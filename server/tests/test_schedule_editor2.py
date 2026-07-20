"""
test_schedule_editor2.py — редактор расписания 2.0: пачечное сохранение черновика,
сброс правок, форс-обновление портала, накладки одного слота при переносе.

Портал в тестах недоступен → расписание строится из правок (сценарий «колледж без
портала»). Полный снимок портала подменяем, чтобы slot-conflicts не ходил в сеть.
"""
import pytest

from conftest import make_admin, make_teacher


@pytest.fixture(autouse=True)
def no_portal(monkeypatch):
    from app import schedule_web
    monkeypatch.setattr(schedule_web, "full_state", lambda: (None, False))


def _set(client, admin, **kw):
    r = client.post("/web/admin/schedule/override", json=kw, headers=admin)
    assert r.status_code == 200, r.text


def _overrides(client, admin, group):
    return client.get("/web/admin/schedule", params={"group": group},
                      headers=admin).json()["overrides"]


# ── Пачечное сохранение черновика ─────────────────────────────────────────────────

def test_batch_applies_all_overrides(client):
    admin = make_admin(client)
    r = client.post("/web/admin/schedule/overrides", json={"overrides": [
        {"group": "ИС-21", "week": 1, "day": "Пнд", "pair_no": 1, "action": "set",
         "subject": "Математика", "time": "09:00-10:35", "room": "101"},
        {"group": "ИС-21", "week": 1, "day": "Втр", "pair_no": 2, "action": "set",
         "subject": "Физика", "time": "10:45-12:20", "room": "202"},
    ]}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2
    assert len(_overrides(client, admin, "ИС-21")) == 2


def test_batch_is_atomic_on_bad_item(client):
    """Одна невалидная правка откатывает всю пачку: половинчатого расписания не бывает."""
    admin = make_admin(client)
    r = client.post("/web/admin/schedule/overrides", json={"overrides": [
        {"group": "ИС-21", "week": 1, "day": "Пнд", "pair_no": 1, "action": "set",
         "subject": "Математика"},
        {"group": "ИС-21", "week": 5, "day": "Пнд", "pair_no": 1, "action": "set",
         "subject": "Плохая неделя"},          #week=5 — невалидно
    ]}, headers=admin)
    assert r.status_code == 400
    assert _overrides(client, admin, "ИС-21") == [], "первая правка не должна сохраниться"


def test_batch_move_is_remove_plus_set(client):
    """Перенос пары = скрыть старую ячейку + задать новую (как делает drag-drop)."""
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=1,
         subject="Математика", time="09:00-10:35", room="101")
    #Черновик переноса на 3-ю пару: время подстроено клиентом под слот.
    r = client.post("/web/admin/schedule/overrides", json={"overrides": [
        {"group": "ИС-21", "week": 1, "day": "Пнд", "pair_no": 1, "action": "remove"},
        {"group": "ИС-21", "week": 1, "day": "Пнд", "pair_no": 3, "action": "set",
         "subject": "Математика", "time": "13:00-14:35", "room": "101"},
    ]}, headers=admin)
    assert r.status_code == 200, r.text
    sch = client.get("/web/schedule", params={"group": "ИС-21"}, headers=admin).json()
    pairs = sch["schedule"]["weeks"]["1"]["Пнд"]
    nums = {p["pair_no"] for p in pairs}
    assert 3 in nums and 1 not in nums, "пара должна переехать с 1-й на 3-ю"


# ── Сброс правок ──────────────────────────────────────────────────────────────────

def test_reset_group_tombstones_overrides(client):
    """Сброс группы снимает её правки (надгробием — они синкуются), чужие не трогает."""
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=1, subject="Мат")
    _set(client, admin, group="ИС-22", week=1, day="Пнд", pair_no=1, subject="Физ")

    r = client.post("/web/admin/schedule/reset", params={"group": "ИС-21"}, headers=admin)
    assert r.status_code == 200 and r.json()["reset"] == 1
    assert _overrides(client, admin, "ИС-21") == []
    assert len(_overrides(client, admin, "ИС-22")) == 1, "чужую группу сброс не трогает"


def test_reset_all_clears_every_group(client):
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=1, subject="Мат")
    _set(client, admin, group="ИС-22", week=1, day="Втр", pair_no=2, subject="Физ")

    r = client.post("/web/admin/schedule/reset", params={"all": True}, headers=admin)
    assert r.status_code == 200 and r.json()["reset"] == 2
    assert _overrides(client, admin, "ИС-21") == []
    assert _overrides(client, admin, "ИС-22") == []


def test_reset_needs_group_or_all(client):
    admin = make_admin(client)
    assert client.post("/web/admin/schedule/reset", headers=admin).status_code == 400


def test_reset_override_is_tombstone_not_physical_delete(client):
    """Правка обязана уехать надгробием (deleted=True), иначе на десктопе воскреснет."""
    from app.models import ScheduleOverride
    from app.db import SessionLocal
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=1, subject="Мат")
    client.post("/web/admin/schedule/reset", params={"group": "ИС-21"}, headers=admin)
    db = SessionLocal()
    try:
        rows = db.query(ScheduleOverride).filter(
            ScheduleOverride.group_name == "ИС-21").all()
        assert rows and all(r.deleted for r in rows), "строка должна остаться надгробием"
    finally:
        db.close()


# ── Накладки одного слота при переносе ───────────────────────────────────────────

def test_slot_conflicts_flags_busy_room(client):
    admin = make_admin(client)
    #В целевом слоте у другой группы уже занята аудитория 305 другим занятием.
    _set(client, admin, group="ИС-22", week=1, day="Пнд", pair_no=3,
         subject="Химия", teacher="Петров П.П.", room="305")
    r = client.get("/web/admin/schedule/slot-conflicts", params={
        "group": "ИС-21", "week": 1, "day": "Пнд", "pair_no": 3,
        "room": "305", "teacher": "Иванов И.И.", "subject": "Математика"}, headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["room"] and data["room"][0]["group"] == "ИС-22"
    assert not data["teacher"], "преподаватель другой — по нему накладки нет"


def test_slot_conflicts_ignores_same_lesson(client):
    """Та же пара у двух групп в одном кабинете — общая лекция, не накладка."""
    admin = make_admin(client)
    _set(client, admin, group="ИС-22", week=1, day="Пнд", pair_no=3,
         subject="История", teacher="Сидоров С.С.", room="Зал")
    r = client.get("/web/admin/schedule/slot-conflicts", params={
        "group": "ИС-21", "week": 1, "day": "Пнд", "pair_no": 3,
        "room": "Зал", "teacher": "Сидоров С.С.", "subject": "История"}, headers=admin)
    assert r.json()["room"] == [] and r.json()["teacher"] == []


def test_editor2_endpoints_are_admin_only(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    assert client.post("/web/admin/schedule/overrides",
                       json={"overrides": [{"group": "ИС-21", "week": 1, "day": "Пнд",
                                            "pair_no": 1, "subject": "X"}]},
                       headers=th).status_code == 403
    assert client.post("/web/admin/schedule/reset", params={"group": "ИС-21"},
                       headers=th).status_code == 403
    assert client.post("/web/admin/schedule/refresh", params={"group": "ИС-21"},
                       headers=th).status_code == 403
