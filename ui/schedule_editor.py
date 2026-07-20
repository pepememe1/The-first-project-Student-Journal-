"""
schedule_editor.py — ДЕСКТОП-редактор расписания 2.0 (overlay поверх портала ВСГУТУ).

Аналог веб-страницы AdminSchedule.vue, тот же набор возможностей:
  • сетка «слоты × дни», каждая ячейка — цель для переноса;
  • перенос пары ПЕРЕТАСКИВАНИЕМ (удержание ~0.5 c → тащим на другой слот/день);
  • при переносе время подстраивается под НОМЕР слота (1-я пара → 09:00, 3-я → 13:00);
  • сразу после переноса — сверка аудитории/преподавателя у ДРУГИХ групп, накладка
    подсвечивается красным;
  • правки НЕ пишутся сразу — копятся в ЧЕРНОВИКЕ, «Сохранить» применяет их пачкой;
  • уход из редактора или смена группы с несохранённым черновиком — переспрос;
  • «Взять с ВСГУТУ» (группа/все) — обновление портала; «Сброс» (группа/все) — снять
    правки и вернуться к порталу.

Правки хранятся локально (schedule_overrides) и СИНХРОНИЗИРУЮТСЯ на сервер — общие с
вебом, работают офлайн. Отметок «совместная пара» на десктопе нет (серверная деталь),
поэтому сверка гасит лишь одинаковые пары у разных групп (см. schedule/conflicts.py).
"""
import log
from PySide6.QtCore import Qt, QTimer, QThread, Signal as QSignal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QDialog,
    QFormLayout, QMessageBox, QHeaderView, QAbstractItemView, QLabel, QComboBox,
)

from styles import C, BTN
from widgets import lbl, title_lbl, btn, combo, field_input
from schedule.model import WEEKDAYS, DEFAULT_PAIR_TIMES
from schedule import store as sched_store
from schedule import overrides as sched_ov
from schedule import conflicts as sched_conf

LONG_PRESS_MS = 500       # удержание до старта перетаскивания (короткий тап = открыть форму)
MOVE_CANCEL_PX = 8        # сдвиг до срабатывания удержания = прокрутка, а не перенос


class _BgWorker(QThread):
    """Фоновая задача (сеть портала не должна морозить интерфейс)."""
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


class _PairDialog(QDialog):
    """Добавить/изменить пару. Время авто-подставляется по номеру слота, но правится."""

    def __init__(self, parent=None, *, day="Пнд", slot=1, subject="", room="", teacher="",
                 pair_times=None):
        super().__init__(parent)
        self.setWindowTitle("Пара")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._pair_times = pair_times or list(DEFAULT_PAIR_TIMES)
        form = QFormLayout(self)
        self.day = combo(WEEKDAYS)
        self.day.setCurrentText(day if day in WEEKDAYS else "Пнд")
        self.slot = QComboBox()
        for i, t in enumerate(self._pair_times, start=1):
            self.slot.addItem(f"{i} ({t})", i)
        self.slot.setCurrentIndex(max(0, int(slot) - 1))
        self.slot.currentIndexChanged.connect(self._sync_time)
        self.subject = field_input("Предмет");  self.subject.setText(subject)
        self.time = field_input("10:45-12:20")
        self.time.setText(self._time_for(slot))
        self.room = field_input("Аудитория");    self.room.setText(room)
        self.teacher = field_input("Преподаватель (необязательно)"); self.teacher.setText(teacher)
        form.addRow("День", self.day)
        form.addRow("№ пары", self.slot)
        form.addRow("Предмет", self.subject)
        form.addRow("Время", self.time)
        form.addRow("Аудитория", self.room)
        form.addRow("Преподаватель", self.teacher)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = btn("Отмена", "ghost"); cancel.clicked.connect(self.reject)
        ok = btn("В черновик", "green"); ok.clicked.connect(self._accept)
        row.addWidget(cancel); row.addWidget(ok)
        form.addRow(row)

    def _time_for(self, slot):
        idx = int(slot) - 1
        return self._pair_times[idx] if 0 <= idx < len(self._pair_times) else ""

    def _sync_time(self):
        #При смене слота подставляем его время (если пользователь его не менял вручную —
        #перезаписываем всегда, это ожидаемое поведение «время под номер пары»).
        self.time.setText(self._time_for(self.slot.currentData()))

    def _accept(self):
        if not self.subject.text().strip():
            QMessageBox.warning(self, "Пара", "Укажите предмет.")
            return
        self.accept()

    def value(self) -> dict:
        return {"day": self.day.currentText(), "slot": int(self.slot.currentData()),
                "subject": self.subject.text().strip(), "time": self.time.text().strip(),
                "room": self.room.text().strip(), "teacher": self.teacher.text().strip()}


