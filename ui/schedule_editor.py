"""
schedule_editor.py — ДЕСКТОП-редактор расписания (overlay поверх портала), аналог
веб-страницы AdminSchedule.vue. Админ правит расписание группы: добавить/изменить/скрыть
пару. Правки хранятся локально (schedule_overrides) и СИНХРОНИЗИРУЮТСЯ на сервер — общие
с вебом, работают офлайн. Порядок правки — тот же, что на сайте.
"""
import log
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QDialog,
    QFormLayout, QSpinBox, QMessageBox, QHeaderView, QAbstractItemView,
)

from styles import C
from widgets import lbl, title_lbl, btn, combo, field_input
from schedule.model import WEEKDAYS
from schedule import store as sched_store
from schedule import overrides as sched_ov


class _PairDialog(QDialog):
    """Диалог добавления/правки пары (день, № пары, предмет, время, аудитория, препод)."""

    def __init__(self, parent=None, *, day="Пнд", pair_no=1, subject="", time="",
                 room="", teacher=""):
        super().__init__(parent)
        self.setWindowTitle("Пара")
        self.setModal(True)
        self.setMinimumWidth(360)
        form = QFormLayout(self)
        self.day = combo(WEEKDAYS)
        self.day.setCurrentText(day if day in WEEKDAYS else "Пнд")
        self.pair = QSpinBox()
        self.pair.setRange(1, 8)
        self.pair.setValue(int(pair_no or 1))
        self.subject = field_input("Предмет");  self.subject.setText(subject)
        self.time = field_input("10:45-12:20");  self.time.setText(time)
        self.room = field_input("Аудитория");    self.room.setText(room)
        self.teacher = field_input("Преподаватель (необязательно)"); self.teacher.setText(teacher)
        form.addRow("День", self.day)
        form.addRow("№ пары", self.pair)
        form.addRow("Предмет", self.subject)
        form.addRow("Время", self.time)
        form.addRow("Аудитория", self.room)
        form.addRow("Преподаватель", self.teacher)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = btn("Отмена", "ghost")
        cancel.clicked.connect(self.reject)
        ok = btn("Сохранить", "green")
        ok.clicked.connect(self._accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)

    def _accept(self):
        if not self.subject.text().strip():
            QMessageBox.warning(self, "Пара", "Укажите предмет.")
            return
        self.accept()

    def value(self) -> dict:
        return {"day": self.day.currentText(), "pair_no": self.pair.value(),
                "subject": self.subject.text().strip(), "time": self.time.text().strip(),
                "room": self.room.text().strip(), "teacher": self.teacher.text().strip()}


