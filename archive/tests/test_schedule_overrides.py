"""Архив 15.10.2026: тесты выведенного sync/sync_engine.py (продукт его не зовёт с
25.09.2026, см. tests/test_legacy_sync_engine_fenced.py). Перенесены ДОСЛОВНО из
tests/test_schedule_overrides.py; не исполняются. Инварианты живого пути держат
desktop/local_mirror, desktop/desk_outbox и server/tests/test_sync*.py."""

def test_collect_includes_tombstones_for_sync():
    """collect_local отдаёт и надгробия — иначе удаление правки не доедет на другой ПК."""
    ov.set_override("К74/1", 1, "Пнд", 2, subject="Математика")
    ov.delete_override(ov.override_id("К74/1", 1, "Пнд", 2))
    collected = se._collect_schedule_overrides()
    assert any(c["id"] == "sovr:К74/1|1|Пнд|2" and c["deleted"] for c in collected)


def test_merge_from_server_applies_lww():
    """Серверная правка применяется (LWW), локальная более свежая — не затирается."""
    se._merge_schedule_overrides([{
        "id": "sovr:К74/1|2|Втр|1", "group_name": "К74/1", "week": 2, "day": "Втр",
        "pair_no": 1, "action": "set", "subject": "Физика",
        "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False}])
    rows = ov.list_overrides("К74/1")
    assert len(rows) == 1 and rows[0]["subject"] == "Физика"

    #старая серверная правка НЕ перетирает свежую локальную
    se._merge_schedule_overrides([{
        "id": "sovr:К74/1|2|Втр|1", "group_name": "К74/1", "week": 2, "day": "Втр",
        "pair_no": 1, "action": "set", "subject": "СТАРОЕ",
        "updated_at": "2000-01-01T00:00:00+00:00", "deleted": False}])
    assert ov.list_overrides("К74/1")[0]["subject"] == "Физика"


