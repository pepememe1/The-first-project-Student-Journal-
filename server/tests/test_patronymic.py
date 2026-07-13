"""
test_patronymic.py — Отчество ОТДЕЛЬНЫМ полем (users.patronymic).

Инвариант безопасности: name хранит «Имя Отчество» и остаётся КЛЮЧОМ оценок
(grades.student_n) — его формат не меняется, оценки не осиротеют, десктоп не
рассинхронится. patronymic — дополнительное поле для раздельного показа/ввода.
"""
from conftest import make_admin
from app.security import hash_password


def _push(client, h, **ent):
    return client.post("/sync/push", json={"changes": ent}, headers=h)


def _students(client, h):
    return {s["login"]: s for s in client.get("/web/admin/students", headers=h).json()["students"]}


def test_create_with_separate_patronymic_keeps_name_as_key(client):
    h = make_admin(client)
    r = client.post("/web/admin/students", json={
        "surname": "Пупкин", "name": "Пётр", "patronymic": "Петрович",
        "login": "pupkin", "group": "G1", "password": "pass1234"}, headers=h)
    assert r.status_code == 200, r.text
    s = _students(client, h)["pupkin"]
    #name — полная форма (ключ), имя и отчество — раздельно
    assert s["name"] == "Пётр Петрович", s
    assert s["first_name"] == "Пётр" and s["patronymic"] == "Петрович", s


def test_backward_compat_full_name_without_patronymic(client):
    h = make_admin(client)
    #старый фронт: имя одной строкой «Имя Отчество», отчество не передано
    r = client.post("/web/admin/students", json={
        "surname": "Гордеев", "name": "Ярослав Борисович",
        "login": "gordeev", "group": "G1"}, headers=h)
    assert r.status_code == 200, r.text
    s = _students(client, h)["gordeev"]
    assert s["name"] == "Ярослав Борисович"      #ключ не изменился
    assert s["first_name"] == "Ярослав" and s["patronymic"] == "Борисович", s


def test_grade_attaches_to_combined_name_key(client):
    """Оценка ключуется по полному name («Имя Отчество») — студент её видит, не осиротела."""
    h = make_admin(client)
    L = {"id": "L1", "group_name": "G1", "subject": "Мат", "type": "Практика", "number": 1}
    st = {"id": "stud:p1", "role": "student", "login": "p1", "surname": "Пупкин",
          "name": "Пётр Петрович", "patronymic": "Петрович", "group_name": "G1",
          "password_hash": hash_password("pass1")}
    g = {"id": "Пупкин|Пётр Петрович|L1", "student_f": "Пупкин",
         "student_n": "Пётр Петрович", "lesson_id": "L1", "grade": "5"}
    assert _push(client, h, lessons=[L], users=[st], grades=[g]).status_code == 200

    r = client.post("/auth/login", json={"login": "p1", "password": "pass1"})
    assert r.status_code == 200, r.text
    hs = {"Authorization": f"Bearer {r.json()['access_token']}"}
    jr = client.get("/web/student/journal", headers=hs).json()
    all_grades = [it["grade"] for subj in jr["subjects"] for it in subj["lessons"]]
    assert "5" in all_grades, all_grades


def test_backfill_populates_patronymic_from_name(client):
    """Бэкфилл заполняет patronymic из name, НЕ меняя сам name (ключ)."""
    from app import db as dbmod
    from app.models import User
    from app.db import SessionLocal
    s = SessionLocal()
    try:
        s.add(User(id="stud:bf", role="student", login="bf", surname="Иванов",
                   name="Иван Иванович", patronymic="", group_name="G1"))
        s.commit()
    finally:
        s.close()
    dbmod._backfill_patronymic()
    s = SessionLocal()
    try:
        u = s.get(User, "stud:bf")
        assert u.name == "Иван Иванович"      #ключ не тронут
        assert u.patronymic == "Иванович"     #отчество заполнено
    finally:
        s.close()
