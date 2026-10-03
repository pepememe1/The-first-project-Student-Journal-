"""
test_scale_conversion.py — смена шкалы оценивания переводит уже поставленные оценки (01.10.2026).

━━ ЗАЧЕМ ━━
Живой прогон стенда: преподаватель сменил шкалу на 100-балльную — и прежние «5/4/3»
стали «5 из 100»: у всей группы средний 2.0, долгов втрое больше, студент и родитель
увидели двойки; в буквенной шкале старые оценки пропали из журнала вовсе. Оценка
хранится сырой строкой и читается по ТЕКУЩЕЙ шкале — значит, смена шкалы обязана
переводить значения. Правила — решение Ярослава (см. grading.convert_scale_value).
"""
import pytest

import grading
from conftest import make_admin, assign_teacher
from app.security import hash_password

G = "К74/1"


# ── правила перевода одного значения ───────────────────────────────────────────────

@pytest.mark.parametrize("raw,src,dst,options,default", [
    ("5", "5", "letter", ["A"], "A"),
    ("4", "5", "letter", ["B"], "B"),
    ("2", "5", "letter", ["F"], "F"),
    ("5", "5", "100", ["100"], "100"),
    ("3", "5", "100", ["60"], "60"),
    ("B", "letter", "100", ["80"], "80"),
    ("D", "letter", "5", ["2"], "2"),
    ("80", "100", "5", ["4"], "4"),                 # делится нацело — переводится сам
    ("73", "100", "5", ["3", "4"], "4"),            # пример Ярослава: 3,65 → спорное, ближе 4
    ("70", "100", "5", ["3", "4"], "3"),            # ровно 3,5: ничья — вниз, не завышаем
    ("91", "100", "letter", ["B", "A"], "A"),
    ("30", "100", "5", ["2"], "2"),                 # ниже двойки шкалы нет
    ("Зачтено", "pass_fail", "5", ["3", "4", "5"], "3"),
    ("3", "5", "pass_fail", ["Зачтено"], "Зачтено"),
    ("55", "100", "pass_fail", ["Не зачтено"], "Не зачтено"),
])
def test_conversion_rules(raw, src, dst, options, default):
    assert grading.convert_scale_value(raw, src, dst) == (options, default)


@pytest.mark.parametrize("raw", ["Н", "Б", "О", "", "✓", "мусор"])
def test_attendance_and_garbage_are_left_alone(raw):
    assert grading.convert_scale_value(raw, "5", "100") is None


# ── перевод журнала ────────────────────────────────────────────────────────────────

