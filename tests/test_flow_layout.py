"""
test_flow_layout.py — кнопки журнала преподавателя ПЕРЕНОСЯТСЯ, а не уезжают за край.

Баг: девять кнопок и три фильтра лежали в QHBoxLayout. Он не переносит — он СЖИМАЕТ,
и в неполноэкранном окне часть кнопок оказывалась за правым краем, то есть недоступной.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   #тесты без реального экрана

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from widgets import FlowLayout  # noqa: E402

LABELS = ["+ Лекция/Практика", "+ Экзамен", "+ Студент", "Сохранить", "Аттестация",
          "Ведомость", "Журнал", "Импорт", "Конфликты"]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _build(qapp, width):
    w = QWidget()
    fl = FlowLayout(w, h_spacing=6, v_spacing=6)
    for t in LABELS:
        fl.addWidget(QPushButton(t))
    w.resize(width, 400)
    w.show()
    qapp.processEvents()
    return w, fl


def test_narrow_window_wraps_to_more_lines(qapp):
    """Узкое окно → больше строк. Это и есть суть переноса."""
    _w, fl = _build(qapp, 1600)
    assert fl.heightForWidth(500) > fl.heightForWidth(1600)


def test_nothing_overflows_the_right_edge(qapp):
    """Главное: ни одна кнопка не уезжает за правый край — иначе до неё не добраться."""
    width = 520
    _w, fl = _build(qapp, width)
    over = [fl.itemAt(i).widget().text() for i in range(fl.count())
            if fl.itemAt(i).geometry().right() > width]
    assert over == [], f"за краем оказались кнопки: {over}"


def test_all_buttons_stay_in_layout(qapp):
    """Перенос не должен терять элементы."""
    _w, fl = _build(qapp, 400)
    assert fl.count() == len(LABELS)
