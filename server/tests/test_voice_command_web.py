"""
test_voice_command_web.py — голосовые команды преподавателя НА САЙТЕ
(POST /web/vector/voice/command).

Разбор — общий модуль `voice_command.py` из корня, тот же, что на десктопе (его
собственные ~117 тестов лежат в `tests/test_voice_command.py`). Здесь проверяется
СЕРВЕРНАЯ обвязка: права, ростер своей группы, привязка к занятию за сегодня и — главное —
что эндпоинт НИЧЕГО НЕ ПИШЕТ.

Почему на «ничего не пишет» отдельный тест. Соблазн «раз уж разобрали — сразу и поставим»
велик, но тогда оценка появлялась бы от расслышанной фразы без подтверждения человеком.
Голос ошибается (Whisper слышит «Вектор» как «Виктор»), и цена ошибки здесь — оценка не
тому студенту.
"""
from conftest import make_admin, make_teacher


TODAY = None        #заполняется в _seed (дата «сегодня» в формате журнала)


def _seed(client, admin, group="ИС-21", subject="Математика", with_lesson=True):
    """Группа + предмет + назначение преподавателя (+ занятие за сегодня) + два студента."""
    global TODAY
    from datetime import datetime, timezone
    TODAY = datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y")

    from app.security import hash_password
    lessons = []
    if with_lesson:
        lessons = [{"id": "LV1", "group_name": group, "subject": subject,
                    "type": "Практика", "number": 1, "topic": "т", "date": TODAY}]
    students = [
        {"id": "stud:ivanov", "role": "student", "login": "ivanov",
         "password_hash": hash_password("p1"), "surname": "Иванов", "name": "Пётр",
         "full_name": "Иванов Пётр", "group_name": group},
        {"id": "stud:petrov", "role": "student", "login": "petrov",
         "password_hash": hash_password("p2"), "surname": "Петров", "name": "Сергей",
         "full_name": "Петров Сергей", "group_name": group},
    ]
    r = client.post("/sync/push", json={"changes": {"lessons": lessons, "users": students}},
                    headers=admin)
    assert r.status_code == 200, r.text
    teach = make_teacher(client, admin, subjects=[subject])
    assert client.post("/web/admin/groups", json={"name": group, "subjects": [subject]},
                       headers=admin).status_code in (200, 409)
    assert client.post("/web/admin/group-hours",
                       json={"group": group, "teachers": {subject: "teach:teacher1"}},
                       headers=admin).status_code == 200
    return teach


def _ask(client, headers, text, group="ИС-21", subject="Математика"):
    return client.post("/web/vector/voice/command",
                       json={"text": text, "group": group, "subject": subject},
                       headers=headers)


def test_single_grade_is_only_proposed_not_written(client):
    """Ключевой инвариант: разбор ПРЕДЛАГАЕТ, а не ставит. Оценки в журнале после вызова
    быть не должно — её поставит `/web/teacher/grade` после подтверждения человеком."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    r = _ask(client, teach, "Иванову пять")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "grades"
    assert body["items"] == [{"surname": "Иванов", "name": "Пётр", "who": "Иванов Пётр",
                             "action": "grade", "grade": "5"}]
    assert body["lesson_id"] == "LV1", "оценка привязана к занятию за сегодня"

    #В журнале — пусто: ничего не записано. Проверяем ЗНАЧЕНИЯ, а не наличие словаря:
    #журнал отдаёт ключ на каждое занятие, просто с пустой оценкой.
    j = client.get("/web/teacher/journal",
                   params={"group": "ИС-21", "subject": "Математика"}, headers=teach).json()
    written = [(s["surname"], k, v) for s in j.get("students", [])
               for k, v in (s.get("grades") or {}).items() if (v or "").strip()]
    assert written == [], f"разбор не имеет права писать в журнал: {written}"


def test_proposal_can_be_written_through_the_existing_endpoint(client):
    """Подтверждение идёт ТЕМ ЖЕ путём, что ручная простановка — отдельного «голосового»
    пути записи нет. Проверяем сквозной сценарий: разобрали → записали → видно в журнале."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    body = _ask(client, teach, "Иванову пять").json()
    item = body["items"][0]
    r = client.post("/web/teacher/grade", json={
        "surname": item["surname"], "name": item["name"],
        "lesson_id": body["lesson_id"], "grade": item["grade"]}, headers=teach)
    assert r.status_code == 200, r.text

    j = client.get("/web/teacher/journal",
                   params={"group": "ИС-21", "subject": "Математика"}, headers=teach).json()
    got = {s["surname"]: (s.get("grades") or {}) for s in j["students"]}
    assert got["Иванов"].get("LV1", "").startswith("5"), got


def test_batch_grades_for_two_students(client):
    """Пакетная команда: несколько студентов за один раз — это и есть смысл голоса."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    body = _ask(client, teach, "Иванову пять Петрову четыре").json()
    assert body["kind"] == "grades"
    pairs = {i["surname"]: i["grade"] for i in body["items"]}
    assert pairs == {"Иванов": "5", "Петров": "4"}


def test_absence_is_recognised(client):
    admin = make_admin(client)
    teach = _seed(client, admin)
    body = _ask(client, teach, "Петров отсутствовал").json()
    assert body["kind"] == "grades"
    assert body["items"][0]["action"] == "absent_n"
    assert body["items"][0]["grade"] == "Н"


def test_question_goes_to_qa_not_to_journal(client):
    """Вопрос НЕ должен превращаться в запись: «сколько пропусков у Иванова» — это вопрос,
    хотя в нём есть и фамилия, и слово про пропуски."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    body = _ask(client, teach, "сколько пропусков у Иванова").json()
    assert body["kind"] == "question" and body["is_question"] is True
    assert body["items"] == []


def test_no_lesson_today_is_explained_not_guessed(client):
    """Занятия за сегодня нет — честная ошибка с подсказкой, а НЕ привязка к произвольному
    занятию: «оценка не за то занятие» тихо портит журнал."""
    admin = make_admin(client)
    teach = _seed(client, admin, with_lesson=False)
    body = _ask(client, teach, "Иванову пять").json()
    assert body["lesson_id"] == ""
    assert body["error"], "должна быть внятная причина"


def test_lesson_creation_is_parsed(client):
    admin = make_admin(client)
    teach = _seed(client, admin)
    body = _ask(client, teach, "создай сегодня лекцию по теме интегралы").json()
    assert body["kind"] == "lesson"
    assert body["lesson"]["type"] == "Лекция"
    assert "интеграл" in body["lesson"]["topic"].lower()


def test_foreign_group_is_refused(client):
    """Чужая группа — 403 ДО разбора: ростер уходит в подсказку распознавателя, то есть
    сам состав группы является данными, которые нельзя отдавать не своему преподавателю."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    assert _ask(client, teach, "Иванову пять", group="К-99").status_code == 403


def test_student_cannot_use_voice_commands(client):
    """Запись голосом — способность преподавателя. Студент не должен даже разбирать."""
    admin = make_admin(client)
    _seed(client, admin)
    r = client.post("/auth/login", json={"login": "ivanov", "password": "p1"})
    sh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert _ask(client, sh, "Иванову пять").status_code == 403


def test_admin_cannot_use_teacher_voice_writes(client):
    """Админ ведёт справочники, а не журнал: у него нет назначений, и путь записи не его."""
    admin = make_admin(client)
    _seed(client, admin)
    assert _ask(client, admin, "Иванову пять").status_code == 403


def test_empty_text_rejected(client):
    admin = make_admin(client)
    teach = _seed(client, admin)
    assert _ask(client, teach, "   ").status_code == 400