@pytest.fixture()
def world(client):
    from app.db import default_term
    ty, ts = default_term()
    y0 = int(ty.split("/")[0])
    prev_y = f"{y0 - 1}/{y0}"
    admin = make_admin(client)
    users = [
        {"id": "stud:s1", "role": "student", "login": "s1", "surname": "Иванов",
         "name": "Иван Петрович", "full_name": "Иванов Иван Петрович", "group_name": G,
         "password_hash": hash_password("studpass1")},
        {"id": "stud:s2", "role": "student", "login": "s2", "surname": "Петрова",
         "name": "Анна Сергеевна", "full_name": "Петрова Анна Сергеевна", "group_name": G,
         "password_hash": ""},
        {"id": "teach:t1", "role": "teacher", "login": "t1", "surname": "Орлова",
         "name": "Анна Петровна", "full_name": "Орлова Анна Петровна",
         "subjects": ["Математика"], "password_hash": hash_password("teachpass1")},
        {"id": "teach:t2", "role": "teacher", "login": "t2", "surname": "Цыренов",
         "name": "Баир Дугарович", "full_name": "Цыренов Баир Дугарович",
         "subjects": ["Физика"], "password_hash": hash_password("teachpass2")},
    ]
    lessons = [
        {"id": "m-1", "group_name": G, "subject": "Математика", "type": "Практика",
         "number": 1, "topic": "т", "date": "02.09.2026", "year": ty, "semester": ts},
        {"id": "m-2", "group_name": G, "subject": "Математика", "type": "ДЗ",
         "number": 1, "topic": "т", "date": "04.09.2026", "year": ty, "semester": ts},
        {"id": "m-lec", "group_name": G, "subject": "Математика", "type": "Лекция",
         "number": 1, "topic": "т", "date": "05.09.2026", "year": ty, "semester": ts},
        {"id": "m-ex", "group_name": G, "subject": "Математика", "type": "Экзамен",
         "number": 1, "topic": "т", "date": "06.09.2026", "year": ty, "semester": ts},
        #Архив прошлого семестра: его тоже читают по ТЕКУЩЕЙ шкале преподавателя.
        {"id": "m-old", "group_name": G, "subject": "Математика", "type": "Практика",
         "number": 1, "topic": "т", "date": "02.03.2026", "year": prev_y, "semester": 2},
        #Чужой предмет — чужая шкала, перевод его не касается.
        {"id": "f-1", "group_name": G, "subject": "Физика", "type": "Практика",
         "number": 1, "topic": "т", "date": "03.09.2026", "year": ty, "semester": ts},
    ]
    marks = {("stud:s1", "m-1"): "5", ("stud:s1", "m-2"): "3", ("stud:s1", "m-lec"): "Н",
             ("stud:s1", "m-ex"): "4", ("stud:s1", "m-old"): "4", ("stud:s1", "f-1"): "5",
             ("stud:s2", "m-1"): "4", ("stud:s2", "m-2"): "Н"}
    grades = [{"id": f"{sid}|{lid}", "student_id": sid,
               "student_f": "Иванов" if sid == "stud:s1" else "Петрова",
               "student_n": "Иван Петрович" if sid == "stud:s1" else "Анна Сергеевна",
               "lesson_id": lid, "grade": v} for (sid, lid), v in marks.items()]
    r = client.post("/sync/push", json={"changes": {
        "groups": [{"id": "grp:1", "name": G, "subjects": ["Математика", "Физика"]}],
        "users": users, "lessons": lessons, "grades": grades}}, headers=admin)
    assert r.status_code == 200, r.text
    assign_teacher(client, admin, "teach:t1", G, "Математика", year=ty, semester=ts)
    assign_teacher(client, admin, "teach:t1", G, "Математика", year=prev_y, semester=2)
    assign_teacher(client, admin, "teach:t2", G, "Физика", year=ty, semester=ts)
    return {"client": client, "teacher": _login(client, "t1", "teachpass1"),
            "student": _login(client, "s1", "studpass1")}


def _login(client, login, password):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _grades(world):
    from app.db import SessionLocal
    from app.models import Grade
    db = SessionLocal()
    try:
        return {g.id: g.grade for g in db.query(Grade).all()}
    finally:
        db.close()


def _avg(world):
    r = world["client"].get("/web/student/overview", headers=world["student"])
    assert r.status_code == 200, r.text
    return r.json()["average"]


def test_switch_to_100_keeps_the_meaning_of_every_grade(world):
    """🔥 Главное свойство: средний студента после смены шкалы тот же, что был."""
    c, t = world["client"], world["teacher"]
    before = _avg(world)
    p = c.post("/web/teacher/grading-scale/preview", json={"scale": "100"}, headers=t).json()
    assert p["from"] == "5" and p["to"] == "100" and not p["disputed"], p
    assert p["auto"] == 4                      # m-1×2, m-2, m-old; «Н», лекция и экзамен — нет
    r = c.post("/web/teacher/grading-scale", json={"scale": "100"}, headers=t)
    assert r.status_code == 200, r.text
    g = _grades(world)
    assert g["stud:s1|m-1"] == "100" and g["stud:s1|m-2"] == "60" and g["stud:s2|m-1"] == "80"
    assert g["stud:s1|m-old"] == "80", "архив читается по текущей шкале — его тоже переводим"
    assert g["stud:s1|m-lec"] == "Н" and g["stud:s2|m-2"] == "Н", "посещаемость не трогаем"
    assert g["stud:s1|m-ex"] == "4", "экзамены на свои шкалы не переводятся"
    assert g["stud:s1|f-1"] == "5", "чужой предмет — чужая шкала"
    assert _avg(world) == before
    prefs = c.get("/me/prefs", headers=t).json()
    assert (prefs.get("prefs") or prefs).get("grading_scale") == "100"


