"""
test_teacher_journal_absences.py — счётчик пропущенных часов в журнале преподавателя.

§12: когда преподаватель ставит «Н» (лекция) или «Н» на практике, это должно сразу
считаться в столбце «Пропусков (ч)» рядом со «Средним» — той же логикой, что и
Вектор/сервер (vector.intents._count_absences, webdata.absences): строка лекции
с Н/Б/О — 1 час, у практики считается только «Н» (ДЗ не входит).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import GradeBook, Student  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _book():
    """Журнал ТЕКУЩЕГО термина — `_reload_journal` дашборда запрашивает именно его
    (в отличие от режима куратора, который читает все периоды без фильтра), поэтому
    записи без термина (год="", семестр=0) дашборд молча не нашёл бы."""
    import terms
    year, sem = terms.current_term()
    return GradeBook("к74/1", "Математика", year, sem)


def _make_dashboard():
    """§ролей: группа теперь берётся из ЯВНОГО назначения (subject_hours.teacher_id),
    не из мёртвого group_assignments — заводим синкнутую строку с этим преподом. Термин
    ДОЛЖЕН совпасть с _book() (terms.current_term()) — иначе назначение не найдётся."""
    import terms
    import sync_engine as se
    year, sem = terms.current_term()
    teacher_id = "teach:petrov"
    se.apply_remote({"subject_hours": [
        {"id": f"hrs:к74/1|Математика|{year}|{sem}", "group_name": "к74/1",
         "subject": "Математика", "year": year, "semester": sem, "hours_total": 0,
         "teacher_id": teacher_id,
         "updated_at": "2026-07-26T10:00:00+00:00", "deleted": False}]})
    from teacher_dashboard import TeacherDashboard
    data = {"id": teacher_id, "subjects": ["Математика"]}
    return TeacherDashboard("Петров Пётр Петрович", data)


def _abs_col(table):
    """Столбец «Пропусков (ч)» — последний (правее «Среднего»)."""
    return table.columnCount() - 1


def test_absences_column_header(qapp, fresh_db):
    dash = _make_dashboard()
    table = dash.t_table
    header = table.horizontalHeaderItem(_abs_col(table))
    assert header is not None and header.text() == "Пропусков (ч)"


def test_lecture_absence_counts_one_hour(qapp, fresh_db):
    book = _book()
    lesson = book.add_lesson("Лекция", topic="Тема", date="01.09.2025")
    st = Student(n="Мария", f="Иванова", group="к74/1")
    st.records[lesson.id] = "Н"
    book.add_student(st)
    book.save_to_db()

    dash = _make_dashboard()
    table = dash.t_table
    assert table.item(0, _abs_col(table)).text() == "1"


def test_practice_absence_counts_only_n(qapp, fresh_db):
    """У практики пропуском считается ТОЛЬКО «Н» — оценка «2» пропуском не является."""
    book = _book()
    l1 = book.add_lesson("Практика", topic="Тема 1", date="01.09.2025")
    l2 = book.add_lesson("Практика", topic="Тема 2", date="02.09.2025")
    st = Student(n="Мария", f="Иванова", group="к74/1")
    st.records[l1.id] = "Н"
    st.records[l2.id] = "2"
    book.add_student(st)
    book.save_to_db()

    dash = _make_dashboard()
    table = dash.t_table
    assert table.item(0, _abs_col(table)).text() == "1"


def test_no_absences_shows_dash(qapp, fresh_db):
    book = _book()
    lesson = book.add_lesson("Лекция", topic="Тема", date="01.09.2025")
    st = Student(n="Мария", f="Иванова", group="к74/1")
    st.records[lesson.id] = "✓"
    book.add_student(st)
    book.save_to_db()

    dash = _make_dashboard()
    table = dash.t_table
    assert table.item(0, _abs_col(table)).text() == "—"


def test_homework_n_is_not_counted_as_absence(qapp, fresh_db):
    """«Н» на ДЗ значит «не сдал», а не «не был» — не должно попадать в пропуски."""
    book = _book()
    lesson = book.add_lesson("ДЗ", topic="Тема", date="01.09.2025")
    st = Student(n="Мария", f="Иванова", group="к74/1")
    st.records[lesson.id] = "Н"
    book.add_student(st)
    book.save_to_db()

    dash = _make_dashboard()
    table = dash.t_table
    assert table.item(0, _abs_col(table)).text() == "—"