class ScheduleEditor(QWidget):
    """Редактор расписания в админ-вкладке «Расписание». Выбор группы, неделя I/II, таблица
    пар с пометкой «правка»; кнопки Добавить / Изменить / Скрыть-Убрать выбранную."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.week = 1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        hdr = QHBoxLayout()
        hdr.addWidget(title_lbl("Расписание — редактор"), 1)
        lay.addLayout(hdr)
        lay.addWidget(lbl("Правки накладываются поверх портала ВСГУТУ и синхронизируются — "
                          "их видят студенты, Вектор и веб-версия.", 11, C['text3'], wrap=True))

        bar = QHBoxLayout()
        self.group = combo([])
        self.group.setMinimumWidth(160)
        self.group.currentTextChanged.connect(self._reload)
        bar.addWidget(lbl("Группа", 12, C['text3']))
        bar.addWidget(self.group)
        self.w1 = btn("I неделя", "green")
        self.w2 = btn("II неделя", "ghost")
        self.w1.clicked.connect(lambda: self._set_week(1))
        self.w2.clicked.connect(lambda: self._set_week(2))
        bar.addWidget(self.w1)
        bar.addWidget(self.w2)
        bar.addStretch(1)
        add_b = btn("+ Добавить пару", "green")
        add_b.clicked.connect(self._add)
        bar.addWidget(add_b)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["День", "№", "Время", "Предмет", "Ауд.", ""])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.doubleClicked.connect(lambda *_: self._edit())
        lay.addWidget(self.table, 1)

        act = QHBoxLayout()
        act.addStretch(1)
        edit_b = btn("Изменить", "ghost")
        edit_b.clicked.connect(self._edit)
        hide_b = btn("Скрыть / убрать", "ghost")
        hide_b.clicked.connect(self._hide_or_revert)
        act.addWidget(edit_b)
        act.addWidget(hide_b)
        lay.addLayout(act)

        self._rows = []           #параллельно строкам таблицы: dict пары
        self._load_groups()

    # ── данные ──
    def _load_groups(self):
        names = []
        try:
            from data_store import get_store
            st = get_store()
            names = sorted({g.get("name") for g in (st.get_groups() if st else []) if g.get("name")})
        except Exception as e:
            log.get("schedule_editor").warning(f"[editor] группы: {e}")
        if not names:
            #фолбэк — группы из снимка расписания
            try:
                snap = sched_store.load_cached()
                names = sorted(snap.group_names()) if snap else []
            except Exception:
                names = []
        self.group.blockSignals(True)
        self.group.clear()
        self.group.addItems(names)
        self.group.blockSignals(False)
        if names:
            self._reload()

    def _set_week(self, w):
        self.week = w
        self.w1.setProperty("variant", None)
        self.w1.setStyleSheet(self.w1.styleSheet())
        from styles import BTN
        self.w1.setStyleSheet(BTN.get("green" if w == 1 else "ghost", ""))
        self.w2.setStyleSheet(BTN.get("green" if w == 2 else "ghost", ""))
        self._reload()

    def _cur_group(self) -> str:
        return self.group.currentText().strip()

    def _reload(self, *_):
        group = self._cur_group()
        self.table.setRowCount(0)
        self._rows = []
        if not group:
            return
        gs = None
        try:
            gs = sched_store.group_schedule(group)   #портал + правки
        except Exception as e:
            log.get("schedule_editor").warning(f"[editor] расписание: {e}")
        edited = set()
        try:
            for o in sched_ov.list_overrides(group):
                if int(o["week"]) == self.week:
                    edited.add((o["day"], int(o["pair_no"])))
        except Exception:
            pass
        pairs = []
        if gs:
            for day in WEEKDAYS:
                for ls in gs.weeks.get(self.week, {}).get(day, []):
                    pairs.append({"day": day, "pair_no": getattr(ls, "pair_no", 0),
                                  "time": getattr(ls, "time", ""),
                                  "subject": getattr(ls, "subject", "") or getattr(ls, "raw", ""),
                                  "room": getattr(ls, "room", ""),
                                  "teacher": getattr(ls, "teacher", ""),
                                  "edited": (day, getattr(ls, "pair_no", 0)) in edited})
        pairs.sort(key=lambda p: (WEEKDAYS.index(p["day"]) if p["day"] in WEEKDAYS else 9,
                                  p["pair_no"]))
        self._rows = pairs
        self.table.setRowCount(len(pairs))
        for i, p in enumerate(pairs):
            subj = p["subject"] + ("  • правка" if p["edited"] else "")
            for col, val in enumerate([p["day"], str(p["pair_no"]), p["time"], subj, p["room"]]):
                it = QTableWidgetItem(val)
                if p["edited"]:
                    it.setForeground(Qt.GlobalColor.darkCyan)
                self.table.setItem(i, col, it)

    def _selected(self):
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    # ── действия ──
    def _add(self):
        group = self._cur_group()
        if not group:
            return
        dlg = _PairDialog(self)
        if dlg.exec() == QDialog.Accepted:
            v = dlg.value()
            sched_ov.set_override(group, self.week, v["day"], v["pair_no"], action="set",
                                  subject=v["subject"], time=v["time"], room=v["room"],
                                  teacher=v["teacher"])
            self._reload()

    def _edit(self):
        p = self._selected()
        group = self._cur_group()
        if not p or not group:
            return
        dlg = _PairDialog(self, day=p["day"], pair_no=p["pair_no"], subject=p["subject"],
                          time=p["time"], room=p["room"], teacher=p.get("teacher", ""))
        if dlg.exec() == QDialog.Accepted:
            v = dlg.value()
            #если сменили день/№ — старую ячейку скрываем, новую задаём
            if (v["day"], v["pair_no"]) != (p["day"], p["pair_no"]):
                sched_ov.set_override(group, self.week, p["day"], p["pair_no"], action="remove")
            sched_ov.set_override(group, self.week, v["day"], v["pair_no"], action="set",
                                  subject=v["subject"], time=v["time"], room=v["room"],
                                  teacher=v["teacher"])
            self._reload()

    def _hide_or_revert(self):
        p = self._selected()
        group = self._cur_group()
        if not p or not group:
            return
        oid = sched_ov.override_id(group, self.week, p["day"], p["pair_no"])
        if p["edited"]:
            #это уже правка — убираем её (ячейка вернётся к порталу)
            if QMessageBox.question(self, "Убрать правку",
                    "Убрать правку и вернуть как на портале?") == QMessageBox.Yes:
                sched_ov.delete_override(oid)
                self._reload()
        else:
            #портальная пара — скрываем (создаём правку remove)
            if QMessageBox.question(self, "Скрыть пару",
                    f"Скрыть пару «{p['subject']}» ({p['day']}, {p['pair_no']})?") == QMessageBox.Yes:
                sched_ov.set_override(group, self.week, p["day"], p["pair_no"], action="remove")
                self._reload()
