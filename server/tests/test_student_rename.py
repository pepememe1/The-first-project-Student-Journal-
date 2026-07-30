"""
test_student_rename.py — смена ФИО студента НЕ ТЕРЯЕТ оценки.

ЭТАП 3 миграции изменил способ, которым это обеспечивается, поэтому и тесты другие.

Было: оценки ключевались по написанию ФИО (`{f}|{n}|{lesson_id}`), и переименование
означало ПЕРЕНОС истории — под новым ФИО создавались копии с новым id, а старые
прикапывались надгробиями. Работало, но было хрупким: сбой посреди переноса оставлял
часть оценок осиротевшими, а на другие ПК уезжала пачка надгробий.

Стало: ключ — неизменяемый student_id, а ФИО в строках оценок живёт лишь как копия для
показа. Поэтому проверяется свойство СИЛЬНЕЕ прежнего: при переименовании ключи не
двигаются вообще и надгробий не появляется — переносить нечего, значит и терять нечего.
"""
from conftest import make_admin, make_teacher, assign_teacher


def _push(client, headers, **entities):
    return client.post("/sync/push", json={"changes": entities}, headers=headers)


def _seed_student_with_grades(client, admin):
    """Оценки ставим ЧЕРЕЗ ЭНДПОИНТ, а не push'ем сырых строк: так ключ считает сам
    сервер, и тест не завязан на формат, который он же и проверяет."""
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    _push(client, admin,
          lessons=[{"id": "L1", "group_name": "ИС-21", "subject": "Математика",
                    "type": "Практика", "number": 1, "topic": "т", "date": "01.09.2025"}])
    teach = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    r = client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "5"},
        headers=teach)
    assert r.status_code == 200, r.text
    return teach


def _changes(client, admin):
    return client.get("/sync/pull", headers=admin).json()["changes"]


def test_rename_keeps_grades_under_same_key(client):
    """Главное свойство этапа 3: фамилия сменилась, а КЛЮЧ остался прежним.

    Раньше тут проверялось «оценка доступна под новым ключом». Теперь правильная
    проверка — что ключ менять и не пришлось: он не зависит от написания ФИО."""
    admin = make_admin(client)
    _seed_student_with_grades(client, admin)
    before = {g["id"] for g in _changes(client, admin)["grades"]}

    r = client.put("/web/admin/students/ivanova",
                   json={"surname": "Петрова"}, headers=admin)
    assert r.status_code == 200, r.text

    after = _changes(client, admin)["grades"]
    assert {g["id"] for g in after} == before, "ключи оценок не должны меняться"
    assert len(after) == 1, "переименование не должно плодить строк"
    assert after[0]["student_f"] == "Петрова", "ФИО-копия обязана обновиться"
    assert after[0]["grade"] == "5", "сама оценка не пострадала"


def test_key_is_built_from_student_id_not_name(client):
    """Ключ строится по id студента. Это и есть то, что делает переименование дешёвым."""
    admin = make_admin(client)
    _seed_student_with_grades(client, admin)
    ids = [g["id"] for g in _changes(client, admin)["grades"]]
    assert ids == ["stud:ivanova|L1"], "ключ по неизменяемому id, а не по ФИО"


def test_rename_creates_no_tombstones(client):
    """Надгробий больше нет вовсе. Раньше их создавал перенос истории, и они пачкой
    уезжали на другие ПК; теперь переносить нечего, значит и хоронить нечего."""
    admin = make_admin(client)
    _seed_student_with_grades(client, admin)
    client.put("/web/admin/students/ivanova", json={"surname": "Петрова"}, headers=admin)

    ch = _changes(client, admin)
    dead = [g for g in ch["grades"] + ch["term_grades"] if g.get("deleted")]
    assert dead == [], "переименование не должно оставлять надгробий"


def test_rename_without_name_change_is_noop(client):
    """Правка без смены ФИО (например, только группы) историю не трогает."""
    admin = make_admin(client)
    _seed_student_with_grades(client, admin)
    before = _changes(client, admin)["grades"]

    r = client.put("/web/admin/students/ivanova", json={"group": "ИС-22"}, headers=admin)
    assert r.status_code == 200, r.text

    after = _changes(client, admin)["grades"]
    assert [g["id"] for g in after] == [g["id"] for g in before]
    assert after[0]["updated_at"] == before[0]["updated_at"], \
        "без реальной правки метку двигать незачем — строка зря уехала бы в дельте"


def test_student_still_sees_own_grades_after_rename(client):
    """Проверка с другого конца: после переименования студентка видит свою историю.
    Выборки идут по ФИО-копии, и если бы её забыли обновить, оценки «пропали» бы."""
    admin = make_admin(client)
    _seed_student_with_grades(client, admin)
    client.put("/web/admin/students/ivanova", json={"surname": "Петрова"}, headers=admin)

    r = client.post("/auth/login", json={"login": "ivanova", "password": "studpass1"})
    assert r.status_code == 200, r.text
    sh = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}
    ov = client.get("/web/student/overview", headers=sh)
    assert ov.status_code == 200, ov.text
    assert ov.json()["average"] == 5.0, "история оценок должна остаться видимой"
