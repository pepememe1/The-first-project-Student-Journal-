"""
test_terms_desktop.py — Учебные семестры на десктопе (как в вебе): штамповка периода
у занятий, фильтр журнала по семестру, «усыновление» легаси-занятий в текущий термин,
синхронизация year/semester и список периодов.
"""
import terms
from core import GradeBook, DBManager
import sync_engine

G, S = "ИС-21", "Математика"


def test_lessons_stamped_and_filtered_by_term(fresh_db):
    """Занятие штампуется периодом журнала; фильтр показывает только свой семестр."""
    cy, cs = terms.current_term()
    gb = GradeBook(G, S, cy, cs)
    lid = gb.add_lesson("Практика", "Тема", "01.09.2025").id

    assert [l.id for l in GradeBook(G, S, cy, cs).lessons] == [lid]      # свой семестр
    assert GradeBook(G, S, "1999/2000", 2).lessons == []                 # другой — пусто
    assert lid in [l.id for l in GradeBook(G, S).lessons]                # без фильтра — есть


def test_legacy_lesson_backfilled_to_current(fresh_db):
    """Занятие без периода (старые базы) «усыновляется» в текущий термин при открытии
    журнала с семестром — иначе оно не показалось бы ни в одном."""
    cy, cs = terms.current_term()
    gb = GradeBook(G, S)                          # без термина → year=""
    lid = gb.add_lesson("Практика", "Тема", "01.09.2025").id

    book = GradeBook(G, S, cy, cs)                # открыли текущий семестр
    assert [l.id for l in book.lessons] == [lid]
    assert book.lessons[0].year == cy and book.lessons[0].semester == cs


def test_lesson_term_round_trips_through_sync(fresh_db):
    """year/semester уезжают в collect и применяются из merge (данные общие с сервером)."""
    cy, cs = terms.current_term()
    lid = GradeBook(G, S, cy, cs).add_lesson("Практика", "Тема", "01.09.2025").id
    row = [x for x in sync_engine.collect_local()["lessons"] if x["id"] == lid][0]
    assert row["year"] == cy and row["semester"] == cs

    sync_engine.apply_remote({"lessons": [{
        "id": "R1", "group_name": G, "subject": S, "type": "Практика", "number": 9,
        "topic": "R", "date": "02.09.2025", "retake_date": "", "hour": 0,
        "year": "2024/2025", "semester": 2,
        "updated_at": "2099-01-01T00:00:00+00:00", "deleted": False}]})
    assert "R1" in [l.id for l in GradeBook(G, S, "2024/2025", 2).lessons]


def test_list_terms(fresh_db):
    """list_terms отдаёт периоды с занятиями, новые сверху."""
    GradeBook(G, S, "2025/2026", 1).add_lesson("Практика", "T", "01.09.2025")
    GradeBook(G, S, "2024/2025", 2).add_lesson("Практика", "T", "01.02.2025")
    assert DBManager.list_terms() == [("2025/2026", 1), ("2024/2025", 2)]
