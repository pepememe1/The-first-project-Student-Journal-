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
from sync import sync_engine as se
from data.core import GradeBook


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


def test_plan_arriving_by_sync_becomes_visible_to_offline_journal():
    """План, ПРИЕХАВШИЙ СИНКОМ, сразу виден офлайн-журналу — источник подписи «Пройдено X из Y ч».

    Часы синкуются (`subject_hours` в SYNC_MODELS), но пока плана нет, знаменателя нет
    тоже — интерфейс обязан не рисовать подпись вовсе, а не показывать «0 из 0».
    Проверяем сам источник цифр (`hours_progress`), а не экран: подпись рисует SPA,
    и она одна на все платформы (§11 «один интерфейс»).
    """
    book = GradeBook("К74/1", "Математика")
    book.add_lesson("Лекция", topic="л1")        #пара = 2 ч (две строки, один зачёт)
    assert book.hours_progress() == (2, 0), "плана нет — знаменателя быть не должно"

    se.apply_remote({"subject_hours": [
        {"id": "hrs:К74/1|Математика||0", "group_name": "К74/1", "subject": "Математика",
         "year": "", "semester": 0, "hours_total": 67,
         "updated_at": "2026-07-28T10:00:00+00:00", "deleted": False}]})

    book = GradeBook("К74/1", "Математика")
    assert book.hours_progress() == (2, 67)


def test_plan_saved_with_term_is_found_by_termless_journal():
    """План, сохранённый АДМИНОМ С САЙТА, виден журналу, открытому без периода.

    Веб пишет часы ключом с учебным периодом (`hrs:Группа|Предмет|2025/2026|1`), а
    экраны студента открывают журнал без периода и искали `hrs:Группа|Предмет||0` —
    ключи не совпадали, и часы на ПК не появлялись вовсе."""
    from data import terms
    year, sem = terms.current_term()

    book = GradeBook("К74/1", "История")
    book.add_lesson("Практика", topic="п1")

    se.apply_remote({"subject_hours": [
        {"id": f"hrs:К74/1|История|{year}|{sem}", "group_name": "К74/1",
         "subject": "История", "year": year, "semester": sem, "hours_total": 40,
         "updated_at": "2026-07-28T10:00:00+00:00", "deleted": False}]})

    book = GradeBook("К74/1", "История")          #как открывает журнал студент — без периода
    assert book.hours_progress() == (2, 40)


def test_archive_term_does_not_borrow_current_plan():
    """Журнал ПРОШЛОГО семестра не подставляет план текущего — это была бы чужая цифра."""
    from data import terms
    year, sem = terms.current_term()
    se.apply_remote({"subject_hours": [
        {"id": f"hrs:К74/1|Химия|{year}|{sem}", "group_name": "К74/1", "subject": "Химия",
         "year": year, "semester": sem, "hours_total": 60,
         "updated_at": "2026-07-28T10:00:00+00:00", "deleted": False}]})

    old = GradeBook("К74/1", "Химия", "2019/2020", 2)
    assert old.hours_progress()[1] == 0


# ── ЗЕТ (docs/PLAN-ZET.md) — desktop offline (SubjectHours.zet синкуется, порог нет) ──
def test_get_group_zet_reads_synced_column():
    """data.data_store.get_group_zet — только предметы с явно заданным (не NULL) ЗЕТ."""
    from data import terms
    from data.data_store import get_store
    year, sem = terms.current_term()
    se.apply_remote({"subject_hours": [
        {"id": f"hrs:К74/1|Математика|{year}|{sem}", "group_name": "К74/1",
         "subject": "Математика", "year": year, "semester": sem, "hours_total": 72,
         "zet": 2.0, "updated_at": "2026-07-29T10:00:00+00:00", "deleted": False},
        {"id": f"hrs:К74/1|Физика|{year}|{sem}", "group_name": "К74/1",
         "subject": "Физика", "year": year, "semester": sem, "hours_total": 36,
         "updated_at": "2026-07-29T10:00:00+00:00", "deleted": False}]})   # zet не задан

    zets = get_store().get_group_zet("К74/1")
    assert zets == {"Математика": 2.0}, "Физика без ЗЕТ не должна попадать в словарь"


def test_subject_zet_earned_offline_uses_exam_result():
    """Офлайн-расчёт ЗЕТ (тот же study_hours, что и на сервере) — сдал экзамен → ЗЕТ."""
    book = GradeBook("К74/1", "Математика")
    lesson = book.add_lesson("Экзамен", topic="итог")
    records = {lesson.id: "4 (Зачтено)"}
    earned = study_hours.subject_zet_earned(book.lessons, records, 2.0, scale="5")
    assert earned == 2.0

    records_failed = {lesson.id: "2 (Не зачтено)"}
    assert study_hours.subject_zet_earned(book.lessons, records_failed, 2.0, scale="5") is None


def test_subject_without_exam_is_pending_until_boundary_then_settled():
    """ВАРИАНТ C (баг Влада): предмет без экзамена НЕ засчитывается по первой же
    положительной оценке — пока семестр идёт, он «ожидается».

    Обратный ход прямо на чистой функции: одна «4» по практике — раньше это давало
    средний 4.0 >= 3.0 и весь предмет мгновенно «сдан». Теперь до рубежа это "pending"
    (ЗЕТ не начисляются), а итог подводится, когда рубеж пройден."""
    book = GradeBook("К74/1", "Математика")
    p1 = book.add_lesson("Практика", topic="п1")
    records = {p1.id: "4"}

    # Семестр идёт (term_over=False) — «ожидается», ЗЕТ НЕ засчитаны.
    assert study_hours.subject_zet_state(book.lessons, records, 2.0, term_over=False, scale="5") == "pending"
    assert study_hours.subject_zet_earned(book.lessons, records, 2.0, scale="5", term_over=False) is None

    # Рубеж пройден (term_over=True) — тот же средний 4.0 подводит итог: сдан.
    assert study_hours.subject_zet_state(book.lessons, records, 2.0, term_over=True, scale="5") == "passed"
    assert study_hours.subject_zet_earned(book.lessons, records, 2.0, scale="5", term_over=True) == 2.0

    # После рубежа, но средний ниже 3.0 — уже не «ожидается», а честно «не сдан».
    assert study_hours.subject_zet_state(book.lessons, {p1.id: "2"}, 2.0, term_over=True, scale="5") == "failed"


def test_subject_with_exam_but_no_mark_is_pending_not_failed():
    """Экзамен в плане есть, но оценки ещё нет — он ВПЕРЕДИ, а не провален: "pending",
    а не "failed" (иначе студент до самого экзамена видел бы «не сдан»)."""
    book = GradeBook("К74/1", "Математика")
    book.add_lesson("Экзамен", topic="итог")
    # term_over не важен: экзамен — сам себе рубеж.
    assert study_hours.subject_zet_state(book.lessons, {}, 2.0, term_over=False, scale="5") == "pending"
    assert study_hours.subject_zet_state(book.lessons, {}, 2.0, term_over=True, scale="5") == "pending"
