"""
test_subject_rename.py — PUT /web/admin/subjects/{name} (3.5.5).

Имя предмета лежит ПРОСТОЙ СТРОКОЙ в нескольких таблицах (внешнего ключа на
Subject.id нигде нет) — переименование обязано докатиться до ВСЕХ них, иначе каталог
показал бы новое имя, а журнал/расписание/нагрузка препода — старое, будто это два
разных предмета. SubjectHours — особый случай: имя предмета сидит ЕЩЁ И в id самой
строки (hrs:{группа}|{предмет}|{год}|{семестр}), поэтому там перенос на новый id,
а не обновление колонки.
"""
from conftest import make_admin, make_teacher, assign_teacher


def test_rename_updates_catalog(client):
    admin = make_admin(client)
    client.post("/web/admin/subjects", json={"name": "Математика"}, headers=admin)
    r = client.put("/web/admin/subjects/Математика", json={"name": "Высшая математика"},
                   headers=admin)
    assert r.status_code == 200, r.text
    names = {s["name"] for s in client.get("/web/admin/subjects", headers=admin).json()["subjects"]}
    assert "Высшая математика" in names and "Математика" not in names


def test_rename_updates_group_subjects_list(client):
    admin = make_admin(client)
    client.post("/web/admin/subjects", json={"name": "Физика"}, headers=admin)
    client.post("/web/admin/groups", json={"name": "ИС-21", "subjects": ["Физика", "Химия"]},
               headers=admin)
    r = client.put("/web/admin/subjects/Физика", json={"name": "Прикладная физика"}, headers=admin)
    assert r.status_code == 200, r.text
    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    g = next(x for x in groups if x["name"] == "ИС-21")
    assert set(g["subjects"]) == {"Прикладная физика", "Химия"}


def test_rename_updates_teacher_workload(client):
    admin = make_admin(client)
    client.post("/web/admin/subjects", json={"name": "Математика"}, headers=admin)
    make_teacher(client, admin, subjects=["Математика"])
    r = client.put("/web/admin/subjects/Математика", json={"name": "Алгебра"}, headers=admin)
    assert r.status_code == 200, r.text
    teachers = client.get("/web/admin/teachers", headers=admin).json()["teachers"]
    t = next(x for x in teachers if x["login"] == "teacher1")
    assert t["subjects"] == ["Алгебра"]


def test_rename_updates_lessons(client):
    admin = make_admin(client)
    client.post("/web/admin/subjects", json={"name": "Физика"}, headers=admin)
    client.post("/web/admin/groups", json={"name": "ИС-21", "subjects": ["Физика"]}, headers=admin)
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L1", "group_name": "ИС-21", "subject": "Физика", "type": "Практика", "number": 1}
    ]}}, headers=admin)
    r = client.put("/web/admin/subjects/Физика", json={"name": "Прикладная физика"}, headers=admin)
    assert r.status_code == 200, r.text
    r2 = client.get("/sync/pull", headers=admin)
    lesson = next(l for l in r2.json()["changes"]["lessons"] if l["id"] == "L1")
    assert lesson["subject"] == "Прикладная физика"


def test_rename_migrates_subject_hours_to_new_id(client):
    """SubjectHours.id САМ включает имя предмета — переименование обязано перенести
    часы/ЗЕТ/назначение препода на НОВЫЙ id, а не просто перезаписать колонку subject
    (иначе id продолжал бы врать про предмет с уже неверным именем)."""
    admin = make_admin(client)
    client.post("/web/admin/subjects", json={"name": "Физика"}, headers=admin)
    client.post("/web/admin/groups", json={"name": "ИС-21", "subjects": ["Физика"]}, headers=admin)
    make_teacher(client, admin, subjects=["Физика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Физика")
    client.post("/web/admin/group-hours", json={
        "group": "ИС-21", "hours": {"Физика": 72}, "zet": {"Физика": 2.0}}, headers=admin)

    r = client.put("/web/admin/subjects/Физика", json={"name": "Прикладная физика"}, headers=admin)
    assert r.status_code == 200, r.text

    hr = client.get("/web/admin/group-hours", params={"group": "ИС-21"}, headers=admin).json()
    row = next(s for s in hr["subjects"] if s["subject"] == "Прикладная физика")
    assert row["hours_total"] == 72 and row["zet"] == 2.0
    assert row["teacher_id"] == "teach:teacher1"
    assert not any(s["subject"] == "Физика" for s in hr["subjects"])


def test_rename_requires_admin(client):
    admin = make_admin(client)
    client.post("/web/admin/subjects", json={"name": "Физика"}, headers=admin)
    th = make_teacher(client, admin)
    r = client.put("/web/admin/subjects/Физика", json={"name": "Х"}, headers=th)
    assert r.status_code == 403


def test_rename_missing_subject_is_404(client):
    admin = make_admin(client)
    r = client.put("/web/admin/subjects/Несуществующий", json={"name": "Х"}, headers=admin)
    assert r.status_code == 404


def test_rename_to_existing_name_is_409(client):
    admin = make_admin(client)
    client.post("/web/admin/subjects", json={"name": "Физика"}, headers=admin)
    client.post("/web/admin/subjects", json={"name": "Химия"}, headers=admin)
    r = client.put("/web/admin/subjects/Физика", json={"name": "Химия"}, headers=admin)
    assert r.status_code == 409


def test_rename_to_empty_name_is_400(client):
    admin = make_admin(client)
    client.post("/web/admin/subjects", json={"name": "Физика"}, headers=admin)
    r = client.put("/web/admin/subjects/Физика", json={"name": "  "}, headers=admin)
    assert r.status_code == 400


def test_rename_to_same_name_is_a_no_op(client):
    admin = make_admin(client)
    client.post("/web/admin/subjects", json={"name": "Физика"}, headers=admin)
    r = client.put("/web/admin/subjects/Физика", json={"name": "Физика"}, headers=admin)
    assert r.status_code == 200
    names = {s["name"] for s in client.get("/web/admin/subjects", headers=admin).json()["subjects"]}
    assert names == {"Физика"}