class _Grid(QTableWidget):
    """Сетка слотов×дней с переносом пары удержанием (long-press). Сигналы наверх:
    pairMoved(fromDay, fromSlot, toDay, toSlot) и cellActivated(day, slot) — короткий тап."""
    pairMoved = QSignal(str, int, str, int)
    cellActivated = QSignal(str, int)

    def __init__(self, days, parent=None):
        super().__init__(parent)
        self.DAYS = days
        self.setColumnCount(len(days))
        self.setHorizontalHeaderLabels(days)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setDefaultSectionSize(64)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setShowGrid(True)
        self._press = None
        self._dragging = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._begin_drag)
        self._ghost = QLabel(self.viewport())
        self._ghost.setStyleSheet(
            f"background:{C['card']}; color:{C['text']}; border:1px solid {C['green']};"
            "border-radius:6px; padding:3px 6px; font-weight:600;")
        self._ghost.hide()

    def _day_slot(self, row, col):
        if 0 <= col < len(self.DAYS) and row >= 0:
            return self.DAYS[col], row + 1
        return None, None

    def mousePressEvent(self, e):
        self._press = None
        if e.button() == Qt.LeftButton:
            idx = self.indexAt(e.position().toPoint())
            if idx.isValid():
                self._press = {"row": idx.row(), "col": idx.column(),
                               "pos": e.position().toPoint(), "moved": False}
                self._timer.start(LONG_PRESS_MS)
        #super() не зовём: выделение/редактирование нам не нужны, а колесо-скролл работает.

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._dragging:
            self._ghost.move(pos.x() + 12, pos.y() + 12)
            return
        if self._press and not self._press["moved"]:
            if (pos - self._press["pos"]).manhattanLength() > MOVE_CANCEL_PX:
                #сдвинулись до срабатывания удержания — это не перенос
                self._press["moved"] = True
                self._timer.stop()
                self._press = None

    def _begin_drag(self):
        if not self._press:
            return
        row, col = self._press["row"], self._press["col"]
        it = self.item(row, col)
        if not it or not it.data(Qt.UserRole):     #в ячейке нет пары — тащить нечего
            self._press = None
            return
        day, slot = self._day_slot(row, col)
        self._dragging = {"day": day, "slot": slot}
        self._ghost.setText(it.text().split("\n")[0] or "пара")
        self._ghost.adjustSize()
        self._ghost.move(self._press["pos"].x() + 12, self._press["pos"].y() + 12)
        self._ghost.show()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, e):
        self._timer.stop()
        self.unsetCursor()
        self._ghost.hide()
        pos = e.position().toPoint()
        if self._dragging:
            d = self._dragging
            self._dragging = None
            idx = self.indexAt(pos)
            if idx.isValid():
                to_day, to_slot = self._day_slot(idx.row(), idx.column())
                if to_day:
                    self.pairMoved.emit(d["day"], d["slot"], to_day, to_slot)
        elif self._press and not self._press["moved"]:
            day, slot = self._day_slot(self._press["row"], self._press["col"])
            if day:
                self.cellActivated.emit(day, slot)
        self._press = None


