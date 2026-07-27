"""
test_admin_curator_desktop.py — режим куратора в АДМИН-редакторе преподавателя (десктоп).

Разведка показала: сама роль куратора (потребление — вкладка «Курирование» у
преподавателя, /отчет для родителей и т.п.) уже полностью работает и покрыта
tests/test_curator_desktop.py. Единственный пробел был в admin_dashboard.py — там
нечем было НАЗНАЧИТЬ куратора: не было ни чекбокса, ни списка групп. Эти тесты
проверяют именно новые куски (_group_picker/_get_checked и бейдж в списке), не
трогая модальные диалоги (._open_teacher/._add_teacher используют QDialog.exec(),
который блокирует поток — в этом файле такие диалоги не тестируются, как и нигде
в проекте, см. отсутствие подобных тестов для остальных диалогов admin_dashboard.py).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pump_until(qapp, predicate, timeout_ms=3000):
    """_run_bg крутит фоновый QThread — ждём, пока его done/finished дойдёт до
    главного потока, а не проверяем состояние сразу же после вызова."""
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_group_picker_lists_available_groups(qapp, fresh_db):
    from admin_dashboard import _group_picker
    lw = _group_picker(None, [])
    names = {lw.item(i).text() for i in range(lw.count())}
    #DEFAULT_GROUPS — фолбэк из styles.py, когда локально групп ещё не заводили.
    assert "к74/1" in names


def test_group_picker_preselects_curated_groups(qapp, fresh_db):
    from admin_dashboard import _group_picker
    lw = _group_picker(None, ["к74/1", "к75/0"])
    checked = {lw.item(i).text() for i in range(lw.count())
              if lw.item(i).checkState() == Qt.Checked}
    assert checked == {"к74/1", "к75/0"}


def test_get_checked_reads_back_exactly_the_ticked_items(qapp, fresh_db):
    from admin_dashboard import _group_picker, _get_checked
    lw = _group_picker(None, ["к74/1"])
    assert _get_checked(lw) == ["к74/1"]
    #Отмечаем ещё одну группу вручную — как сделал бы клик пользователя.
    for i in range(lw.count()):
        if lw.item(i).text() == "к74/2":
            lw.item(i).setCheckState(Qt.Checked)
    assert set(_get_checked(lw)) == {"к74/1", "к74/2"}


def test_teachers_list_shows_curator_badge(qapp, fresh_db):
    """§12: список преподавателей помечает куратора — данные видны сразу, без
    открытия диалога редактирования."""
    from data_store import get_store
    gh = get_store()
    gh.set_teachers({
        "Иванов Иван Иванович": {"login": "ivanov", "subjects": [], "curated_groups": ["к74/1"]},
        "Петров Пётр Петрович": {"login": "petrov", "subjects": []},
    })
    from admin_dashboard import AdminDashboard
    dash = AdminDashboard(lambda: None)
    dash._render_teachers()
    assert _pump_until(qapp, lambda: dash._t_list.count() >= 2), "список не наполнился вовремя"
    lines = {dash._t_list.item(i).text() for i in range(dash._t_list.count())}
    assert any("Иванов" in l and "куратор" in l for l in lines)
    assert any("Петров" in l and "куратор" not in l for l in lines)
