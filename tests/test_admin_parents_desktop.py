"""
test_admin_parents_desktop.py — вкладка «Родители» в АДМИН-дашборде (десктоп).

Разведка показала: сама роль родителя (кабинет parent_dashboard.py, согласие
студента, ограничения в мессенджере) уже полностью реализована на сервере/вебе/
десктопе. Единственный пробел — в admin_dashboard.py не было НИКАКОГО способа
завести аккаунт родителя, привязать его к студенту или отредактировать/удалить
запись, не открывая браузер. ParentLink — онлайн-only (не в SYNC_MODELS), поэтому
вкладка ходит через SyncClient напрямую; здесь SyncClient подменяется, как в
test_notifications_desktop.py (без похода на реальный сервер).

Модальные диалоги (._open_parent/._add_parent и т.п.) здесь НЕ открываются через
.exec() (см. решение в предыдущих заходах — это блокирует поток); вместо этого
проверяется то же, что видел бы диалог: данные в _parents_list (Qt.UserRole) и
фактические вызовы SyncClient через _run_bg напрямую.
"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pump_until(qapp, predicate, timeout_ms=3000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class _FakeSyncClient:
    """Двойник SyncClient — только методы, которые трогает вкладка «Родители»."""
    parents = [{"id": "par:1", "login": "roditel1", "full_name": "Сидорова Анна Петровна"}]
    links = [{"id": "plink:1", "status": "pending",
             "student": {"id": "stud:1", "full_name": "Иванов Иван", "group": "к74/1"},
             "parent": {"id": "par:1", "full_name": "Сидорова Анна Петровна", "login": "roditel1"}}]
    created_links = []
    revoked = []
    updated = []
    deleted = []

    def __init__(self, *a, **kw):
        pass

    def list_parents(self):
        return {"parents": self.parents}

    def list_parent_links(self, group=""):
        return {"links": self.links}

    def create_parent(self, surname, name, login, password):
        return {"ok": True, "id": "par:new", "login": login}

    def create_parent_link(self, parent_id, student_id):
        type(self).created_links.append((parent_id, student_id))
        return {"ok": True, "id": "plink:new", "status": "pending"}

    def revoke_parent_link(self, link_id):
        type(self).revoked.append(link_id)
        return {"ok": True}

    def update_parent(self, parent_id, surname="", name="", password=""):
        type(self).updated.append((parent_id, surname, name, bool(password)))
        return {"ok": True, "id": parent_id}

    def delete_parent(self, parent_id):
        type(self).deleted.append(parent_id)
        return {"ok": True, "id": parent_id}


@pytest.fixture()
def dash(qapp, fresh_db, monkeypatch):
    monkeypatch.setattr("sync_runner.current_auth", lambda: ("http://test", "tok"))
    import sync_client
    monkeypatch.setattr(sync_client, "SyncClient", _FakeSyncClient)
    _FakeSyncClient.created_links = []
    _FakeSyncClient.revoked = []
    _FakeSyncClient.updated = []
    _FakeSyncClient.deleted = []
    from admin_dashboard import AdminDashboard
    return AdminDashboard(lambda: None)


def test_parents_tab_lists_accounts_and_links(qapp, dash):
    dash._reload_parents()
    assert _pump_until(qapp, lambda: dash._parents_list.count() and dash._links_box.count())
    assert "Сидорова" in dash._parents_list.item(0).text()
    #Qt.UserRole на строке родителя несёт весь словарь — на нём построен двойной клик.
    stored = dash._parents_list.item(0).data(Qt.UserRole)
    assert stored["id"] == "par:1"
    #Строка привязки — card (QFrame), текст лежит в дочернем QLabel.
    link_row = dash._links_box.itemAt(0).widget()
    labels = link_row.findChildren(QLabel)
    assert any("Иванов" in l.text() for l in labels)
    assert any("Сидорова" in l.text() for l in labels)


def test_revoke_button_calls_sync_client(qapp, dash, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.Yes))
    dash._revoke_parent_link("plink:1")
    assert _pump_until(qapp, lambda: len(_FakeSyncClient.revoked) == 1)
    assert _FakeSyncClient.revoked == ["plink:1"]


def test_create_parent_calls_sync_client(qapp, dash):
    dash._reload_parents()
    assert _pump_until(qapp, lambda: dash._parents_list.count())

    def _do():
        return _FakeSyncClient().create_parent("Петрова", "Ольга", "petrova", "pass1234")
    result = {}
    dash._run_bg(_do, lambda r: result.update(r))
    assert _pump_until(qapp, lambda: result.get("ok"))
    assert result["login"] == "petrova"


def test_create_parent_link_calls_sync_client(qapp, dash):
    from data_store import get_store
    gh = get_store()
    gh.set_students([{"surname": "Иванов", "name": "Иван", "group": "к74/1",
                      "login": "ivanov", "password_hash": "x"}])
    sid = gh.get_students()[0]["id"]

    def _do():
        return _FakeSyncClient().create_parent_link("par:1", sid)
    dash._run_bg(_do, lambda _r: None)
    assert _pump_until(qapp, lambda: len(_FakeSyncClient.created_links) == 1)
    assert _FakeSyncClient.created_links == [("par:1", sid)]


def test_update_parent_calls_sync_client(qapp, dash):
    """§12: двойной клик → правка ФИО/пароля уходит через update_parent (не generic push —
    родитель online-only, см. sync/sync_client.py)."""
    def _do():
        return _FakeSyncClient().update_parent("par:1", surname="Петрова", name="Ольга",
                                                password="newpass1")
    dash._run_bg(_do, lambda _r: None)
    assert _pump_until(qapp, lambda: _FakeSyncClient.updated)
    assert _FakeSyncClient.updated == [("par:1", "Петрова", "Ольга", True)]


def test_delete_parent_calls_sync_client(qapp, dash):
    def _do():
        return _FakeSyncClient().delete_parent("par:1")
    dash._run_bg(_do, lambda _r: None)
    assert _pump_until(qapp, lambda: _FakeSyncClient.deleted)
    assert _FakeSyncClient.deleted == ["par:1"]


