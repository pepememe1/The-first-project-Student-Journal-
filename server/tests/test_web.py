"""
test_web.py — READ-представления /web/*: корректность данных и ролевой scope.

Данные заводятся как в бою: админ пушит группы/предметы/занятия/пользователей/оценки
через /sync/push (студенты — это users с ролью student). Вход в тестах — через host-
устройство (conftest шлёт X-Device-Id хоста), поэтому барьер проходят все; проверяем
именно ролевой scope и совпадение расчёта с grading.py.
"""
from conftest import make_admin, make_teacher, assign_teacher
from app.security import hash_password


def _seed(client, admin):
    """Группа ИС-21, предмет Математика, две практики и студент Иванов с оценками 5 и 3."""
    student = {"id": "stud:stud1", "role": "student", "login": "stud1",
               "password_hash": hash_password("studpass1"),
               "surname": "Иванов", "name": "Иван", "group_name": "ИС-21"}
    lessons = [
        {"id": "L1", "group_name": "ИС-21", "subject": "Математика",
         "type": "Практика", "number": 1, "topic": "Пределы", "date": "01.09.2025"},
        {"id": "L2", "group_name": "ИС-21", "subject": "Математика",
         "type": "Практика", "number": 2, "topic": "Производные", "date": "08.09.2025"},
    ]
    grades = [
        {"id": "Иванов|Иван|L1", "student_f": "Иванов", "student_n": "Иван",
         "lesson_id": "L1", "grade": "5"},
        {"id": "Иванов|Иван|L2", "student_f": "Иванов", "student_n": "Иван",
         "lesson_id": "L2", "grade": "3"},
    ]
    r = client.post("/sync/push", json={"changes": {
        "groups": [{"id": "g:ИС-21", "name": "ИС-21", "subjects": ["Математика"]}],
        "subjects": [{"id": "s:Математика", "name": "Математика"}],
        "users": [student], "lessons": lessons, "grades": grades,
    }}, headers=admin)
    assert r.status_code == 200, r.text


def _login(client, login, password):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# СТУДЕНТ ──────────────────────────────────────────────────────────────────────
def test_student_overview_average_matches_grading(client):
    admin = make_admin(client)
    _seed(client, admin)
    h = _login(client, "stud1", "studpass1")
    data = client.get("/web/student/overview", headers=h).json()
    assert data["group"] == "ИС-21"
    assert data["average"] == 4.0          # (5 + 3) / 2 — единый расчёт grading
    assert data["debts"] == 0
    assert len(data["recent"]) == 2


def test_student_journal_grouped_by_subject(client):
    admin = make_admin(client)
    _seed(client, admin)
    h = _login(client, "stud1", "studpass1")
    data = client.get("/web/student/journal", headers=h).json()
    assert len(data["subjects"]) == 1
    subj = data["subjects"][0]
    assert subj["subject"] == "Математика"
    assert len(subj["lessons"]) == 2
    assert subj["average"] == 4.0
    #оценка проставлена именно этому студенту
    assert {l["grade"] for l in subj["lessons"]} == {"5", "3"}


def test_overview_and_journal_show_plan_subject_with_no_lessons_yet(client):
    """Живой баг: «на Главной 2 предмета, в Журнале 4, в Статистике весь список» —
    три экрана по-разному отвечали на «сколько у меня предметов». Предмет
    ДЕЙСТВУЮЩЕГО плана без единого занятия обязан быть виден ВЕЗДЕ (не пропадать,
    пока преподаватель не откроет журнал), а не только в статистике."""
    admin = make_admin(client)
    _seed(client, admin)   # план: {"Математика"} + 2 занятия
    #Второй предмет ЕСТЬ в плане группы, но занятий по нему нет вовсе.
    r = client.post("/sync/push", json={"changes": {
        "groups": [{"id": "g:ИС-21", "name": "ИС-21", "subjects": ["Математика", "Физика"]}],
    }}, headers=admin)
    assert r.status_code == 200, r.text
    h = _login(client, "stud1", "studpass1")

    ov = client.get("/web/student/overview", headers=h).json()
    assert {s["subject"] for s in ov["subjects"]} == {"Математика", "Физика"}
    phys = next(s for s in ov["subjects"] if s["subject"] == "Физика")
    assert phys["grades"] == 0

    jr = client.get("/web/student/journal", headers=h).json()
    assert {s["subject"] for s in jr["subjects"]} == {"Математика", "Физика"}
    phys_j = next(s for s in jr["subjects"] if s["subject"] == "Физика")
    assert phys_j["lessons"] == [] and phys_j["average"] == 0


