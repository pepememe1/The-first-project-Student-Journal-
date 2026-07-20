"""
test_curator_desktop.py — режим куратора на ДЕСКТОПЕ.

Куратор — преподаватель, которому админ назначил группы (users.curated_groups). Он видит
успеваемость этих групп по ВСЕМ предметам, включая чужие, но СТРОГО только на чтение:
журнал ведёт преподаватель предмета.

Что здесь защищается:
  • вкладка не появляется у обычного преподавателя (нет назначенных групп);
  • таблица куратора НЕредактируема — иначе он правил бы чужие оценки мимо проверки
    прав (инвариант §6);
  • средний балл считается через grading.py, а не своей формулой (инвариант §8);
  • список групп берётся из локальных данных, то есть работает офлайн (инвариант §1).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   #тесты без реального экрана

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtWidgets import QApplication, QAbstractItemView  # noqa: E402

from core import Student  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_dashboard(curated):
    """TeacherDashboard с заданными курируемыми группами."""
    from teacher_dashboard import TeacherDashboard
    data = {"subjects": ["Математика"], "group_assignments": {"Математика": "ИС-21"},
            "curated_groups": list(curated)}
    return TeacherDashboard("Петров Пётр Петрович", data)


def _seed_group(group="ИС-21", subject="Математика"):
    """Занятие + студент с оценкой в локальной базе.

    ⚠️ У Student порядок полей (n, f, group) — имя ПЕРВЫМ, фамилия второй."""
    from core import GradeBook
    book = GradeBook(group, subject)
    lesson = book.add_lesson("Практика", topic="Тема", date="01.09.2025")
    st = Student(n="Мария", f="Иванова", group=group)
    st.records[lesson.id] = "5"
    book.add_student(st)
    book.save_to_db()
    return book


def test_tab_hidden_for_ordinary_teacher(qapp, fresh_db):
    """Нет назначенных групп — нет и вкладки: кураторство выдаёт только админ."""
    dash = _make_dashboard([])
    assert "curator" not in dash.pages


def test_tab_appears_for_curator(qapp, fresh_db):
    dash = _make_dashboard(["ИС-21"])
    assert "curator" in dash.pages
    assert dash._curated_groups() == ["ИС-21"]


def test_curator_table_is_read_only(qapp, fresh_db):
    """Ключевая гарантия: куратор смотрит, но не правит. Редактируемая таблица дала бы
    ему запись в чужой журнал в обход проверки прав."""
    dash = _make_dashboard(["ИС-21"])
    assert dash._cur_table.editTriggers() == QAbstractItemView.NoEditTriggers


def test_curator_sees_grades_of_curated_group(qapp, fresh_db):
    """Оценки курируемой группы видны, средний балл посчитан."""
    _seed_group()
    dash = _make_dashboard(["ИС-21"])
    dash._cur_group_combo.setCurrentText("ИС-21")
    dash._on_curator_group()

    table = dash._cur_table
    assert table.rowCount() == 1, "студент курируемой группы должен быть в таблице"
    assert table.item(0, 0).text() == "Иванова"
    row_text = " ".join(table.item(0, c).text()
                        for c in range(table.columnCount()) if table.item(0, c))
    assert "5" in row_text, "оценка должна отображаться"


def test_average_matches_grading_module(qapp, fresh_db):
    """Средний балл обязан совпасть с grading.py — единым расчётом для десктопа,
    сервера и сайта. Своя формула здесь означала бы разные цифры на разных экранах."""
    import grading
    book = _seed_group()
    dash = _make_dashboard(["ИС-21"])
    dash._cur_group_combo.setCurrentText("ИС-21")
    dash._on_curator_group()

    expected = grading.practice_average(
        grading.pairs_from_objects(book.lessons), book.spisok_stud[0].records, {})
    shown = dash._cur_table.item(0, dash._cur_table.columnCount() - 1).text()
    assert shown == f"{expected:.2f}"


def test_uncurated_group_is_not_offered(qapp, fresh_db):
    """В выборе — только курируемые группы. Чужие группы куратору не показываем."""
    _seed_group(group="ИС-99")
    dash = _make_dashboard(["ИС-21"])
    offered = [dash._cur_group_combo.itemText(i)
               for i in range(dash._cur_group_combo.count())]
    assert offered == ["ИС-21"]
