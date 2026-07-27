"""
test_admin_groups_desktop.py — двойной клик по группе в админке: просмотр/правка
прикреплённых предметов (по аналогии с преподавателями/студентами/родителями).

Диалог (._open_group) собирается через QDialog.exec() — в тестах его не открываем
(см. решение в других файлах этой сессии); вместо этого проверяем то, что диалог
реально показал бы (локальные данные группы) и сам путь сохранения (store.set_groups),
которым пользуется _open_group._save() — идентично _add_group/_del_group.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_group_carries_subjects_locally(qapp, fresh_db):
    """Локальный словарь группы уже несёт subjects — на этом построен просмотр по
    двойному клику, без похода на сервер."""
    from data_store import get_store
    gh = get_store()
    gh.set_groups([{"name": "к74/1", "subjects": ["Математика", "Физика"]}])
    groups = gh.get_groups()
    assert groups[0]["subjects"] == ["Математика", "Физика"]


def test_group_picker_prechecks_existing_subjects(qapp, fresh_db):
    """_open_group использует тот же _subject_picker, что _add_group — проверяем его
    поведение с непустым набором предметов группы (сам _subject_picker уже
    протестирован для куратора; здесь — что группа реально его переиспользует)."""
    from data_store import get_store
    from subjects import save_subjects
    save_subjects(["Математика", "Физика", "История"])
    gh = get_store()
    gh.set_groups([{"name": "к74/1", "subjects": ["Физика"]}])

    from admin_dashboard import _subject_picker, _get_checked
    from PySide6.QtCore import Qt
    g = gh.get_groups()[0]
    lw = _subject_picker(None, g.get("subjects", []))
    checked = {lw.item(i).text() for i in range(lw.count())
              if lw.item(i).checkState() == Qt.Checked}
    assert checked == {"Физика"}
    assert _get_checked(lw) == ["Физика"]


def test_double_click_dialog_double_click_wired(qapp, fresh_db):
    """itemDoubleClicked действительно подключён и извлекает имя группы из колонки 0."""
    from data_store import get_store
    gh = get_store()
    gh.set_groups([{"name": "к74/1", "subjects": []}])
    from admin_dashboard import AdminDashboard
    dash = AdminDashboard(lambda: None)
    dash._render_groups()

    import time
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and dash._g_table.rowCount() == 0:
        qapp.processEvents()
        time.sleep(0.01)
    assert dash._g_table.rowCount() == 1

    opened = []
    dash._open_group = lambda name: opened.append(name)
    dash._g_table.itemDoubleClicked.emit(dash._g_table.item(0, 0))
    assert opened == ["к74/1"]


def test_save_subjects_via_set_groups(qapp, fresh_db):
    """_open_group._save() — тот же локальный путь, что _add_group/_del_group."""
    from data_store import get_store
    gh = get_store()
    gh.set_groups([{"name": "к74/1", "subjects": ["Математика"]}])

    gs = gh.get_groups()
    for x in gs:
        if x["name"] == "к74/1":
            x["subjects"] = ["Физика", "История"]
    gh.set_groups(gs)

    assert gh.get_groups()[0]["subjects"] == ["Физика", "История"]
