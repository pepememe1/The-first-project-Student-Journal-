"""
test_schedule_overrides.py — ДЕСКТОП: правки расписания (overlay) + их синхронизация.

Редактор расписания есть и на вебе, и на десктопе; правки — ОБЩАЯ синкуемая сущность
(schedule_overrides), поэтому id ячейки детерминированный и совпадает с серверным.
"""
import pytest

from schedule import overrides as ov
from schedule.model import GroupSchedule, Lesson
import sync_engine as se


@pytest.fixture(autouse=True)
def _clean(fresh_db):
    """Каждому тесту — чистая локальная БД (фикстура проекта)."""
    yield


def test_override_id_matches_server_format():
    """id ячейки — тот же формат, что на сервере (models.schedule_override_id): ключ синка."""
    assert ov.override_id("К74/1", 1, "Пнд", 2) == "sovr:К74/1|1|Пнд|2"


def test_set_list_delete_roundtrip():
    ov.set_override("К74/1", 1, "Пнд", 2, subject="Математика", time="10:45", room="101")
    rows = ov.list_overrides("К74/1")
    assert len(rows) == 1 and rows[0]["subject"] == "Математика"

    #повторная правка ТОЙ ЖЕ ячейки заменяет прежнюю (id детерминированный)
    ov.set_override("К74/1", 1, "Пнд", 2, subject="Физика")
    rows = ov.list_overrides("К74/1")
    assert len(rows) == 1 and rows[0]["subject"] == "Физика"

    #удаление — надгробие: из активных пропадает
    ov.delete_override(ov.override_id("К74/1", 1, "Пнд", 2))
    assert ov.list_overrides("К74/1") == []


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


def test_apply_to_group_sets_and_removes_pairs():
    """Мердж поверх портального расписания: set добавляет/заменяет, remove скрывает."""
    gs = GroupSchedule(name="К74/1")
    gs.weeks = {1: {"Пнд": [Lesson(pair_no=2, subject="Портальная", time="10:45")]}}

    ov.set_override("К74/1", 1, "Пнд", 2, subject="Заменённая")
    merged = ov.apply_to_group(gs, "К74/1")
    pnd = merged.weeks[1]["Пнд"]
    assert len(pnd) == 1 and pnd[0].subject == "Заменённая"

    ov.set_override("К74/1", 1, "Пнд", 2, action="remove")
    merged2 = ov.apply_to_group(merged, "К74/1")
    assert not [x for x in merged2.weeks[1]["Пнд"] if x.pair_no == 2]


def test_apply_without_portal_builds_from_overrides():
    """Колледж без портала: расписание строится ТОЛЬКО из правок админа."""
    ov.set_override("НОВАЯ-1", 1, "Срд", 3, subject="История", time="13:00")
    gs = ov.apply_to_group(None, "НОВАЯ-1")
    assert gs.weeks[1]["Срд"][0].subject == "История"
