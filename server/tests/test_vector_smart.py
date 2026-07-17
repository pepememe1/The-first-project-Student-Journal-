"""
test_vector_smart.py — «умный» Вектор на сервере: единый лексикон (vector_nlu),
новые интенты (счёт оценок, оценки по предмету) и роль-скоуп.

Проверяем, что веб-Вектор больше не отстаёт от десктопа: 8 интентов рукописной цепочки
if заменены на общий классификатор. Числа берём из РЕАЛЬНЫХ данных (SQL), не из модели.
"""
from conftest import make_admin, make_teacher
from app.security import hash_password


def _push(client, headers, **entities):
    return client.post("/sync/push", json={"changes": entities}, headers=headers)


def _mk_student(client, admin, login, surname, name, group, pw="studpass1"):
    client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password(pw), "surname": surname, "name": name,
        "group_name": group}]}}, headers=admin)
    r = client.post("/auth/login", json={"login": login, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed(client, admin):
    """Группа ИС-21, предметы Математика/Физика, студент Иванов с оценками 5,4 и 3."""
    _push(client, admin,
          groups=[{"id": "grp:ИС-21", "name": "ИС-21",
                   "subjects": ["Математика", "Физика"]}],
          lessons=[
              {"id": "M1", "group_name": "ИС-21", "subject": "Математика",
               "type": "Практика", "number": 1, "topic": "т", "date": "01.09.2025"},
              {"id": "M2", "group_name": "ИС-21", "subject": "Математика",
               "type": "Практика", "number": 2, "topic": "т", "date": "08.09.2025"},
              {"id": "F1", "group_name": "ИС-21", "subject": "Физика",
               "type": "Практика", "number": 1, "topic": "т", "date": "02.09.2025"},
          ],
          grades=[
              {"id": "Иванов|Иван|M1", "student_f": "Иванов", "student_n": "Иван",
               "lesson_id": "M1", "grade": "5"},
              {"id": "Иванов|Иван|M2", "student_f": "Иванов", "student_n": "Иван",
               "lesson_id": "M2", "grade": "4"},
              {"id": "Иванов|Иван|F1", "student_f": "Иванов", "student_n": "Иван",
               "lesson_id": "F1", "grade": "3"},
          ])


def _ask(client, headers, msg):
    return client.post("/web/vector/ask", json={"message": msg}, headers=headers).json()


def test_student_grade_count(client):
    """«сколько у меня оценок» — новый интент grade_count с реальным счётом."""
    admin = make_admin(client)
    _seed(client, admin)
    sa = _mk_student(client, admin, "iv", "Иванов", "Иван", "ИС-21")
    r = _ask(client, sa, "сколько у меня оценок")
    assert r["intent"] == "grade_count", r
    assert r["facts"]["всего"] == 3, r          # 5,4,3
    assert "3" in r["text"]


def test_student_grade_count_by_subject(client):
    """«сколько оценок по математике» — счёт по конкретному предмету."""
    admin = make_admin(client)
    _seed(client, admin)
    sa = _mk_student(client, admin, "iv", "Иванов", "Иван", "ИС-21")
    r = _ask(client, sa, "сколько оценок по математике")
    assert r["intent"] == "grade_count", r
    assert r["facts"]["всего"] == 2, r          # только математика: 5,4


def test_student_subject_grades(client):
    """«оценки по математике» — интент subject_grades с распознаванием предмета."""
    admin = make_admin(client)
    _seed(client, admin)
    sa = _mk_student(client, admin, "iv", "Иванов", "Иван", "ИС-21")
    r = _ask(client, sa, "какие у меня оценки по математике")
    assert r["intent"] == "subject_grades", r
    assert r["facts"]["subject"] == "Математика", r


def test_student_cannot_see_roster(client):
    """Роль-скоуп: студент НЕ получает список одногруппников (чужие ПДн)."""
    admin = make_admin(client)
    _seed(client, admin)
    sa = _mk_student(client, admin, "iv", "Иванов", "Иван", "ИС-21")
    _mk_student(client, admin, "pe", "Петров", "Пётр", "ИС-21")
    r = _ask(client, sa, "список студентов группы")
    assert r["intent"] != "roster", r           # студенту роспись недоступна
    assert "Петров" not in r["text"]


def test_teacher_roster_and_groups(client):
    """Преподаватель: список студентов своей группы и свои группы."""
    admin = make_admin(client)
    _seed(client, admin)
    th = make_teacher(client, admin, login="t1", subjects=["Математика"])
    _mk_student(client, admin, "iv", "Иванов", "Иван", "ИС-21")

    r = _ask(client, th, "список студентов группы")
    assert r["intent"] == "roster", r
    assert "Иванов" in r["text"]
    r2 = _ask(client, th, "какие у меня группы")
    assert r2["intent"] == "groups", r2
    assert "ИС-21" in r2["text"]


def test_admin_teachers_and_groups(client):
    """Админ: справочники преподавателей и групп."""
    admin = make_admin(client)
    _seed(client, admin)
    make_teacher(client, admin, login="t1", subjects=["Математика"])

    r = _ask(client, admin, "какие преподаватели есть")
    assert r["intent"] == "teachers", r
    r2 = _ask(client, admin, "какие группы есть")
    assert r2["intent"] == "groups", r2
    assert "ИС-21" in r2["text"]


def test_server_uses_shared_lexicon():
    """Ключевой инвариант: сервер разбирает запрос ТЕМ ЖЕ vector_nlu, что и десктоп
    (десктопный vector/faq.py его реэкспортирует — держат клиентские тесты). Значит один
    вопрос даёт ОДИН интент на обеих платформах: вторая упрощённая копия на сервере убрана.
    Модуль ЧИСТЫЙ (без PySide6), поэтому сервер тянет его без десктопных зависимостей."""
    import vector_nlu
    for q, expected in [("сколько у меня оценок", "grade_count"),
                        ("оценки по информатике", "subject_grades"),
                        ("когда математика", "schedule"),
                        ("у кого долги", "debtors")]:
        assert vector_nlu.classify(q, subjects=["Информатика", "Математика"])["intent"] == expected
