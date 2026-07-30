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


# ── §ролей: предмет из списка группы, преподаватель автоматом, без поля «время» ────────
def test_pair_dialog_has_no_separate_time_field():
    """Раньше «Время» было отдельным QLineEdit, который МОГ разойтись с номером пары
    (перезаписывался при смене слота, но пользователь мог вписать что угодно вручную).
    Теперь поля нет вовсе — time() всегда равен _time_for(номер_пары)."""
    from schedule_editor import _PairDialog
    dlg = _PairDialog(day="Пнд", slot=1, subjects=["Математика"],
                      subject_teacher={}, pair_times=["09:00-10:35", "10:45-12:20"])
    assert not hasattr(dlg, "time"), "отдельного поля времени быть не должно"
    v = dlg.value()
    assert v["time"] == "09:00-10:35"
    dlg.slot.setCurrentIndex(1)   # 2-я пара
    assert dlg.value()["time"] == "10:45-12:20", "время всегда следует за номером пары"


def test_pair_dialog_subject_is_dropdown_from_group_subjects():
    """Предмет — выпадающий список РОВНО предметов группы, не свободный текст."""
    from schedule_editor import _PairDialog
    dlg = _PairDialog(day="Пнд", slot=1, subjects=["Математика", "Физика"],
                      subject_teacher={}, pair_times=["09:00-10:35"])
    items = [dlg.subject.itemText(i) for i in range(dlg.subject.count())]
    assert items == ["Математика", "Физика"]
    assert dlg.value()["subject"] == "Математика"   # первый пункт по умолчанию


def test_pair_dialog_teacher_auto_fills_from_subject_and_updates_on_change():
    """Преподаватель подставляется автоматом по выбранному предмету — не вводится руками."""
    from schedule_editor import _PairDialog
    dlg = _PairDialog(day="Пнд", slot=1, subjects=["Математика", "Физика"],
                      subject_teacher={"Математика": "Иванов И.И.", "Физика": "Петров П.П."},
                      pair_times=["09:00-10:35"])
    assert dlg.value()["teacher"] == "Иванов И.И."
    dlg.subject.setCurrentText("Физика")
    assert dlg.value()["teacher"] == "Петров П.П."


def test_pair_dialog_no_assignment_leaves_teacher_empty():
    from schedule_editor import _PairDialog
    dlg = _PairDialog(day="Пнд", slot=1, subjects=["Математика"], subject_teacher={},
                      pair_times=["09:00-10:35"])
    assert dlg.value()["teacher"] == ""
    assert dlg.teacher_lbl.text() == "— не назначен —"


def test_subject_teacher_map_reads_local_assignment(editor):
    """ScheduleEditor._subject_teacher_map — читает локально-синкнутую subject_hours
    (teacher_id) + локальных преподавателей (имя по id), как это уже делает teacher_
    dashboard.get_teacher_assignments (обратная сторона того же источника). Термин —
    ТЕКУЩИЙ (terms.current_term()), как и у самого метода, который его не параметризует."""
    import terms
    import sync_engine as se
    from data_store import get_store
    year, sem = terms.current_term()
    get_store().set_teachers({"Иванов Иван Иванович": {
        "id": "teach:ivanov", "login": "ivanov", "subjects": ["Математика"],
    }}, stamp=False, wake=False)
    se.apply_remote({"subject_hours": [
        {"id": f"hrs:ИС-21|Математика|{year}|{sem}", "group_name": "ИС-21",
         "subject": "Математика", "year": year, "semester": sem, "hours_total": 0,
         "teacher_id": "teach:ivanov",
         "updated_at": "2026-07-26T10:00:00+00:00", "deleted": False}]})
    editor._group_subjects["ИС-21"] = ["Математика"]

    m = editor._subject_teacher_map("ИС-21")
    assert m == {"Математика": "Иванов Иван Иванович"}