class ScheduleEditor(QWidget):
    """Редактор расписания в админ-вкладке «Расписание»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.week = 1
        self.DAYS = list(WEEKDAYS)
        self._base = None                 #слитое расписание группы (GroupSchedule)
        self._saved = set()               #(day,slot) уже сохранённых правок текущей недели
        self._pending = {}                #(week,day,slot) -> op
        self._conflicts = set()           #(week,day,slot) с накладкой
        self._workers = []
        self._cur_group = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        lay.addWidget(title_lbl("Расписание — редактор"))
        lay.addWidget(lbl("Удерживайте пару ~полсекунды и перетащите на другой слот или "
                          "день — время подстроится под номер пары. Тап по паре — правка, "
                          "по пустой ячейке — добавить. Правки синхронизируются с сайтом.",
                          11, C['text3'], wrap=True))

        bar = QHBoxLayout()
        self.group = combo([]); self.group.setMinimumWidth(160)
        self.group.currentTextChanged.connect(self._on_group_change)
        bar.addWidget(lbl("Группа", 12, C['text3'])); bar.addWidget(self.group)
        self.w1 = btn("I неделя", "green"); self.w2 = btn("II неделя", "ghost")
        self.w1.clicked.connect(lambda: self._set_week(1))
        self.w2.clicked.connect(lambda: self._set_week(2))
        bar.addWidget(self.w1); bar.addWidget(self.w2)
        bar.addStretch(1)
        for text, cb in (("↻ Взять с ВСГУТУ", self._refresh_group),
                         ("↻ Все группы", self._refresh_all),
                         ("Сброс группы", self._reset_group),
                         ("Сброс всех", self._reset_all)):
            b = btn(text, "ghost"); b.clicked.connect(cb); bar.addWidget(b)
        lay.addLayout(bar)

        #Полоса черновика — видна только при несохранённых правках.
        self._draft_bar = QWidget()
        db = QHBoxLayout(self._draft_bar); db.setContentsMargins(0, 0, 0, 0)
        db.addWidget(lbl("Есть несохранённые правки", 12, C['green']))
        db.addStretch(1)
        self._discard_b = btn("Отменить", "ghost"); self._discard_b.clicked.connect(self._discard)
        self._save_b = btn("Сохранить", "green"); self._save_b.clicked.connect(self._save)
        db.addWidget(self._discard_b); db.addWidget(self._save_b)
        lay.addWidget(self._draft_bar)
        self._draft_bar.hide()

        self._status = lbl("", 11, C['text3'])
        lay.addWidget(self._status)

        self.grid = _Grid(self.DAYS)
        self.grid.pairMoved.connect(self._on_pair_moved)
        self.grid.cellActivated.connect(self._on_cell_activated)
        lay.addWidget(self.grid, 1)

        self._load_groups()

    # ── данные ──────────────────────────────────────────────────────────────────────
    def _load_groups(self):
        names = []
        try:
            from data_store import get_store
            st = get_store()
            names = sorted({g.get("name") for g in (st.get_groups() if st else []) if g.get("name")})
        except Exception as e:
            log.get("schedule_editor").warning(f"[editor] группы: {e}")
        if not names:
            try:
                snap = sched_store.load_cached()
                names = sorted(snap.group_names()) if snap else []
            except Exception:
                names = []
        self.group.blockSignals(True)
        self.group.clear(); self.group.addItems(names)
        self.group.blockSignals(False)
        if names:
            self._cur_group = names[0]
            self._reload()

    def _cur(self) -> str:
        return self.group.currentText().strip()

    def _pair_times(self) -> list:
        pts = getattr(self._base, "pair_times", None)
        return list(pts) if pts else list(DEFAULT_PAIR_TIMES)

    def _time_for(self, slot: int) -> str:
        pts = self._pair_times()
        return pts[slot - 1] if 0 <= slot - 1 < len(pts) else ""

    def _slot_count(self) -> int:
        n = 6
        if self._base:
            for _w, days in self._base.weeks.items():
                for _d, lessons in days.items():
                    for ls in lessons:
                        n = max(n, int(getattr(ls, "pair_no", 0) or 0))
        for (w, _d, slot) in self._pending:
            if w == self.week:
                n = max(n, slot)
        return n

    def _base_pairs(self, day):
        if not self._base:
            return []
        return self._base.weeks.get(self.week, {}).get(day, [])

    def _cell(self, day, slot):
        op = self._pending.get((self.week, day, slot))
        if op is not None:
            if op["action"] == "remove":
                return None
            return {**op, "pending": True}
        for ls in self._base_pairs(day):
            if int(getattr(ls, "pair_no", 0)) == slot:
                return {"subject": getattr(ls, "subject", "") or getattr(ls, "raw", ""),
                        "time": getattr(ls, "time", ""), "room": getattr(ls, "room", ""),
                        "teacher": getattr(ls, "teacher", ""), "pending": False}
        return None

    def _reload(self, *_):
        group = self._cur()
        self._cur_group = group
        self._pending.clear()
        self._conflicts.clear()
        self._refresh_saved()
        try:
            self._base = sched_store.group_schedule(group) if group else None
        except Exception as e:
            log.get("schedule_editor").warning(f"[editor] расписание: {e}")
            self._base = None
        self._render()
        self._update_draft_bar()

    def _refresh_saved(self):
        self._saved = set()
        try:
            for o in sched_ov.list_overrides(self._cur()):
                if int(o["week"]) == self.week:
                    self._saved.add((o["day"], int(o["pair_no"])))
        except Exception:
            pass

    def _render(self):
        slots = self._slot_count()
        self.grid.setRowCount(slots)
        self.grid.setVerticalHeaderLabels([f"{i}\n{self._time_for(i)}" for i in range(1, slots + 1)])
        for r in range(slots):
            slot = r + 1
            for c, day in enumerate(self.DAYS):
                cell = self._cell(day, slot)
                it = QTableWidgetItem()
                if cell:
                    txt = cell["subject"]
                    sub = " · ".join([x for x in (cell.get("teacher"),
                                     ("ауд. " + cell["room"]) if cell.get("room") else "") if x])
                    it.setText(txt + ("\n" + sub if sub else ""))
                    it.setData(Qt.UserRole, True)      #в ячейке есть пара (можно тащить)
                    key = (self.week, day, slot)
                    if key in self._conflicts:
                        it.setBackground(QColor(220, 40, 40, 40)); it.setForeground(QColor("#b91c1c"))
                    elif key in self._pending:
                        it.setBackground(QColor(20, 160, 120, 35))
                    elif (day, slot) in self._saved:
                        it.setForeground(QColor(Qt.darkCyan))
                self.grid.setItem(r, c, it)

    def _update_draft_bar(self):
        self._draft_bar.setVisible(bool(self._pending))

    # ── правки черновика ─────────────────────────────────────────────────────────────
    def _on_pair_moved(self, from_day, from_slot, to_day, to_slot):
        if (from_day, from_slot) == (to_day, to_slot):
            return
        src = self._cell(from_day, from_slot)
        if not src:
            return
        if self._cell(to_day, to_slot):
            self._status.setText("Слот занят — сначала освободите его."); return
        self._pending[(self.week, from_day, from_slot)] = {"action": "remove"}
        self._conflicts.discard((self.week, from_day, from_slot))
        op = {"action": "set", "subject": src["subject"], "time": self._time_for(to_slot),
              "room": src.get("room", ""), "teacher": src.get("teacher", ""), "kind": ""}
        self._pending[(self.week, to_day, to_slot)] = op
        self._check_slot(to_day, to_slot, op)
        self._render(); self._update_draft_bar()

    def _check_slot(self, day, slot, op):
        try:
            res = sched_conf.slot_conflicts(self._cur(), self.week, day, slot,
                                            room=op.get("room", ""), teacher=op.get("teacher", ""),
                                            subject=op.get("subject", ""))
        except Exception as e:
            log.get("schedule_editor").warning(f"[editor] сверка слота: {e}")
            return
        key = (self.week, day, slot)
        if res["room"] or res["teacher"]:
            self._conflicts.add(key)
            who = (f"аудитория {op.get('room')}" if res["room"]
                   else f"преподаватель {op.get('teacher')}")
            self._status.setText(f"⚠ Накладка: {who} занят(а) в это время у другой группы.")
        else:
            self._conflicts.discard(key)
            self._status.setText("")

    def _on_cell_activated(self, day, slot):
        cell = self._cell(day, slot)
        dlg = _PairDialog(self, day=day, slot=slot,
                          subject=(cell or {}).get("subject", ""), room=(cell or {}).get("room", ""),
                          teacher=(cell or {}).get("teacher", ""), pair_times=self._pair_times())
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.value()
        #Сменили день/слот в форме — это перенос: старую ячейку скрыть.
        if (v["day"], v["slot"]) != (day, slot) and cell is not None:
            self._pending[(self.week, day, slot)] = {"action": "remove"}
            self._conflicts.discard((self.week, day, slot))
        op = {"action": "set", "subject": v["subject"], "time": v["time"],
              "room": v["room"], "teacher": v["teacher"], "kind": ""}
        self._pending[(self.week, v["day"], v["slot"])] = op
        self._check_slot(v["day"], v["slot"], op)
        self._render(); self._update_draft_bar()

    # ── сохранение / отмена ──────────────────────────────────────────────────────────
    def has_unsaved(self) -> bool:
        return bool(self._pending)

    def confirm_leave(self) -> bool:
        """True — можно уходить (нет правок или пользователь согласился их потерять)."""
        if not self._pending:
            return True
        return QMessageBox.question(
            self, "Несохранённые правки", "Продолжить без сохранения?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    def _save(self):
        if not self._pending:
            return
        group = self._cur()
        try:
            for (w, day, slot), op in self._pending.items():
                sched_ov.set_override(group, w, day, slot, action=op["action"],
                                      subject=op.get("subject", ""), time=op.get("time", ""),
                                      room=op.get("room", ""), teacher=op.get("teacher", ""),
                                      kind=op.get("kind", ""))
            self._status.setText("✅ Расписание сохранено.")
            self._reload()
        except Exception as e:
            log.get("schedule_editor").warning(f"[editor] сохранение: {e}")
            self._status.setText("⚠️ Не удалось сохранить правки.")

    def _discard(self):
        if not self._pending:
            return
        if QMessageBox.question(self, "Отменить правки", "Отменить несохранённые правки?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._pending.clear(); self._conflicts.clear()
        self._render(); self._update_draft_bar()
        self._status.setText("")

    # ── взять с ВСГУТУ / сброс ───────────────────────────────────────────────────────
    def _run_bg(self, fn, on_done):
        w = _BgWorker(fn)
        self._workers.append(w)
        w.done.connect(on_done)
        w.error.connect(lambda msg: self._status.setText(f"⚠️ Не удалось обновить: {msg}"))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        w.start()

    def _refresh_group(self):
        if not self.confirm_leave():
            return
        group = self._cur()
        self._status.setText("⏳ Обновляю группу с портала…")
        self._run_bg(lambda: sched_store.refresh_group(group),
                     lambda _r: (self._reload(), self._status.setText("✅ Обновлено с портала.")))

    def _refresh_all(self):
        if not self.confirm_leave():
            return
        if QMessageBox.question(self, "Обновить всё",
                "Скачать расписание ВСЕХ групп с портала? Это займёт до минуты.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._status.setText("⏳ Обновляю все группы с портала (до минуты)…")
        self._run_bg(sched_store.refresh_all,
                     lambda _r: (self._reload(), self._status.setText("✅ Все группы обновлены.")))

    def _reset_group(self):
        group = self._cur()
        if QMessageBox.question(self, "Сброс правок",
                f"Сбросить правки группы {group}? Расписание снова будет браться с портала.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            for o in sched_ov.list_overrides(group):
                sched_ov.delete_override(o["id"])
            self._reload(); self._status.setText("Правки группы сброшены.")
        except Exception as e:
            self._status.setText(f"⚠️ Не удалось сбросить: {e}")

    def _reset_all(self):
        if QMessageBox.question(self, "Сброс всех правок",
                "Удалить ручные правки ВСЕХ групп безвозвратно?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if QMessageBox.question(self, "Точно?",
                "Это действие необратимо. Удалить правки всех групп?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            for o in sched_ov.list_overrides():
                sched_ov.delete_override(o["id"])
            self._reload(); self._status.setText("Правки всех групп сброшены.")
        except Exception as e:
            self._status.setText(f"⚠️ Не удалось сбросить: {e}")

    # ── неделя / группа с защитой черновика ──────────────────────────────────────────
    def _set_week(self, w):
        self.week = w
        self.w1.setStyleSheet(BTN.get("green" if w == 1 else "ghost", ""))
        self.w2.setStyleSheet(BTN.get("green" if w == 2 else "ghost", ""))
        #Черновик по неделям раздельный (ключ включает неделю) — переключение не теряет его.
        self._refresh_saved()
        self._render()

    def _on_group_change(self, _text):
        if not self._pending:
            self._reload(); return
        if self.confirm_leave():
            self._reload()
        else:
            #вернуть прежнюю группу, не трогая черновик
            self.group.blockSignals(True)
            self.group.setCurrentText(self._cur_group)
            self.group.blockSignals(False)
