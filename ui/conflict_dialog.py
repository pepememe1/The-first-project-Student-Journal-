"""
conflict_dialog.py — окно разрешения конфликтов синхронизации оценок.

Когда два ПК поставили РАЗНЫЕ оценки в одну ячейку и время правок неотличимо,
система не затирает молча, а заносит расхождение в sync_conflicts. Здесь
преподаватель видит каждое расхождение и выбирает, какое значение оставить.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QWidget, QFrame, QMessageBox
)
from PySide6.QtCore import Qt

try:
    from styles import C
except Exception:
    C = {"card": "#fff", "card2": "#f3f6f7", "border": "#dfe6e8",
         "text": "#0d2b30", "text3": "#3a565b", "green": "#147c8b", "blue": "#1f6f8b"}


class ConflictDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Конфликты синхронизации оценок")
        self.setMinimumSize(560, 420)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        head = QLabel("Эти оценки разошлись между компьютерами. Выберите, "
                      "какое значение считать верным — оно уйдёт на сервер.")
        head.setWordWrap(True)
        head.setStyleSheet(f"color:{C['text3']};font-size:12px;")
        lay.addWidget(head)

        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("border:none;")
        self._inner = QWidget()
        self._vbox = QVBoxLayout(self._inner)
        self._vbox.setSpacing(8)
        self._scroll.setWidget(self._inner)
        lay.addWidget(self._scroll, 1)

        close = QPushButton("Закрыть"); close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(close)
        lay.addLayout(row)

        self._reload()

    def _reload(self):
        #очистить
        while self._vbox.count():
            it = self._vbox.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        from core import DBManager
        conflicts = DBManager.list_conflicts(unresolved_only=True)
        if not conflicts:
            ok = QLabel("✓ Конфликтов нет — все оценки синхронизированы.")
            ok.setStyleSheet(f"color:{C['green']};font-size:14px;")
            self._vbox.addWidget(ok)
            self._vbox.addStretch(1)
            return
        for c in conflicts:
            self._vbox.addWidget(self._card(c))
        self._vbox.addStretch(1)

    def _card(self, c: dict) -> QFrame:
        fr = QFrame()
        fr.setStyleSheet(f"QFrame{{background:{C['card2']};border:1px solid "
                         f"{C['border']};border-radius:10px;}}")
        v = QVBoxLayout(fr); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(6)
        who = QLabel(f"<b>{c['student_f']} {c['student_n']}</b> — занятие {c['lesson_id'][:8]}…")
        who.setStyleSheet(f"color:{C['text']};font-size:13px;")
        v.addWidget(who)

        row = QHBoxLayout(); row.setSpacing(8)
        local_b = QPushButton(f"Этот ПК:  {c['local_grade'] or '—'}")
        remote_b = QPushButton(f"Сервер ({c['remote_device'] or '?'}):  {c['remote_grade'] or '—'}")
        for b in (local_b, remote_b):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:{C['card']};border:1px solid "
                            f"{C['border']};border-radius:8px;padding:6px 10px;"
                            f"color:{C['text']};}}QPushButton:hover{{"
                            f"border-color:{C['green']};color:{C['green']};}}")
        local_b.clicked.connect(lambda _=False, cid=c["id"], g=c["local_grade"]: self._resolve(cid, g))
        remote_b.clicked.connect(lambda _=False, cid=c["id"], g=c["remote_grade"]: self._resolve(cid, g))
        row.addWidget(local_b); row.addWidget(remote_b)
        v.addLayout(row)
        return fr

    def _resolve(self, conflict_id: int, grade: str):
        from core import DBManager
        if DBManager.resolve_conflict(conflict_id, grade):
            self._reload()
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось применить значение.")
