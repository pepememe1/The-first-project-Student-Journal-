"""
parent_links_card.py — карточка «Родители» на вкладке «Профиль» студента.

Родитель получает доступ к журналу студента только после СОГЛАСИЯ САМОГО СТУДЕНТА
(§12, ParentLink.status: pending → active/revoked) — выдать доступ за него нельзя,
поэтому заявка должна быть видна там, где студент реально её увидит: в профиле, рядом
с уведомлениями. ParentLink — онлайн-only (не в SYNC_MODELS, как и мессенджер),
поэтому здесь прямые REST-вызовы через SyncClient, а не локальный кэш.

Пусто (нет ни pending, ни active) → виджет не занимает места (setVisible(False)) —
большинству студентов родителя не привязывали, и пустая карточка была бы просто шумом.
"""
import log

from PySide6.QtCore import QThread, Signal as QSignal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from styles import C
from widgets import btn, lbl, section_lbl

_LOG = log.get("parent_links_card")


class _BgWorker(QThread):
    done = QSignal(object)
    error = QSignal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as e:
            self.error.emit(str(e))


def _client():
    """Клиент с живой сессией или None — та же логика, что в notifications_view.py
    (fresh_auth тихо продлевает access по refresh, без повторного ввода пароля)."""
    import sync_runner
    try:
        url, token = sync_runner.fresh_auth()
    except Exception:
        url, token = sync_runner.current_auth()
    if not url or not token:
        return None
    from sync_client import SyncClient
    return SyncClient(url, token=token)


class ParentLinksCard(QWidget):
    """Заявки родителей на доступ к журналу — показывается только студенту."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._title = section_lbl("Родители")
        lay.addWidget(self._title)
        self._box = QVBoxLayout()
        self._box.setSpacing(6)
        lay.addLayout(self._box)
        #Пока не знаем, есть ли вообще заявки — скрыты сразу, показываемся только если
        #действительно есть что показать (см. _apply).
        self.setVisible(False)
        self.reload()

    def reload(self):
        c = _client()
        if c is None:
            return
        w = _BgWorker(c.my_parent_links)
        w.done.connect(self._apply)
        w.error.connect(lambda e: _LOG.warning(f"[parent-links] не загрузились: {e}"))
        self._workers.append(w)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        w.start()

    def _clear(self):
        while self._box.count():
            it = self._box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _apply(self, data):
        links = (data or {}).get("links", [])
        pending = [l for l in links if l.get("status") == "pending"]
        active = [l for l in links if l.get("status") == "active"]
        self._clear()
        if not pending and not active:
            self.setVisible(False)
            return
        self.setVisible(True)
        for link in pending:
            self._box.addWidget(self._pending_row(link))
        for link in active:
            self._box.addWidget(self._active_row(link))

    def _pending_row(self, link: dict) -> QFrame:
        parent = link.get("parent", {}) or {}
        who = parent.get("full_name") or parent.get("login") or "Родитель"
        f = QFrame(); f.setObjectName("card")
        h = QHBoxLayout(f); h.setContentsMargins(14, 10, 14, 10); h.setSpacing(10)
        text = lbl(f"👤 {who} просит доступ к вашему журналу", 12, C['text'])
        text.setWordWrap(True)
        h.addWidget(text, 1)
        ok = btn("Подтвердить", "green")
        ok.clicked.connect(lambda _=0, i=link.get("id", ""): self._decide(i, True))
        h.addWidget(ok)
        no = btn("Отклонить", "red")
        no.clicked.connect(lambda _=0, i=link.get("id", ""): self._decide(i, False))
        h.addWidget(no)
        return f

    def _active_row(self, link: dict) -> QFrame:
        parent = link.get("parent", {}) or {}
        who = parent.get("full_name") or parent.get("login") or "Родитель"
        f = QFrame(); f.setObjectName("card")
        h = QHBoxLayout(f); h.setContentsMargins(14, 10, 14, 10); h.setSpacing(10)
        text = lbl(f"✅ {who} — доступ к журналу выдан", 12, C['text3'])
        text.setWordWrap(True)
        h.addWidget(text, 1)
        revoke = btn("Отозвать доступ", "red")
        revoke.clicked.connect(lambda _=0, i=link.get("id", ""): self._decide(i, False))
        h.addWidget(revoke)
        return f

    def _decide(self, link_id: str, approve: bool):
        if not link_id:
            return
        c = _client()
        if c is None:
            QMessageBox.warning(self, "Родители", "Нет связи с сервером.")
            return

        def _do():
            return c.decide_parent_link(link_id, approve)

        w = _BgWorker(_do)
        w.done.connect(lambda _r: self.reload())
        w.error.connect(lambda e: QMessageBox.warning(self, "Родители", f"Не удалось сохранить решение: {e}"))
        self._workers.append(w)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        w.start()
