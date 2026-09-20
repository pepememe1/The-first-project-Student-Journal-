"""
test_namesake_students.py — два полных тёзки в одной группе получают независимые оценки
(находка ревью J08, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
Запись искала студента `.first()` по паре (фамилия, имя) в группе, а выборка оценок
фильтровала по тем же двум полям. Итог: балл доставался первому найденному, а в журнале
у обоих тёзок стояли оценки обоих — и в среднем балле, и в долгах, и в индексе риска
отчисления.

⚠️ Тёзки в одной группе — редкость, но не выдумка, и цена ошибки несимметрична: чужая
двойка идёт в отчёт куратора и родителю.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть `.first()` по ФИО в `write.py` — краснеет первый тест;
убрать `student_id` из выборки `webdata.student_records` — второй.
"""
from conftest import make_admin, make_teacher
from app.security import hash_password

GROUP, SUBJ = "К-71", "Химия"
A, B = "stud:tez_a", "stud:tez_b"


def _setup(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t_tez", subjects=(SUBJ,))
    from app.db import SessionLocal
    from app.routers.web import _common as C
    db = SessionLocal()
    try:
        ty, ts = C.W.current_term(C.W.load_config(db))
    finally:
        db.close()
    r = client.post("/sync/push", json={"changes": {
        "subject_hours": [{
            "id": f"hrs:{GROUP}|{SUBJ}|{ty}|{ts}", "group_name": GROUP, "subject": SUBJ,
            "year": ty, "semester": ts, "hours_total": 32, "teacher_id": "teach:t_tez",
        }],
        "users": [
            {"id": A, "role": "student", "login": "tez_a",
             "password_hash": hash_password("studpass1"),
             "surname": "Иванов", "name": "Иван", "group_name": GROUP},
            {"id": B, "role": "student", "login": "tez_b",
             "password_hash": hash_password("studpass1"),
             "surname": "Иванов", "name": "Иван", "group_name": GROUP},
        ],
    }}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": "Практика", "number": 1,
        "date": "01.09.2026", "topic": "Тема",
    }, headers=teacher)
    assert r.status_code == 200, r.text
    return admin, teacher, r.json()["id"]


def _grade(client, teacher, lid, value, student_id):
    return client.post("/web/teacher/grade", json={
        "surname": "Иванов", "name": "Иван", "lesson_id": lid, "grade": value,
        "student_id": student_id,
    }, headers=teacher)


def test_a_grade_goes_to_the_student_it_was_meant_for(client):
    _, teacher, lid = _setup(client)
    assert _grade(client, teacher, lid, "5", A).status_code == 200
    assert _grade(client, teacher, lid, "2", B).status_code == 200

    from app.db import SessionLocal
    from app.models import Grade, grade_id
    db = SessionLocal()
    try:
        assert (db.get(Grade, grade_id(A, lid)).grade or "") == "5"
        assert (db.get(Grade, grade_id(B, lid)).grade or "") == "2", \
            "оценка второго тёзки ушла первому"
    finally:
        db.close()


def test_the_journal_shows_each_namesake_only_their_own(client):
    _, teacher, lid = _setup(client)
    _grade(client, teacher, lid, "5", A)
    _grade(client, teacher, lid, "2", B)

    r = client.get("/web/teacher/journal", params={"group": GROUP, "subject": SUBJ},
                   headers=teacher)
    assert r.status_code == 200, r.text
    rows = {row["student_id"]: row for row in r.json()["students"]}
    assert set(rows) == {A, B}, f"журнал не различает тёзок: {list(rows)}"
    assert rows[A]["grades"].get(lid) == "5"
    assert rows[B]["grades"].get(lid) == "2", "в строке одного тёзки видна оценка другого"


def test_without_an_id_an_ambiguous_name_is_refused_not_guessed(client):
    """Старый клиент id не шлёт. Лучше честный отказ, чем оценка наугад."""
    _, teacher, lid = _setup(client)
    r = client.post("/web/teacher/grade", json={
        "surname": "Иванов", "name": "Иван", "lesson_id": lid, "grade": "4",
    }, headers=teacher)
    assert r.status_code == 409, f"при двух тёзках сервер выбрал одного молча: {r.status_code}"
    assert "двое" in r.json().get("detail", ""), r.text


def test_a_single_student_still_works_without_an_id(client):
    """Обычный случай — один человек с таким ФИО: прежнее поведение не тронуто."""
    admin, teacher, lid = _setup(client)
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:solo", "role": "student", "login": "solo",
        "password_hash": hash_password("studpass1"),
        "surname": "Доржиев", "name": "Баир", "group_name": GROUP,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/web/teacher/grade", json={
        "surname": "Доржиев", "name": "Баир", "lesson_id": lid, "grade": "4",
    }, headers=teacher)
    assert r.status_code == 200, r.text


def test_term_grades_are_independent_for_namesakes(client):
    _, teacher, _lid = _setup(client)
    for sid, mark in ((A, "5"), (B, "3")):
        r = client.post("/web/teacher/term-grade", json={
            "surname": "Иванов", "name": "Иван", "subject": SUBJ, "group": GROUP,
            "grade": mark, "student_id": sid,
        }, headers=teacher)
        assert r.status_code == 200, r.text

    r = client.get("/web/teacher/term-grades", params={"group": GROUP, "subject": SUBJ},
                   headers=teacher)
    assert r.status_code == 200, r.text
    by_id = r.json().get("grades_by_id") or {}
    assert by_id.get(A, {}).get("grade") == "5"
    assert by_id.get(B, {}).get("grade") == "3", \
        "ведомость показывает тёзкам одну итоговую на двоих"
