"""
test_schedule_editor_desktop.py — десктоп-редактор расписания 2.0.

Проверяем не Qt-жест (его гоняем в браузере/руками), а ЛОГИКУ, на которую он опирается:
  • перенос пары = скрыть старую ячейку + задать новую с временем ПОД НОМЕР слота;
  • правки копятся в черновике (has_unsaved), «Сохранить» пишет их в overrides;
  • «Отмена» черновик очищает, ничего не записав;
  • сброс группы снимает сохранённые правки.

Портал в тестах недоступен → база строится из правок (сценарий «колледж без портала»).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from schedule import overrides as sched_ov  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def editor(qapp, fresh_db):
    from schedule_editor import ScheduleEditor
    ed = ScheduleEditor()
    # Группа + одна пара на 1-й паре Пнд (через overrides — портала в тестах нет).
    sched_ov.set_override("ИС-21", 1, "Пнд", 1, action="set", subject="Математика",
                          time="09:00-10:35", room="101", teacher="Иванов И.И.")
    ed.group.blockSignals(True)
    ed.group.clear(); ed.group.addItem("ИС-21"); ed.group.setCurrentText("ИС-21")
    ed.group.blockSignals(False)
    ed._reload()
    return ed


def test_move_hides_source_and_sets_target_with_slot_time(editor):
    editor._on_pair_moved("Пнд", 1, "Пнд", 3)
    assert editor.has_unsaved()
    # старая ячейка скрыта
    assert editor._cell("Пнд", 1) is None
    # новая — с предметом и ВРЕМЕНЕМ 3-й пары
    moved = editor._cell("Пнд", 3)
    assert moved and moved["subject"] == "Математика"
    assert moved["time"] == "13:00-14:35", "время должно подстроиться под номер слота"


def test_move_onto_occupied_slot_is_blocked(editor):
    sched_ov.set_override("ИС-21", 1, "Втр", 2, action="set", subject="Физика")
    editor._reload()
    editor._on_pair_moved("Пнд", 1, "Втр", 2)   # Втр/2 занята
    assert not editor.has_unsaved(), "занятый слот не должен принимать перенос"


def test_save_writes_overrides_and_clears_draft(editor):
    editor._on_pair_moved("Пнд", 1, "Пнд", 3)
    editor._save()
    assert not editor.has_unsaved(), "после сохранения черновик пуст"
    keys = {(o["day"], int(o["pair_no"]), o["action"])
            for o in sched_ov.list_overrides("ИС-21") if int(o["week"]) == 1}
    assert ("Пнд", 3, "set") in keys       # новая пара сохранена
    # исходная ячейка сохранена скрытой (remove) — на портале её нет, значит пусто
    sch = editor._cell("Пнд", 1)
    assert sch is None


def test_discard_clears_draft_without_writing(editor, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    editor._on_pair_moved("Пнд", 1, "Чтв", 4)
    assert editor.has_unsaved()
    editor._discard()
    assert not editor.has_unsaved()
    # ничего не записалось: на Чтв/4 правки нет
    assert not any(o["day"] == "Чтв" and int(o["pair_no"]) == 4
                   for o in sched_ov.list_overrides("ИС-21"))


def test_reset_group_removes_saved_overrides(editor, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    editor._reset_group()
    live = [o for o in sched_ov.list_overrides("ИС-21") if not o.get("deleted")]
    assert live == [], "после сброса живых правок группы быть не должно"
