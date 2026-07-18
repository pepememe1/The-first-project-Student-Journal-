"""
test_student_rename.py — смена ФИО студента НЕ ТЕРЯЕТ оценки.

Оценки исторически ключуются по ФИО (§10: `{f}|{n}|{lesson_id}`), поэтому переименование
(замужество, исправление опечатки) отвязывало всю историю: оценки оставались под старым
ключом и «пропадали» у студента. Теперь они переключаются на новый ключ, а старые id
получают надгробие — чтобы удаление доехало на другие ПК и не осталось дублей.
"""
from conftest import make_admin


def _push(client, headers, **entities):
    return client.post("/sync/push", json={"changes": entities}, headers=headers)


def _seed_student_with_grades(client, admin):
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    _push(client, admin,
          lessons=[{"id": "L1", "group_name": "ИС-21", "subject": "Математика",
                    "type": "Практика", "number": 1, "topic": "т", "date": "01.09.2025"}],
          grades=[{"id": "Иванова|Мария|L1", "student_f": "Иванова", "student_n": "Мария",
                   "lesson_id": "L1", "grade": "5"}],
          term_grades=[{"id": "Иванова|Мария|Математика|2025/2026|1",
                        "student_f": "Иванова", "student_n": "Мария", "subject": "Математика",
                        "year": "2025/2026", "semester": 1, "grade": "5", "form": "экзамен"}])


def test_rename_moves_grades_to_new_key(client):
    """Фамилия сменилась → оценка и итоговая доступны под НОВЫМ ключом."""
    admin = make_admin(client)
    _seed_student_with_grades(client, admin)

    r = client.put("/web/admin/students/ivanova",
                   json={"surname": "Петрова"}, headers=admin)
    assert r.status_code == 200, r.text

    ch = client.get("/sync/pull", headers=admin).json()["changes"]
    live = {g["id"]: g for g in ch["grades"] if not g.get("deleted")}
    assert "Петрова|Мария|L1" in live, "оценка должна переехать на новый ключ"
    assert live["Петрова|Мария|L1"]["grade"] == "5"

    live_t = {t["id"]: t for t in ch["term_grades"] if not t.get("deleted")}
    assert "Петрова|Мария|Математика|2025/2026|1" in live_t, "итоговая тоже переезжает"


def test_old_key_becomes_tombstone(client):
    """Старый ключ получает надгробие — удаление доедет на другие ПК, дублей не будет."""
    admin = make_admin(client)
    _seed_student_with_grades(client, admin)
    client.put("/web/admin/students/ivanova", json={"surname": "Петрова"}, headers=admin)

    ch = client.get("/sync/pull", headers=admin).json()["changes"]
    old = [g for g in ch["grades"] if g["id"] == "Иванова|Мария|L1"]
    assert old and old[0]["deleted"] is True, "старая оценка должна стать надгробием"


def test_rename_without_name_change_is_noop(client):
    """Правка без смены ФИО (например, только группа) историю не трогает."""
    admin = make_admin(client)
    _seed_student_with_grades(client, admin)
    client.put("/web/admin/students/ivanova", json={"group": "ИС-22"}, headers=admin)

    ch = client.get("/sync/pull", headers=admin).json()["changes"]
    live = [g for g in ch["grades"] if not g.get("deleted")]
    assert [g["id"] for g in live] == ["Иванова|Мария|L1"], "ключ не должен меняться"