def test_disputed_values_wait_for_the_teachers_choice(world):
    c, t = world["client"], world["teacher"]
    assert c.post("/web/teacher/grading-scale", json={"scale": "100"}, headers=t).status_code == 200
    #Преподаватель уже в 100-балльной ставит «живые» баллы.
    from app.db import SessionLocal
    from app.models import Grade
    db = SessionLocal()
    try:
        db.get(Grade, "stud:s1|m-1").grade = "73"
        db.get(Grade, "stud:s2|m-1").grade = "70"
        db.commit()
    finally:
        db.close()
    p = c.post("/web/teacher/grading-scale/preview", json={"scale": "5"}, headers=t).json()
    disputed = {d["id"]: d for d in p["disputed"]}
    assert disputed["stud:s1|m-1"]["options"] == ["3", "4"]
    assert disputed["stud:s1|m-1"]["default"] == "4"
    assert disputed["stud:s2|m-1"]["default"] == "3"
    assert disputed["stud:s1|m-1"]["student"].startswith("Иванов")
    r = c.post("/web/teacher/grading-scale", headers=t, json={
        "scale": "5", "choices": {"stud:s1|m-1": "3", "stud:s2|m-1": "9"}})
    assert r.status_code == 200, r.text
    g = _grades(world)
    assert g["stud:s1|m-1"] == "3", "выбор преподавателя"
    assert g["stud:s2|m-1"] == "3", "вариант не из списка — берём значение по умолчанию"
    assert g["stud:s1|m-2"] == "3" and g["stud:s1|m-old"] == "4"


def test_old_prefs_door_converts_unambiguous_and_refuses_disputed(world):
    """Старый клиент меняет шкалу через /me/prefs: однозначное переводится само, а при
    спорных — отказ, и журнал НЕ тронут (раньше там была порча всех оценок группы)."""
    c, t = world["client"], world["teacher"]
    r = c.post("/me/prefs", json={"grading_scale": "letter"}, headers=t)
    assert r.status_code == 200, r.text
    g = _grades(world)
    assert g["stud:s1|m-1"] == "A" and g["stud:s1|m-2"] == "C" and g["stud:s2|m-1"] == "B"
    assert c.post("/web/teacher/grading-scale", json={"scale": "100"}, headers=t).status_code == 200
    from app.db import SessionLocal
    from app.models import Grade
    db = SessionLocal()
    try:
        db.get(Grade, "stud:s1|m-1").grade = "73"
        db.commit()
    finally:
        db.close()
    before = _grades(world)
    r = c.post("/me/prefs", json={"grading_scale": "5"}, headers=t)
    assert r.status_code == 409, r.text
    assert _grades(world) == before
    prefs = c.get("/me/prefs", headers=t).json()
    assert (prefs.get("prefs") or prefs).get("grading_scale") == "100"


def test_only_a_teacher_converts_and_only_his_own_journal(world):
    c = world["client"]
    r = c.post("/web/teacher/grading-scale", json={"scale": "100"}, headers=world["student"])
    assert r.status_code == 403
    r = c.post("/web/teacher/grading-scale/preview", json={"scale": "сто"},
               headers=world["teacher"])
    assert r.status_code == 400


def test_second_change_converts_from_the_scale_that_is_really_stored(world):
    """🔒 Две смены шкалы почти одновременно: вторая держит объект преподавателя, загруженный
    ДО первой (шкала «5»), а в базе уже «100». Перевод обязан идти ОТ того, что лежит в
    базе: иначе «100» разбирается как 5-балльная оценка, не распознаётся, остаётся как
    есть — и буквенная шкала её не читает (оценка пропадает из журнала)."""
    from app.db import SessionLocal
    from app.models import User
    from app import scale_conversion as SC
    c, t = world["client"], world["teacher"]
    stale_db = SessionLocal()
    try:
        stale = stale_db.query(User).filter(User.login == "t1").first()
        assert (stale.prefs or {}).get("grading_scale", "5") == "5"      #загружен до смены
        assert c.post("/web/teacher/grading-scale", json={"scale": "100"},
                      headers=t).status_code == 200
        out = SC.apply(stale_db, stale, "letter", {})
    finally:
        stale_db.close()
    assert out["from"] == "100", out
    g = _grades(world)
    assert g["stud:s1|m-1"] == "A" and g["stud:s2|m-1"] == "B" and g["stud:s1|m-2"] == "C", g
