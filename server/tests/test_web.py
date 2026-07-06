"""
test_web.py — READ-представления /web/*: корректность данных и ролевой scope.

Данные заводятся как в бою: админ пушит группы/предметы/занятия/пользователей/оценки
через /sync/push (студенты — это users с ролью student). Вход в тестах — через host-
устройство (conftest шлёт X-Device-Id хоста), поэтому барьер проходят все; проверяем
именно ролевой scope и совпадение расчёта с grading.py.
"""
from conftest import make_admin, make_teacher
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
