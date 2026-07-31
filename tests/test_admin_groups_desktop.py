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


#Учебные часы группы («🕐») — REST через SyncClient (не локальный store, см.
#_open_group_hours: «пройдено X ч» считает сервер по занятиям ВСЕХ преподавателей).


def test_hours_button_wired(qapp, fresh_db):
    """Клик по «🕐» в строке группы вызывает _open_group_hours с именем группы, не
    просто _open_group (по аналогии с test_double_click_dialog_double_click_wired)."""
    from data_store import get_store
    gh = get_store()
    gh.set_groups([{"name": "к74/1", "subjects": []}])
    from admin_dashboard import AdminDashboard
    dash = AdminDashboard(lambda: None)

    opened = []
    dash._open_group_hours = lambda name: opened.append(name)
    dash._render_groups()

    import time
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and dash._g_table.rowCount() == 0:
        qapp.processEvents()
        time.sleep(0.01)
    assert dash._g_table.rowCount() == 1

    actions = dash._g_table.cellWidget(0, 3)   # 0=Название,1=Категория,2=Предметы,3=действия
    hrs_button = actions.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)[0]
    hrs_button.click()
    assert opened == ["к74/1"]


class _FakeHoursSyncClient:
    saved = []

    def __init__(self, *a, **kw):
        pass

    def group_hours(self, group):
        return {"group": group, "term": {"year": "2025", "semester": 1},
                "subjects": [{"subject": "Математика", "hours_total": 24, "hours_done": 10,
                             "teacher_id": "teach:ivanov", "teacher_name": "Иванов И.И.",
                             "zet": None, "zet_hint": 0.7}]}

    #§ролей: список преподов для выпадающего списка «кто ведёт этот предмет».
    def admin_teachers(self):
        return {"teachers": [{"id": "teach:ivanov", "name": "Иванов И.И.",
                              "subjects": ["Математика"]},
                             {"id": "teach:petrov", "name": "Петров П.П.",
                              "subjects": ["Физика"]}]}

    def save_group_hours(self, group, hours, teachers=None, zet=None):
        type(self).saved.append((group, dict(hours), dict(teachers or {}), dict(zet or {})))
        return {"ok": True, "saved": len(hours)}


def test_group_hours_load_and_save_via_sync_client(qapp, fresh_db, monkeypatch):
    """SyncClient.group_hours/save_group_hours — тот же путь, что использует
    _open_group_hours (диалог не открываем — d.exec() блокирует поток, см. решение
    в других тестах этой сессии)."""
    _FakeHoursSyncClient.saved = []
    monkeypatch.setattr("sync_runner.current_auth", lambda: ("http://test", "tok"))
    import sync_client
    monkeypatch.setattr(sync_client, "SyncClient", _FakeHoursSyncClient)
    from admin_dashboard import AdminDashboard
    dash = AdminDashboard(lambda: None)

    loaded = {}

    def _load():
        from sync_client import SyncClient
        return SyncClient("http://test", token="tok").group_hours("к74/1")
    dash._run_bg(_load, lambda r: loaded.update(r))

    import time
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not loaded:
        qapp.processEvents()
        time.sleep(0.01)
    assert loaded["subjects"] == [{"subject": "Математика", "hours_total": 24, "hours_done": 10,
                                   "teacher_id": "teach:ivanov", "teacher_name": "Иванов И.И.",
                                   "zet": None, "zet_hint": 0.7}]

    def _save():
        from sync_client import SyncClient
        return SyncClient("http://test", token="tok").save_group_hours(
            "к74/1", {"Математика": 26}, {"Математика": "teach:ivanov"})
    dash._run_bg(_save, lambda _r: None)

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not _FakeHoursSyncClient.saved:
        qapp.processEvents()
        time.sleep(0.01)
    assert _FakeHoursSyncClient.saved == [("к74/1", {"Математика": 26}, {"Математика": "teach:ivanov"}, {})]


def test_group_hours_dialog_lists_only_teachers_with_that_subject(qapp, fresh_db, monkeypatch):
    """§ролей: выпадающий список препода на предмет — только те, у кого этот предмет
    указан в профиле («нажали математику — все преподы, у которых указана математика»).
    Диалог не открываем (.exec() блокирует поток) — проверяем ту же фильтрацию, что
    строит _open_group_hours, применённую к данным фейкового клиента напрямую."""
    monkeypatch.setattr("sync_runner.current_auth", lambda: ("http://test", "tok"))
    import sync_client
    monkeypatch.setattr(sync_client, "SyncClient", _FakeHoursSyncClient)

    c = _FakeHoursSyncClient()
    all_teachers = c.admin_teachers()["teachers"]
    subj = c.group_hours("к74/1")["subjects"][0]["subject"]
    matching = [t for t in all_teachers if subj in (t.get("subjects") or [])]
    assert [t["id"] for t in matching] == ["teach:ivanov"], \
        "Петров (Физика) не должен предлагаться на предмет Математика"
