"""
test_subject_hours_desktop.py — ДЕСКТОП: учебные часы «пройдено X из Y».

Часы задаёт админ на сайте, но показывать их обязан и нативный журнал на ПК — именно там
преподаватель ведёт занятия, и именно там журнал должен работать офлайн. Поэтому
subject_hours входит в SYNC_MODELS и приезжает обычным pull'ом.

Отдельно закреплено ПРАВИЛО ПОДСЧЁТА: лекция хранится ДВУМЯ строками (по академическому
часу), практика — одной, поэтому считать строки нельзя.
"""
import pytest

import study_hours
import sync_engine as se
from core import GradeBook


@pytest.fixture(autouse=True)
def _clean(fresh_db):
    yield


def test_lecture_and_practice_give_equal_hours():
    """Одна лекция и одна практика — это две пары, то есть 4 часа, а не 3."""
    book = GradeBook("К74/1", "Математика")
    book.add_lesson("Лекция", topic="л1")      #ляжет ДВУМЯ строками: hour=1 и hour=2
    book.add_lesson("Практика", topic="п1")    #одной строкой
    assert study_hours.hours_done(book.lessons) == 4


def test_homework_gives_no_hours():
    book = GradeBook("К74/1", "Математика")
    book.add_lesson("Практика", topic="п1")
    book.add_lesson("ДЗ", topic="сделать базу")
    assert study_hours.hours_done(book.lessons) == 2


def test_plan_arrives_by_sync_and_shows_in_journal():
    """План приходит с сервера pull'ом → журнал показывает «пройдено 2 из 72 ч»."""
    book = GradeBook("К74/1", "Математика")
    book.add_lesson("Практика", topic="п1")
    assert book.hours_progress() == (2, 0), "без плана — ноль, а не выдуманное число"

    se.apply_remote({"subject_hours": [
        {"id": "hrs:К74/1|Математика||0", "group_name": "К74/1", "subject": "Математика",
         "year": "", "semester": 0, "hours_total": 72,
         "updated_at": "2026-07-26T10:00:00+00:00", "deleted": False}]})

    book = GradeBook("К74/1", "Математика")
    assert book.hours_progress() == (2, 72)
    assert study_hours.format_progress(2, 72) == "Пройдено 2 из 72 ч"


def test_unset_plan_renders_nothing():
    """План не задан — интерфейс не показывает НИЧЕГО (а не «0 из 0»)."""
    assert study_hours.format_progress(4, 0) == ""


def test_hours_roundtrip_through_collect():
    """Приехавшая строка попадает и в collect_local — иначе она застряла бы на одном ПК."""
    se.apply_remote({"subject_hours": [
        {"id": "hrs:К74/1|Физика||0", "group_name": "К74/1", "subject": "Физика",
         "year": "", "semester": 0, "hours_total": 36,
         "updated_at": "2026-07-26T10:00:00+00:00", "deleted": False}]})
    collected = se._collect_subject_hours()
    assert any(c["id"] == "hrs:К74/1|Физика||0" and c["hours_total"] == 36
               for c in collected), collected


def test_older_remote_row_does_not_override_newer_local():
    """LWW: устаревшая серверная версия не затирает более свежую локальную."""
    fresh = {"id": "hrs:К74/1|Физика||0", "group_name": "К74/1", "subject": "Физика",
             "year": "", "semester": 0, "hours_total": 72,
             "updated_at": "2026-07-26T12:00:00+00:00", "deleted": False}
    se.apply_remote({"subject_hours": [fresh]})
    stale = dict(fresh, hours_total=10, updated_at="2026-07-26T09:00:00+00:00")
    se.apply_remote({"subject_hours": [stale]})

    book = GradeBook("К74/1", "Физика")
    assert book.hours_progress()[1] == 72
