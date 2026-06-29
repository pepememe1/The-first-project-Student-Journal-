"""
teacher_dashboard.py — TeacherDashboard
Часть рефакторинга GUI.py → модульная архитектура
"""

import os
from datetime import datetime, timedelta
import ui_date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHeaderView,
    QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QFrame
)

from styles import C, BTN
from widgets import (
    lbl, title_lbl, section_lbl, btn, combo, card, separator, stat_card,
    vector_unavailable_widget
)
from ui_components import Sidebar
from utils import get_groups

from core import GradeBook, Student
from data_store import get_store


class TeacherDashboard(QWidget):
    def __init__(self, teacher_name: str, teacher_data: dict, parent=None):
        super().__init__(parent)
        self.teacher_name = teacher_name
        self.teacher_data = teacher_data
        self.book = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        items = [
            ("__label__", "", "Журнал"),
            ("journal",  "clipboard", "Журнал"),
            ("students", "users",     "Студенты"),
            ("stats",    "chart",     "Статистика"),
            ("ai",       "bot",       "ИИ Помощник"),
            ("__label__", "", "Личное"),
            ("profile",  "user",      "Профиль"),
        ]
        self.sidebar = Sidebar(items)
        self.sidebar.tab_clicked.connect(self._switch)
        self.stack = QStackedWidget()
        self.pages = {}
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        body.addWidget(self.sidebar); body.addWidget(self.stack, 1)
        lay.addLayout(body)
        self._build_journal()
        self._build_students()
        self._build_stats()
        self._build_ai()
        self._build_profile()
        self.sidebar.set_active("journal")
        self._init_selectors()

        #Вектор постоянно слева (⇄ — вправо, — свернуть/вернуть 🐯)
        try:
            from vector.widget import VectorPanel, VectorHost
            self._ensure_vector_session()
            self.vector_dock = VectorHost(
                body, VectorPanel(self.vector_session, docked=True))
            self.vector_dock.mount(side="left")
        except Exception as _e:
            print(f"[Vector] панель сбоку (препод): {_e}")

    def _ensure_vector_session(self):
        """Создаёт ОБЩУЮ сессию Вектора (одна история для шторки и вкладки). Движок
        собирается один раз; шторка и вкладка «ИИ Помощник» делят эту сессию."""
        if getattr(self, "vector_session", None) is not None:
            return self.vector_session
        from vector import VectorEngine, VectorScope, get_provider
        from vector.widget import VectorSession
        try:
            from data_store import get_store as _gs
            _cfg0 = _gs()._config()
        except Exception:
            _cfg0 = {}
        eng = VectorEngine(VectorScope(
            role="teacher", group=self._group_combo.currentText(),
            subject=self._subj_combo.currentText() or None), get_provider(_cfg0))
        self.vector_engine = eng
        self.vector_session = VectorSession(eng)
        return self.vector_session

    #Журнал

    def _build_journal(self):
        w = QWidget()
        lay = QVBoxLayout(w); lay.setContentsMargins(20, 18, 20, 18); lay.setSpacing(10)
        #Заголовок
        hdr = QHBoxLayout()
        hdr.addWidget(title_lbl("Журнал преподавателя", 20), 1)
        self._subj_combo = combo(self.teacher_data.get("subjects", []))
        self._subj_combo.currentTextChanged.connect(self._on_subj_change)
        raw_groups = get_groups()
        group_names = [g["name"] if isinstance(g, dict) else str(g) for g in raw_groups]
        self._group_combo = combo(group_names)
        self._group_combo.currentTextChanged.connect(self._reload_journal)
        hdr.addWidget(lbl("Предмет:", 12, C['text3'])); hdr.addWidget(self._subj_combo)
        hdr.addWidget(lbl("Группа:",  12, C['text3'])); hdr.addWidget(self._group_combo)
        lay.addLayout(hdr)
        #Кнопки
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        for txt, style, cb in [
            ("+ Лекция/Практика", "green",  self._add_lesson),
            ("+ Экзамен",         "blue",   self._add_exam),
            ("+ Студент",         "ghost",  self._add_student),
            ("💾 Сохранить",      "ghost",  self._save),
            ("📤 Экспорт",        "ghost",  self._export_excel),
            ("📥 Импорт",         "ghost",  self._import_excel),
        ]:
            b = btn(txt, style); b.clicked.connect(cb); btn_row.addWidget(b)
        #индикатор конфликтов синхронизации (виден, только если они есть)
        self._conflict_btn = btn("⚠ Конфликты", "blue")
        self._conflict_btn.clicked.connect(self._open_conflicts)
        self._conflict_btn.hide()
        btn_row.addWidget(self._conflict_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        self._refresh_conflicts_badge()
        #Таблица
        self.t_table = QTableWidget()
        self.t_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.t_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.t_table.horizontalHeader().customContextMenuRequested.connect(self._header_ctx)
        self.t_table.setWordWrap(True)
        self.t_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.t_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        lay.addWidget(self.t_table, 1)
        self.pages["journal"] = w; self.stack.addWidget(w)

    def _init_selectors(self):
        subjects = self.teacher_data.get("subjects", [])
        self._subj_combo.clear(); self._subj_combo.addItems(subjects)
        if subjects:
            ga  = self.teacher_data.get("group_assignments", {})
            grp = ga.get(subjects[0], "")
            #get_groups() может вернуть строки или dict — нормализуем
            raw_groups = get_groups()
            group_names = [
                g["name"] if isinstance(g, dict) else str(g)
                for g in raw_groups
            ]
            self._group_combo.clear()
            self._group_combo.addItems(group_names)
            if grp:
                idx = self._group_combo.findText(grp)
                if idx >= 0: self._group_combo.setCurrentIndex(idx)
        self._reload_journal()

    def _on_subj_change(self):
        subj = self._subj_combo.currentText()
        ga   = self.teacher_data.get("group_assignments", {})
        grp  = ga.get(subj, "")
        if grp:
            idx = self._group_combo.findText(grp)
            if idx >= 0: self._group_combo.setCurrentIndex(idx)
        self._reload_journal()

    def _reload_journal(self):
        subj  = self._subj_combo.currentText()
        group = self._group_combo.currentText()
        if not subj or not group: return
        self.book = GradeBook(group, subj)
        #Вектор отвечает по той группе/предмету, что открыты сейчас
        if getattr(self, "vector_engine", None):
            self.vector_engine.scope.group = group
            self.vector_engine.scope.subject = subj
        self._sync_students_from_store()
        self._update_table()

    def _sync_students_from_store(self):
        """Подтянуть студентов из общего хранилища и добавить недостающих в журнал."""
        if not self.book: return
        store = get_store()
        if not store: return
        try:
            known_students = store.get_students()
            group = self.book.group
            existing = {s.f.lower() for s in self.book.spisok_stud}
            added = False
            for s in known_students:
                if s.get("group", "") != group: continue
                surname = s.get("surname", "")
                if surname.lower() not in existing:
                    st = Student(s.get("name", ""), surname, group)
                    self.book.add_student(st)
                    existing.add(surname.lower())
                    added = True
            if added:
                self.book.save_to_db()
        except Exception as e:
            print(f"[sync students] {e}")

    def _update_table(self):
        if not self.book: return
        students = self.book.spisok_stud
        col_defs = []
        for l in self.book.lessons:
            col_defs.append((l, 0))
            if l.type == "Экзамен":
                ri = 1
                while getattr(l, f'retake_date{"" if ri == 1 else "_" + str(ri)}', ''):
                    col_defs.append((l, ri)); ri += 1
        self.t_table.setRowCount(len(students))
        self.t_table.setColumnCount(2 + len(col_defs))
        #Тему в шапке показываем коротко (чтобы столбец не разъезжался), но
        #полную тему кладём в подсказку — наведёшь мышь и прочитаешь целиком.
        def _short(text: str, limit: int = 22) -> str:
            text = (text or "").strip()
            if len(text) <= limit:
                return text
            cut = text[:limit].rstrip()
            sp = cut.rfind(" ")
            if sp >= limit - 8:          #обрезаем по последнему пробелу, не посреди слова
                cut = cut[:sp].rstrip()
            return cut + "…"
        headers = ["Фамилия", "Имя"]
        tooltips = ["", ""]
        for l, ri in col_defs:
            if ri > 0:
                rd = getattr(l, f'retake_date{"" if ri == 1 else "_" + str(ri)}', '')
                headers.append(f"Пересдача №{ri}\n{rd}"); tooltips.append("")
            elif l.type == "Лекция":
                headers.append(f"Лекция {l.number}{f' ({l.hour}-й ч.)' if l.hour else ''}\n{l.date}\n{_short(l.topic)}")
                tooltips.append(l.topic or "")
            elif l.type == "Экзамен":
                headers.append(f"Экзамен №{l.number}\n{l.date}\n{_short(l.topic)}")
                tooltips.append(l.topic or "")
            else:
                headers.append(f"Практика {l.number}\n{l.date}\n{_short(l.topic)}")
                tooltips.append(l.topic or "")
        self.t_table.setHorizontalHeaderLabels(headers)
        #полная тема в подсказке заголовка
        for c, tip in enumerate(tooltips):
            it = self.t_table.horizontalHeaderItem(c)
            if it is not None and tip:
                it.setToolTip(tip)
        self.t_table.blockSignals(True)
        for r, s in enumerate(students):
            fi = QTableWidgetItem(s.f); fi.setForeground(QColor(C['text']))
            ni = QTableWidgetItem(s.n); ni.setForeground(QColor(C['text3']))
            self.t_table.setItem(r, 0, fi); self.t_table.setItem(r, 1, ni)
            for ci, (l, ri) in enumerate(col_defs):
                col = 2 + ci
                rk  = l.id + ("_retake" if ri == 1 else f"_retake_{ri}" if ri > 1 else "")
                val = s.records.get(rk if ri > 0 else l.id, "")
                if l.type == "Лекция" and ri == 0:
                    cb = QComboBox()
                    cb.addItems(["", "✓", "Н", "Б", "О"])
                    cb.setCurrentText(val)
                    cb.setStyleSheet(f"background:{C['card2']};border:1px solid {C['border']};border-radius:5px;color:{C['text']};font-size:12px;padding:2px;")
                    cb.currentTextChanged.connect(lambda v, st=s, k=l.id: self._set_val(st, k, v))
                    self.t_table.setCellWidget(r, col, cb)
                elif l.type == "Практика" and ri == 0:
                    cb = QComboBox()
                    cb.addItems(["", "2", "3", "4", "5", "Н"])
                    cb.setCurrentText(val)
                    cb.setStyleSheet(f"background:{C['card2']};border:1px solid {C['border']};border-radius:5px;color:{C['text']};font-size:12px;padding:2px;")
                    cb.currentTextChanged.connect(lambda v, st=s, k=l.id: self._set_val(st, k, v))
                    self.t_table.setCellWidget(r, col, cb)
                elif l.type == "Экзамен" or ri > 0:
                    rk_full = l.id + (f"_retake" if ri == 1 else f"_retake_{ri}" if ri > 1 else "")
                    #ФИКС БАГА: пересдача назначается не всем.
                    #Ячейка пересдачи №ri активна только у студента, который
                    #ЗАВАЛИЛ предыдущую попытку (2 / Н / «Не зачтено»).
                    #Сдавшим — серый прочерк без редактирования.
                    if ri > 0 and not self._needs_retake(s, l, ri):
                        it = QTableWidgetItem("—")
                        it.setTextAlignment(Qt.AlignCenter)
                        it.setFlags(Qt.ItemIsEnabled)          #не редактируется
                        it.setForeground(QColor(C['text3']))
                        self.t_table.setItem(r, col, it)
                        continue
                    cb = QComboBox()
                    cb.addItems(["", "2", "3", "4", "5", "Н"])
                    raw = val.split()[0] if val else ""
                    cb.setCurrentText(raw)
                    cb.setStyleSheet(f"background:{C['card2']};border:1px solid {C['border']};border-radius:5px;color:{C['text']};font-size:12px;padding:2px;")
                    cb.currentTextChanged.connect(lambda v, st=s, le=l, rk=rk_full, ri_=ri: self._set_exam_val(st, le, rk, v, ri_))
                    self.t_table.setCellWidget(r, col, cb)
        self.t_table.blockSignals(False)
        self.t_table.resizeColumnsToContents()
        hh = self.t_table.horizontalHeader()
        hh.setMinimumSectionSize(90); hh.setDefaultAlignment(Qt.AlignCenter)
        self.t_table.setColumnWidth(0, 130); self.t_table.setColumnWidth(1, 100)
        for c in range(2, self.t_table.columnCount()):
            self.t_table.setColumnWidth(c, max(self.t_table.columnWidth(c), 100))

    def _set_val(self, student, key, val):
        student.records[key] = val
        self._persist_grade(student, key, val)

    def _persist_grade(self, student, key, val):
        """Пишем оценку в локальную БД СРАЗУ (offline-first: каждое действие → диск).

        Раньше оценка жила только в памяти до нажатия «Сохранить»; при переключении
        группы/предмета (журнал перезагружается из БД) или закрытии программы
        несохранённое терялось. Теперь правка не пропадёт. После записи будим
        фоновую синхронизацию, чтобы оценка ушла на сервер без ожидания интервала."""
        try:
            from core import DBManager
            conn = DBManager.get_conn()
            cur = conn.cursor()
            DBManager.upsert_grade(cur, (student.f, student.n, key, val))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[journal] не удалось сохранить оценку: {e}")
        try:
            from sync_runner import trigger
            trigger()
        except Exception:
            pass

    #конфликты синхронизации
    def _refresh_conflicts_badge(self):
        try:
            from core import DBManager
            n = len(DBManager.list_conflicts(unresolved_only=True))
            if hasattr(self, "_conflict_btn"):
                self._conflict_btn.setVisible(n > 0)
                if n > 0:
                    self._conflict_btn.setText(f"⚠ Конфликты ({n})")
        except Exception:
            pass

    def _open_conflicts(self):
        try:
            from conflict_dialog import ConflictDialog
            ConflictDialog(self).exec()
            self._refresh_conflicts_badge()
            self._update_table()
        except Exception as e:
            QMessageBox.warning(self, "Конфликты", f"Не удалось открыть: {e}")

    #хелперы пересдач
    @staticmethod
    def _attempt_key(lesson, ri: int) -> str:
        """Ключ записи попытки №ri: 0 — основной экзамен, 1 — _retake, 2+ — _retake_N."""
        if ri <= 0:
            return lesson.id
        return lesson.id + ("_retake" if ri == 1 else f"_retake_{ri}")

    @staticmethod
    def _is_failed(val: str) -> bool:
        """Попытка считается заваленной: 2, Н или «Не зачтено» (в т.ч. 3 без зачёта)."""
        v = (val or "").strip()
        if not v:
            return False
        return v.startswith(("2", "Н")) or "Не зачтено" in v

    def _needs_retake(self, student, lesson, ri: int) -> bool:
        """
        Нужна ли студенту пересдача №ri: предыдущая попытка должна быть
        ЗАВАЛЕНА. Если ячейка пересдачи уже заполнена (оценка проставлена
        ранее) — тоже показываем, чтобы не прятать существующие данные.
        """
        if student.records.get(self._attempt_key(lesson, ri), ""):
            return True
        prev = student.records.get(self._attempt_key(lesson, ri - 1), "")
        return self._is_failed(prev)

    def _set_exam_val(self, student, lesson, key, val, ri):
        if not val: return
        if val in ("4", "5"):
            full = val + " (Зачтено)"
        elif val == "3":
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Оценка 3")
            dlg.setText(f"Оценка 3 у {student.f}. Засчитать или на пересдачу?")
            bp = dlg.addButton("✅ Зачёт", QMessageBox.AcceptRole)
            dlg.addButton("❌ Пересдача", QMessageBox.RejectRole)
            dlg.exec()
            if dlg.clickedButton() == bp:
                full = "3 (Зачтено)"
            else:
                full = "3 (Не зачтено)"
                rd = ui_date.ask_date(self, "Дата пересдачи", "Когда пересдача:",
                    default=ui_date.plus_days_str(7), min_today=True)
                if rd: self.book.set_retake_date(lesson.id, rd, ri + 1)
        elif val in ("2", "Н"):
            full = val + " (Не зачтено)"
            rd = ui_date.ask_date(self, "Дата пересдачи", "Когда пересдача:",
                default=ui_date.plus_days_str(7), min_today=True)
            if rd: self.book.set_retake_date(lesson.id, rd, ri + 1 if ri > 0 else 1)
        else:
            full = val
        student.records[key] = full
        self._persist_grade(student, key, full)   #сразу на диск (offline-first)
        self._update_table()

    def _header_ctx(self, pos):
        col = self.t_table.horizontalHeader().logicalIndexAt(pos)
        if col < 2: return
        ci = col - 2
        col_defs = []
        for l in self.book.lessons:
            col_defs.append((l, 0))
            if l.type == "Экзамен":
                ri = 1
                while getattr(l, f'retake_date{"" if ri == 1 else "_" + str(ri)}', ''):
                    col_defs.append((l, ri)); ri += 1
        if ci >= len(col_defs): return
        l, ri = col_defs[ci]
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;"
            f"color:{C['text']};padding:4px;}}"
            f"QMenu::item{{padding:8px 16px;border-radius:6px;}}"
            f"QMenu::item:selected{{background:rgba(20,124,139,0.1);color:{C['green']};}}"
        )
        if l.type == "Экзамен" and ri == 0:
            a = menu.addAction("📅 Назначить пересдачу")
            a.triggered.connect(lambda: self._ask_retake(l, 1))
        if l.type in ("Лекция", "Практика", "Экзамен"):
            d = menu.addAction("🗑  Удалить столбец")
            d.triggered.connect(lambda: self._delete_lesson(l.id))
        menu.exec(self.t_table.horizontalHeader().mapToGlobal(pos))

    def _ask_retake(self, lesson, n):
        rd = ui_date.ask_date(self, "Дата пересдачи", "Когда пересдача:",
            default=ui_date.plus_days_str(7), min_today=True)
        if rd:
            self.book.set_retake_date(lesson.id, rd, n); self._update_table()

    def _delete_lesson(self, lesson_id):
        if QMessageBox.question(self, "Удалить занятие?", "Удалить этот столбец?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        #delete_lesson ставит надгробие в БД (а не просто убирает из списка) —
        #раньше столбец возвращался после перезагрузки и не удалялся на других ПК.
        self.book.delete_lesson(lesson_id); self._update_table()

    def _journal_ready(self) -> bool:
        """Журнал открыт (выбраны предмет и группа)? Если нет — self.book пуст, и
        добавление молча падало бы: в .exe без консоли исключение не видно. Поэтому
        проверяем заранее и понятно сообщаем пользователю."""
        if not self.book:
            QMessageBox.warning(self, "Журнал не открыт",
                "Сначала выберите предмет и группу на вкладке «Журнал».")
            return False
        return True

    def _add_lesson(self):
        if not self._journal_ready():
            return
        t, ok = QInputDialog.getItem(self, "Тип", "Выберите тип:", ["Лекция", "Практика"], 0, False)
        if not ok: return
        d = ui_date.ask_date(self, "Дата занятия", "Когда занятие:",
                             default=ui_date.today_str())
        if not d: return
        tp, ok3 = QInputDialog.getText(self, "Тема", "Тема занятия:")
        if not ok3: return
        try:
            self.book.add_lesson(t, topic=tp.strip(), date=d)
            self._update_table()
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Не удалось добавить занятие", str(e))

    def _add_exam(self):
        if not self._journal_ready():
            return
        d = ui_date.ask_date(self, "Дата экзамена", "Когда экзамен:",
                             default=ui_date.today_str())
        if not d: return
        tp, ok2 = QInputDialog.getText(self, "Тема", "Тема экзамена:")
        if not ok2: return
        try:
            l = self.book.add_lesson("Экзамен", topic=tp.strip(), date=d)
            l.retake_date = ""
            self.book.save_to_db(); self._update_table()
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Не удалось добавить экзамен", str(e))

    def _add_student(self):
        #Если журнал ещё не открыт — предупреждаем
        if not self.book:
            QMessageBox.warning(
                self, "Журнал не открыт",
                "Сначала откройте журнал:\nвыберите предмет и группу на вкладке «Журнал»."
            )
            return
        sn, ok = QInputDialog.getText(self, "Фамилия", "Введите фамилию:")
        if not ok or not sn.strip(): return
        nm, ok2 = QInputDialog.getText(self, "Имя", "Введите имя:")
        if not ok2: return
        sn, nm = sn.strip(), nm.strip()
        if any(s.f.lower() == sn.lower() for s in self.book.spisok_stud):
            QMessageBox.information(self, "Уже есть", f"{sn} уже в списке"); return
        st = Student(nm, sn, self.book.group)
        self.book.add_student(st)
        gh = get_store()
        if gh:
            try:
                ss = gh.get_students()
                if not any(s.get("surname", "").lower() == sn.lower() and
                           s.get("name", "").lower() == nm.lower() for s in ss):
                    ss.append({"surname": sn, "name": nm, "group": self.book.group})
                    gh.set_students(ss)
            except Exception as e:
                print(f"[GH add student] {e}")
        self._update_table()

    def _save(self):
        if self.book: self.book.save_to_db()
        QMessageBox.information(self, "Сохранено", "Данные сохранены.")

    def _export_excel(self):
        if not self.book: return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить", "", "Excel (*.xlsx)")
        if path:
            try:
                self.book.export_to_excel(path)
                QMessageBox.information(self, "Excel", "Готово!")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _import_excel(self):
        if not self.book:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте журнал."); return
        path, _ = QFileDialog.getOpenFileName(self, "Открыть Excel", "", "Excel (*.xlsx *.xls)")
        if not path: return
        try:
            from openpyxl import load_workbook
            wb = load_workbook(path); ws = wb.active; rows = list(ws.iter_rows(values_only=True))
            if len(rows) < 2: QMessageBox.warning(self, "Ошибка", "Файл пустой."); return
            added = updated = 0
            for row in rows[1:]:
                if not row or not row[0]: continue
                sn = str(row[0]).strip()
                nm = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                s  = next((x for x in self.book.spisok_stud if x.f.lower() == sn.lower()), None)
                if not s:
                    s = Student(nm, sn, self.book.group); self.book.spisok_stud.append(s); added += 1
                for ci, val in enumerate(row[2:], start=2):
                    if ci - 2 >= len(self.book.lessons): break
                    if val is not None and str(val).strip():
                        s.records[self.book.lessons[ci - 2].id] = str(val).strip(); updated += 1
            self.book.save_to_db(); self._update_table()
            QMessageBox.information(self, "Импорт",
                f"Добавлено студентов: {added}\nОбновлено записей: {updated}")
        except ImportError:
            QMessageBox.critical(self, "Ошибка", "pip install openpyxl")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    #Студенты

    def _build_students(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(12)
        lay.addWidget(title_lbl("Студенты группы"))
        btn_row = QHBoxLayout()
        add_b = btn("+ Добавить", "green"); add_b.clicked.connect(self._add_student)
        btn_row.addWidget(add_b); btn_row.addStretch()
        lay.addLayout(btn_row)
        self._stud_table = QTableWidget()
        self._stud_table.setColumnCount(4)
        self._stud_table.setHorizontalHeaderLabels(["Фамилия", "Имя", "Средний балл", ""])
        self._stud_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._stud_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self._stud_table, 1)
        self.pages["students"] = w; self.stack.addWidget(w)

    def _refresh_students(self):
        if not self.book: return
        students = self.book.spisok_stud
        self._stud_table.setRowCount(len(students))
        for r, s in enumerate(students):
            gs = []
            for l in self.book.lessons:
                if l.type in ("Практика", "Экзамен"):
                    v = s.records.get(l.id, "")
                    try: gs.append(int(v.split()[0]))
                    except: pass
            avg = f"{sum(gs)/len(gs):.1f}" if gs else "—"
            self._stud_table.setItem(r, 0, QTableWidgetItem(s.f))
            self._stud_table.setItem(r, 1, QTableWidgetItem(s.n))
            self._stud_table.setItem(r, 2, QTableWidgetItem(avg))
            del_b = QPushButton("✕"); del_b.setStyleSheet(BTN["sm_red"])
            del_b.clicked.connect(lambda _, f=s.f, n=s.n: self._del_student(f, n))
            self._stud_table.setCellWidget(r, 3, del_b)

    def _del_student(self, f, n):
        if QMessageBox.question(self, "Удалить?", f"Удалить {f} {n}?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        self.book.delete_student(f, n)
        gh = get_store()
        if gh:
            try:
                ss = [x for x in gh.get_students()
                      if not (x.get("surname", "") == f and x.get("name", "") == n)]
                gh.set_students(ss)
            except Exception as e:
                print(f"[GH del student] {e}")
        self._refresh_students(); self._update_table()

    #Статистика

    def _build_stats(self):
        w = QScrollArea(); w.setWidgetResizable(True); w.setStyleSheet("border:none;")
        inner = QWidget()
        lay = QVBoxLayout(inner); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("Статистика группы"))
        self._tstat_content = QVBoxLayout(); lay.addLayout(self._tstat_content)
        lay.addStretch()
        w.setWidget(inner)
        self.pages["stats"] = w; self.stack.addWidget(w)

    def _refresh_stats(self):
        while self._tstat_content.count():
            it = self._tstat_content.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        if not self.book: return
        students = self.book.spisok_stud
        dist = {2: 0, 3: 0, 4: 0, 5: 0}; att_rows = []
        for s in students:
            gs = []; lt = lp = 0
            for l in self.book.lessons:
                if l.type in ("Практика", "Экзамен"):
                    v = s.records.get(l.id, "")
                    try: g = int(v.split()[0]); gs.append(g); dist[g] += 1
                    except: pass
                elif l.type == "Лекция":
                    lt += 1
                    if s.records.get(l.id, "") != "Н": lp += 1
            avg = sum(gs) / len(gs) if gs else 0
            att = int(lp / lt * 100) if lt else 100
            att_rows.append((s.f, att, avg))
        all_g     = sum(dist.values())
        total_avg = f"{sum(k*v for k,v in dist.items())/all_g:.1f}" if all_g else "—"
        sr = QHBoxLayout(); sr.setSpacing(10)
        for l, v, c in [
            ("Студентов",  str(len(students)), "green"),
            ("Средний балл", total_avg, "blue"),
            ("Оценок",     str(all_g),  "text"),
            ("Занятий",    str(len(self.book.lessons)), "text"),
        ]:
            sr.addWidget(stat_card(l, v, c))
        self._tstat_content.addLayout(sr)
        #Распределение оценок
        dc = card(); dl = QVBoxLayout(dc); dl.setContentsMargins(18, 16, 18, 16)
        dl.addWidget(section_lbl("Распределение оценок"))
        cols = {5: C['green'], 4: C['blue'], 3: C['yellow'], 2: C['red']}
        for g in [5, 4, 3, 2]:
            cnt = dist[g]; pct = int(cnt / all_g * 100) if all_g else 0
            row = QHBoxLayout()
            row.addWidget(lbl(str(g), 14, cols[g], True))
            bar = QFrame(); bar.setFixedHeight(4)
            bar.setStyleSheet(f"background:{C['border']};border-radius:2px;")
            row.addWidget(bar, 1)
            row.addWidget(lbl(f"{cnt} ({pct}%)", 12, C['text3']))
            dl.addLayout(row)
        self._tstat_content.addWidget(dc)
        #Посещаемость
        ac = card(); al = QVBoxLayout(ac); al.setContentsMargins(18, 16, 18, 16)
        al.addWidget(section_lbl("Посещаемость по студентам"))
        for f, att, avg_s in sorted(att_rows, key=lambda x: -x[1]):
            c = C['green'] if att >= 90 else C['blue'] if att >= 70 else C['red']
            row = QHBoxLayout()
            row.addWidget(lbl(f, 12, C['text'])); row.setStretch(0, 1)
            bar = QFrame(); bar.setFixedHeight(4)
            bar.setStyleSheet(f"background:{C['border']};border-radius:2px;")
            row.addWidget(bar, 2)
            row.addWidget(lbl(f"{att}%", 12, c, True))
            al.addLayout(row)
        self._tstat_content.addWidget(ac)

    #ИИ помощник

    def _build_ai(self):
        """Вкладка «ИИ Помощник» — Вектор (офлайн / GigaChat / Ollama).
        Делит ОБЩУЮ сессию со шторкой — переписка единая."""
        try:
            from vector.widget import VectorPanel
            self._ensure_vector_session()
            ai = VectorPanel(self.vector_session, docked=False)
        except Exception as _e:
            print(f"[Vector] вкладка не собралась (препод): {_e}")
            ai = vector_unavailable_widget()
        self.pages["ai"] = ai; self.stack.addWidget(ai)

    def _build_profile(self):
        """Вкладка «Профиль»: данные преподавателя + кастомизация темы оформления."""
        from theme_ui import ThemeCustomizer
        import theme_service
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        identity = {"name": self.teacher_name}
        spec = theme_service.current_spec("teacher", identity)

        def _save(s):
            theme_service.save_user_theme(s, "teacher", identity)
            self._request_theme_rebuild()

        lay.addWidget(ThemeCustomizer(initial_spec=spec, on_save=_save))
        self.pages["profile"] = w; self.stack.addWidget(w)

    def _request_theme_rebuild(self):
        """Просим главное окно пересобрать дашборд — чтобы новая тема применилась
        целиком (инлайн-стили перекрашиваются только при пересборке)."""
        win = self.window()
        if hasattr(win, "reapply_current"):
            win.reapply_current()

    #Роутинг

    def _switch(self, key):
        if getattr(self, '_switching', False):
            return
        self._switching = True
        try:
            if key == "stats":    self._refresh_stats()
            if key == "students": self._refresh_students()
            #Шторка Вектора на вкладке «ИИ» прячется, на остальных — возвращается.
            dock = getattr(self, "vector_dock", None)
            if dock is not None:
                dock.suspend() if key == "ai" else dock.resume()
            if key in self.pages:
                self.stack.setCurrentWidget(self.pages[key])
                self.sidebar.set_active(key)
        finally:
            self._switching = False
