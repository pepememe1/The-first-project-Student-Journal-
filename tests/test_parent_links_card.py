"""
test_parent_links_card.py — карточка «Родители» в профиле студента (десктоп).

Показывается ТОЛЬКО когда есть заявки/активные привязки — большинству студентов
родителя не привязывали, и пустая карточка была бы просто шумом (§12). Согласие
на доступ к журналу может дать только сам студент (offline-first не при чём —
ParentLink online-only), поэтому решение (Подтвердить/Отклонить/Отозвать) уходит
прямым REST-вызовом через SyncClient — здесь он подменяется.
"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
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


class _FakeClient:
    links = []
    decisions = []

    def my_parent_links(self):
        return {"links": self.links}

    def decide_parent_link(self, link_id, approve):
        type(self).decisions.append((link_id, approve))
        return {"ok": True, "status": "active" if approve else "revoked"}


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeClient.links = []
    _FakeClient.decisions = []


def test_hidden_when_no_links(qapp, monkeypatch):
    import parent_links_card as m
    monkeypatch.setattr(m, "_client", lambda: _FakeClient())
    card = m.ParentLinksCard()
    #Ждём, пока фоновый воркер реально отработает (а не просто проверяем стартовое
    #состояние — оно и так setVisible(False) ДО загрузки, это не доказывало бы, что
    #reload() вообще что-то сделал).
    assert _pump_until(qapp, lambda: not card._workers)
    assert not card.isVisible()


def test_shows_pending_request_with_actions(qapp, monkeypatch):
    import parent_links_card as m
    _FakeClient.links = [{"id": "plink:1", "status": "pending",
                          "parent": {"full_name": "Сидорова Анна Петровна"}}]
    monkeypatch.setattr(m, "_client", lambda: _FakeClient())
    card = m.ParentLinksCard()
    assert _pump_until(qapp, lambda: card.isVisible())
    assert card._box.count() == 1
    row = card._box.itemAt(0).widget()
    labels = row.findChildren(QLabel)
    assert any("Сидорова" in l.text() for l in labels)


def test_confirm_calls_decide_with_approve_true(qapp, monkeypatch):
    import parent_links_card as m
    _FakeClient.links = [{"id": "plink:1", "status": "pending",
                          "parent": {"full_name": "Сидорова Анна Петровна"}}]
    monkeypatch.setattr(m, "_client", lambda: _FakeClient())
    card = m.ParentLinksCard()
    assert _pump_until(qapp, lambda: card.isVisible())
    card._decide("plink:1", True)
    assert _pump_until(qapp, lambda: _FakeClient.decisions)
    assert _FakeClient.decisions == [("plink:1", True)]


def test_active_link_shows_revoke_button(qapp, monkeypatch):
    import parent_links_card as m
    _FakeClient.links = [{"id": "plink:2", "status": "active",
                          "parent": {"full_name": "Кузнецов Олег"}}]
    monkeypatch.setattr(m, "_client", lambda: _FakeClient())
    card = m.ParentLinksCard()
    assert _pump_until(qapp, lambda: card.isVisible())
    row = card._box.itemAt(0).widget()
    labels = row.findChildren(QLabel)
    assert any("Кузнецов" in l.text() and "выдан" in l.text() for l in labels)
