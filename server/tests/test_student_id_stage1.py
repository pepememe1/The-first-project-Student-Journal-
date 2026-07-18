"""
test_student_id_stage1.py — СЕРВЕР: оценки несут неизменяемый student_id.

Зеркало клиентского tests/test_student_id_stage1.py (правки делаем на ОБЕИХ платформах).
Этап 1 миграции с ФИО-ключей: поле добавочное, PK прежний, пустое значение законно.
Главное, что здесь проверяется, — обратная совместимость. Сервер обновляется раньше
десктопов, и если бы он требовал новое поле, синк лёг бы у всех непроапгрейженных ПК.
"""
from conftest import make_admin, make_teacher


def _push(client, headers, **entities):
    return client.post("/sync/push", json={"changes": entities}, headers=headers)


def _seed(client, admin):
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    _push(client, admin,
          lessons=[{"id": "L1", "group_name": "ИС-21", "subject": "Математика",
                    "type": "Практика", "number": 1, "topic": "т", "date": "01.09.2025"}])


def test_web_grade_write_fills_student_id(client):
    """Запись оценки с сайта проставляет id: студент там уже найден (проверка «состоит
    в группе занятия»), так что связь ставится бесплатно и сразу."""
    admin = make_admin(client)
    _seed(client, admin)
    teach = make_teacher(client, admin)
    r = client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "5"},
        headers=teach)
    assert r.status_code == 200, r.text

    ch = client.get("/sync/pull", headers=admin).json()["changes"]
    g = [x for x in ch["grades"] if x["id"] == "Иванова|Мария|L1"][0]
    assert g["student_id"] == "stud:ivanova", "оценка обязана нести id студента"


def test_push_without_student_id_is_accepted(client):
    """СТАРЫЙ клиент шлёт оценку без поля — сервер принимает, а не отвечает ошибкой.
    Иначе обновление сервера положило бы синхронизацию всем старым десктопам."""
    admin = make_admin(client)
    _seed(client, admin)
    r = _push(client, admin, grades=[{
        "id": "Иванова|Мария|L1", "student_f": "Иванова", "student_n": "Мария",
        "lesson_id": "L1", "grade": "4"}])
    assert r.status_code == 200, r.text

    ch = client.get("/sync/pull", headers=admin).json()["changes"]
    g = [x for x in ch["grades"] if x["id"] == "Иванова|Мария|L1"][0]
    assert g["grade"] == "4"
    assert g.get("student_id", "") == "", "пустой id законен на этапе 1"


def test_push_with_student_id_round_trips(client):
    """Новый клиент прислал id — сервер его сохраняет и отдаёт обратно в дельте."""
    admin = make_admin(client)
    _seed(client, admin)
    _push(client, admin, grades=[{
        "id": "Иванова|Мария|L1", "student_f": "Иванова", "student_n": "Мария",
        "lesson_id": "L1", "grade": "3", "student_id": "stud:ivanova"}])

    ch = client.get("/sync/pull", headers=admin).json()["changes"]
    g = [x for x in ch["grades"] if x["id"] == "Иванова|Мария|L1"][0]
    assert g["student_id"] == "stud:ivanova"


def test_rename_preserves_student_id(client):
    """Ради чего всё затевалось: ФИО поменялось, id остался — связь со студентом цела.
    Если бы перенос истории терял id, миграция обнулялась бы на каждом переименовании."""
    admin = make_admin(client)
    _seed(client, admin)
    teach = make_teacher(client, admin)
    gr = client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "5"},
        headers=teach)
    assert gr.status_code == 200, gr.text

    r = client.put("/web/admin/students/ivanova",
                   json={"surname": "Петрова"}, headers=admin)
    assert r.status_code == 200, r.text

    ch = client.get("/sync/pull", headers=admin).json()["changes"]
    live = [x for x in ch["grades"] if not x.get("deleted")]
    assert live and live[0]["id"] == "Петрова|Мария|L1"
    assert live[0]["student_id"] == "stud:ivanova", "id обязан пережить переименование"
