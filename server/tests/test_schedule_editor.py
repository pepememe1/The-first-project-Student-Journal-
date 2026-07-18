"""
test_schedule_editor.py — админ-редактор расписания (правки ПОВЕРХ портала, overlay).

В тестах портал недоступен (нет сети) → базовое расписание пустое, и правки строятся с
нуля — это и есть сценарий «колледж без портала»: админ вручную наполняет расписание.
"""
from conftest import make_admin, make_teacher


def _set(client, admin, **kw):
    return client.post("/web/admin/schedule/override", json=kw, headers=admin)


def test_admin_set_pair_appears_in_schedule(client):
    admin = make_admin(client)
    r = _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=2,
             subject="Математика", time="10:45-12:20", room="101")
    assert r.status_code == 200 and r.json()["ok"]

    sch = client.get("/web/schedule", params={"group": "ИС-21"}, headers=admin).json()
    assert sch["available"]
    pairs = sch["schedule"]["weeks"]["1"]["Пнд"]
    assert any(p["pair_no"] == 2 and p["subject"] == "Математика" for p in pairs)


def test_override_replaces_same_cell(client):
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=2, subject="Математика")
    _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=2, subject="Физика")
    adm = client.get("/web/admin/schedule", params={"group": "ИС-21"}, headers=admin).json()
    #та же ячейка → одна правка, последнее значение
    cell = [o for o in adm["overrides"] if o["day"] == "Пнд" and o["pair_no"] == 2]
    assert len(cell) == 1 and cell[0]["subject"] == "Физика"


def test_remove_action_hides_and_delete_reverts(client):
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=2, day="Втр", pair_no=1, subject="Химия")
    # action=remove скрывает пару (в этой ячейке пусто)
    _set(client, admin, group="ИС-21", week=2, day="Втр", pair_no=1, action="remove")
    sch = client.get("/web/schedule", params={"group": "ИС-21"}, headers=admin).json()
    pairs = (sch["schedule"]["weeks"].get("2", {}).get("Втр", []))
    assert not any(p["pair_no"] == 1 for p in pairs)

    # удалить правку — ячейка возвращается к порталу (в тесте портал пуст → пары нет вовсе)
    ov_id = client.get("/web/admin/schedule", params={"group": "ИС-21"},
                       headers=admin).json()["overrides"][0]["id"]
    assert client.delete(f"/web/admin/schedule/override/{ov_id}", headers=admin).json()["ok"]


def test_only_admin_can_edit(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    r = _set(client, th, group="ИС-21", week=1, day="Пнд", pair_no=1, subject="Х")
    assert r.status_code == 403


def test_validation_rejects_bad_input(client):
    admin = make_admin(client)
    assert _set(client, admin, group="", week=1, day="Пнд", pair_no=1).status_code == 400
    assert _set(client, admin, group="ИС-21", week=5, day="Пнд", pair_no=1).status_code == 400
    assert _set(client, admin, group="ИС-21", week=1, day="Хрд", pair_no=1).status_code == 400