def test_overview_does_not_blend_a_recurring_subject_across_past_courses(client):
    """Живой баг 3.6.1: «Физра» (и любой другой предмет, повторяющийся каждый курс)
    числится в плане группы КАЖДЫЙ семестр — group_lessons(db, group) без year/semester
    возвращает историю группы ЦЕЛИКОМ, а фильтр по имени предмета (current_subject_
    lessons) её не сужает. Без term-фильтра «средний балл сейчас» тянул бы оценки за
    ВСЕ прошлые курсы той же группы. Проверяем ровно этот сценарий: двойка за физру
    два года назад не должна портить сегодняшнюю пятёрку."""
    admin = make_admin(client)
    student = {"id": "stud:phys1", "role": "student", "login": "phys1",
               "password_hash": hash_password("physpass1"),
               "surname": "Орлов", "name": "Олег", "group_name": "ИС-99"}
    old_lesson = {"id": "PhysOld", "group_name": "ИС-99", "subject": "Физическая культура",
                  "type": "Практика", "number": 1, "topic": "т", "date": "01.09.2022",
                  "year": "2022/2023", "semester": 1}
    new_lesson = {"id": "PhysNew", "group_name": "ИС-99", "subject": "Физическая культура",
                  "type": "Практика", "number": 1, "topic": "т", "date": "01.09.2025",
                  "year": "2025/2026", "semester": 2}
    r = client.post("/sync/push", json={"changes": {
        "groups": [{"id": "g:ИС-99", "name": "ИС-99", "subjects": ["Физическая культура"]}],
        "users": [student], "lessons": [old_lesson, new_lesson],
        "grades": [{"id": "Орлов|Олег|PhysOld", "student_f": "Орлов", "student_n": "Олег",
                    "lesson_id": "PhysOld", "grade": "2"},
                   {"id": "Орлов|Олег|PhysNew", "student_f": "Орлов", "student_n": "Олег",
                    "lesson_id": "PhysNew", "grade": "5"}],
    }}, headers=admin)
    assert r.status_code == 200, r.text
    h = _login(client, "phys1", "physpass1")

    ov = client.get("/web/student/overview", headers=h).json()
    #Сегодняшний термин видит ровно текущую пятёрку, а не (2+5)/2=3.5 из обоих курсов.
    assert ov["average"] == 5.0, ov
    phys = next(s for s in ov["subjects"] if s["subject"] == "Физическая культура")
    assert phys["grades"] == 1, phys


def test_student_cannot_access_teacher_view(client):
    admin = make_admin(client)
    _seed(client, admin)
    h = _login(client, "stud1", "studpass1")
    r = client.get("/web/teacher/journal", params={"group": "ИС-21", "subject": "Математика"},
                   headers=h)
    assert r.status_code == 403


def test_student_sees_only_own_grades(client):
    """Второй студент с другими оценками не «протекает» в overview первого."""
    admin = make_admin(client)
    _seed(client, admin)
    #второй студент той же группы с двойками
    client.post("/sync/push", json={"changes": {
        "users": [{"id": "stud:stud2", "role": "student", "login": "stud2",
                   "password_hash": hash_password("studpass2"),
                   "surname": "Петров", "name": "Пётр", "group_name": "ИС-21"}],
        "grades": [{"id": "Петров|Пётр|L1", "student_f": "Петров", "student_n": "Пётр",
                    "lesson_id": "L1", "grade": "2"},
                   {"id": "Петров|Пётр|L2", "student_f": "Петров", "student_n": "Пётр",
                    "lesson_id": "L2", "grade": "2"}],
    }}, headers=admin)
    h1 = _login(client, "stud1", "studpass1")
    assert client.get("/web/student/overview", headers=h1).json()["average"] == 4.0
    h2 = _login(client, "stud2", "studpass2")
    assert client.get("/web/student/overview", headers=h2).json()["average"] == 2.0


# ПРЕПОДАВАТЕЛЬ ──────────────────────────────────────────────────────────────────
def test_teacher_journal_scoped_by_subject(client):
    admin = make_admin(client)
    _seed(client, admin)
    th = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    ok = client.get("/web/teacher/journal",
                    params={"group": "ИС-21", "subject": "Математика"}, headers=th)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert len(body["lessons"]) == 2
    row = [s for s in body["students"] if s["surname"] == "Иванов"][0]
    assert row["average"] == 4.0
    #чужой предмет — 403 (row-level scope, как в /sync/push)
    forbidden = client.get("/web/teacher/journal",
                           params={"group": "ИС-21", "subject": "Физика"}, headers=th)
    assert forbidden.status_code == 403


def test_teacher_overview_lists_groups_from_lessons(client):
    admin = make_admin(client)
    _seed(client, admin)
    th = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    data = client.get("/web/teacher/overview", headers=th).json()
    assert data["subjects"] == ["Математика"]
    assert "ИС-21" in data["groups"]


# АДМИНИСТРАТОР ───────────────────────────────────────────────────────────────────
def test_admin_overview_counts(client):
    admin = make_admin(client)
    _seed(client, admin)
    make_teacher(client, admin, subjects=["Математика"])
    data = client.get("/web/admin/overview", headers=admin).json()
    assert data["students"] == 1
    assert data["teachers"] == 1
    assert data["subjects"] == 1
    assert data["groups"] == 1
    assert data["lessons"] == 2
    assert data["grades"] == 2


def test_admin_students_listing(client):
    admin = make_admin(client)
    _seed(client, admin)
    data = client.get("/web/admin/students", headers=admin).json()
    #Ответ теперь несёт и контактные/сессионные поля (телефон, последний вход, IP,
    #устройство) — у свежесозданного студента они пустые. Проверяем базовые + наличие.
    s = data["students"][0]
    assert (s["login"], s["surname"], s["name"], s["group"]) == \
        ("stud1", "Иванов", "Иван", "ИС-21")
    assert s["phone"] == "" and s["last_login"] == "" and s["ip"] == "" and s["device"] == ""


def test_web_endpoints_require_auth(client):
    assert client.get("/web/student/overview").status_code == 401
    assert client.get("/web/admin/overview").status_code == 401


# «ВЕКТОР» ─────────────────────────────────────────────────────────────────────────
def test_vector_uses_real_average(client):
    """«Вектор» берёт средний из реальных данных (не выдумывает)."""
    admin = make_admin(client)
    _seed(client, admin)
    h = _login(client, "stud1", "studpass1")
    r = client.post("/web/vector/ask", json={"message": "какой мой средний балл?"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["facts"]["average"] == 4.0
    assert "4.0" in body["text"]
