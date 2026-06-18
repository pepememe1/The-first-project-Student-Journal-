"""
admin_dashboard.py — AdminDashboard
Часть рефакторинга GUI.py → модульная архитектура
"""

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSpacerItem, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QFrame
)

from styles import C, BTN
from widgets import (
    lbl, title_lbl, section_lbl, btn, combo, card, field_input,
    separator, stat_card
)
from ui_components import Sidebar
from ai_module import AIWidget

from PySide6.QtCore import QThread, Signal as QSignal

from core import DBManager
from subjects import load_subjects
from data_store import get_store as get_gh_store
from audit import log_event


# ── Фоновый воркер для сетевых/долгих запросов ──────────────────────
class _GHWorker(QThread):
    """Выполняет fn() в фоновом потоке, возвращает результат через сигнал."""
    done  = QSignal(object)   # успех — данные
    error = QSignal(str)      # ошибка

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as e:
            self.error.emit(str(e))


def _subject_picker(parent, selected: list[str]) -> QListWidget:
    """QListWidget с чекбоксами для выбора предметов из каталога."""
    lw = QListWidget(parent)
    lw.setSelectionMode(QAbstractItemView.NoSelection)
    lw.setStyleSheet(
        f"QListWidget{{background:{C['card2']};border:1px solid {C['border2']};"
        f"border-radius:8px;padding:4px;color:{C['text']};font-size:12px;}}"
        f"QListWidget::item{{padding:4px 8px;border-radius:4px;}}"
        f"QListWidget::item:hover{{background:rgba(20,124,139,0.08);}}"
    )
    for subj in sorted(load_subjects()):
        it = QListWidgetItem(subj)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if subj in selected else Qt.Unchecked)
        lw.addItem(it)
    return lw


def _get_checked(lw: QListWidget) -> list[str]:
    """Возвращает список отмеченных предметов из QListWidget."""
    return [lw.item(i).text() for i in range(lw.count())
            if lw.item(i).checkState() == Qt.Checked]


class AdminDashboard(QWidget):
    def __init__(self, back_to_login_cb, parent=None):
        super().__init__(parent)
        self._back_cb = back_to_login_cb
        self._workers = []   # держим ссылки чтобы GC не убил потоки
        self._build()

    def _build(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        items = [
            ("__label__", "", "Управление"),
            ("dash",     "🏠",  "Дашборд"),
            ("teachers", "👨‍🏫", "Преподаватели"),
            ("students", "👥",  "Студенты"),
            ("groups",   "🏫",  "Группы"),
            ("subjects", "📚",  "Предметы"),
            ("__label__", "", "Система"),
            ("api",  "🔑",  "API Ключ"),
            ("pg",   "🗄️", "База данных"),
            ("ai",   "🤖",  "ИИ Помощник"),
        ]
        self.sidebar = Sidebar(items)
        self.sidebar.tab_clicked.connect(self._switch)
        self.stack = QStackedWidget()
        self.pages = {}
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        body.addWidget(self.sidebar); body.addWidget(self.stack, 1)
        lay.addLayout(body)
        self._build_dash()
        self._build_teachers()
        self._build_students()
        self._build_groups()
        self._build_subjects()
        self._build_api()
        self._build_pg()
        self._build_ai()
        self.sidebar.set_active("dash")

        # ── Вектор постоянно слева (⇄ — вправо, — свернуть/вернуть 🐯) ──
        try:
            from vector.widget import VectorPanel, VectorHost
            eng = getattr(self, "vector_engine", None)
            if eng is None:
                from vector import VectorEngine, VectorScope, get_provider
                try:
                    from data_store import get_store as _gs
                    _cfg0 = _gs()._config()
                except Exception:
                    _cfg0 = {}
                eng = VectorEngine(VectorScope(role="admin"), get_provider(_cfg0))
                self.vector_engine = eng
            self.vector_dock = VectorHost(body, VectorPanel(eng, docked=True))
            self.vector_dock.mount(side="left")
        except Exception as _e:
            print(f"[Vector] панель сбоку (админ): {_e}")

    def _run_bg(self, fn, on_done, on_error=None):
        """Запустить fn() в фоновом потоке; on_done(result) вызовется в UI-потоке."""
        w = _GHWorker(fn)
        self._workers.append(w)
        w.done.connect(on_done)
        w.done.connect(lambda _: self._workers.remove(w) if w in self._workers else None)
        if on_error:
            w.error.connect(on_error)
        else:
            w.error.connect(lambda e: print(f"[BG] фоновая ошибка: {e}"))
        w.start()

    # Дашборд

    def _build_dash(self):
        w = QScrollArea(); w.setWidgetResizable(True); w.setStyleSheet("border:none;")
        inner = QWidget(); lay = QVBoxLayout(inner); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("Панель администратора"))
        self._dash_stats = QHBoxLayout(); self._dash_stats.setSpacing(10)
        lay.addLayout(self._dash_stats)
        tiles = [
            ("teachers", "👨‍🏫", "Преподаватели", "Учётные записи"),
            ("students", "👥",   "Студенты",      "Список и пароли"),
            ("groups",   "🏫",   "Группы",         "Группы и предметы"),
            ("subjects", "📚",   "Предметы",       "Каталог предметов"),
            ("api",      "🔑",   "API Ключ",       "OpenRouter AI"),
            ("pg",       "🗄️",  "База данных",    "PostgreSQL / перенос"),
        ]
        grid = QGridLayout(); grid.setSpacing(12)
        for i, (key, icon, ttl, desc) in enumerate(tiles):
            f = QFrame(); f.setObjectName("card"); f.setCursor(Qt.PointingHandCursor)
            fl = QVBoxLayout(f); fl.setContentsMargins(20, 18, 20, 18)
            fl.addWidget(lbl(icon, 32))
            fl.addWidget(lbl(ttl, 15, C['text'], True))
            fl.addWidget(lbl(desc, 11, C['text3']))
            f.mousePressEvent = lambda e, k=key: self._switch(k)
            grid.addWidget(f, i // 3, i % 3)
        lay.addLayout(grid); lay.addStretch()
        w.setWidget(inner)
        self.pages["dash"] = w; self.stack.addWidget(w)
        self._refresh_dash()

    def _refresh_dash(self):
        def _fetch():
            gh = get_gh_store()
            try: t = len(gh.get_teachers()) if gh else 0
            except: t = 0
            try: s = len(gh.get_students()) if gh else 0
            except: s = 0
            try: g = len(gh.get_groups()) if gh else 0
            except: g = 0
            try: subj = len(load_subjects())
            except: subj = 0
            return t, s, g, subj

        def _apply(counts):
            t, s, g, subj = counts
            while self._dash_stats.count():
                it = self._dash_stats.takeAt(0)
                if it.widget(): it.widget().deleteLater()
            for label, val, color in [
                ("Преподавателей", str(t),    "green"),
                ("Студентов",      str(s),    "blue"),
                ("Групп",          str(g),    "text"),
                ("Предметов",      str(subj), "text"),
            ]:
                self._dash_stats.addWidget(stat_card(label, val, color))

        self._run_bg(_fetch, _apply)

    # Преподаватели

    def _build_teachers(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(12)
        hdr = QHBoxLayout(); hdr.addWidget(title_lbl("Преподаватели"), 1)
        for txt, cb in [
            ("+ Добавить",  self._add_teacher),
            ("💾 Экспорт",  self._export_teachers),
            ("📥 Импорт",   self._import_teachers),
        ]:
            b = btn(txt, "ghost" if txt != "+ Добавить" else "green")
            b.clicked.connect(cb); hdr.addWidget(b)
        lay.addLayout(hdr)
        self._t_search = field_input("Поиск...")
        self._t_search.textChanged.connect(self._render_teachers)
        lay.addWidget(self._t_search)
        self._t_list = QListWidget()
        self._t_list.itemDoubleClicked.connect(lambda it: self._open_teacher(it.data(Qt.UserRole)))
        lay.addWidget(self._t_list, 1)
        self.pages["teachers"] = w; self.stack.addWidget(w)

    def _render_teachers(self):
        q = self._t_search.text().lower()
        def _fetch():
            gh = get_gh_store()
            return gh.get_teachers() if gh else {}
        def _apply(teachers):
            self._t_list.clear()
            for name, data in teachers.items():
                if q and q not in name.lower(): continue
                has_pw = "✅" if (data.get("password_hash") or data.get("password")) else "❌"
                it = QListWidgetItem(f"{has_pw}  {name}"); it.setData(Qt.UserRole, name)
                self._t_list.addItem(it)
        self._run_bg(_fetch, _apply)

    def _open_teacher(self, name):
        gh = get_gh_store()
        teachers = gh.get_teachers() if gh else {}
        data = teachers.get(name, {})
        d = QDialog(self); d.setWindowTitle(f"Преподаватель: {name}"); d.resize(420, 520)
        lay = QVBoxLayout(d); lay.setSpacing(12); lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(title_lbl(name, 18))
        nm_edit  = field_input(name); nm_edit.setText(name)
        lg_edit  = field_input(); lg_edit.setText(data.get("login", ""))
        pw_edit  = field_input("Новый пароль", password=True)
        subj_lw  = _subject_picker(d, data.get("subjects", []))
        for lb, w in [("ФИО", nm_edit), ("Логин", lg_edit), ("Новый пароль", pw_edit), ("Предметы", subj_lw)]:
            lay.addWidget(lbl(lb.upper(), 10, C['text3'])); lay.addWidget(w)
        btns  = QHBoxLayout()
        del_b = btn("🗑 Удалить", "red")
        def _del():
            gh = get_gh_store()
            ts = gh.get_teachers() if gh else {}
            ts.pop(name, None)
            if gh: gh.set_teachers(ts)
            d.accept(); self._render_teachers()
        del_b.clicked.connect(_del)
        save_b = btn("Сохранить", "green")
        def _save():
            gh       = get_gh_store()
            ts       = gh.get_teachers() if gh else {}
            new_name = nm_edit.text().strip()
            nd       = dict(ts.get(name, {}))
            pw       = pw_edit.text().strip()
            nd["login"] = lg_edit.text().strip()
            if pw: nd["password"] = pw
            nd["subjects"] = _get_checked(subj_lw)
            if new_name != name: ts.pop(name, None)
            ts[new_name] = nd
            if gh: gh.set_teachers(ts)
            d.accept(); self._render_teachers()
        save_b.clicked.connect(_save)
        btns.addWidget(del_b); btns.addStretch()
        btns.addWidget(btn("Отмена", "ghost")); btns.addWidget(save_b)
        lay.addLayout(btns); d.exec()

    def _add_teacher(self):
        d = QDialog(self); d.setWindowTitle("Новый преподаватель"); d.resize(420, 480)
        lay = QVBoxLayout(d); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(10)
        lay.addWidget(title_lbl("Добавить преподавателя", 18))
        nm = field_input("Фамилия Имя Отчество")
        lg = field_input("login")
        pw = field_input("Пароль", password=True)
        sj = _subject_picker(d, [])
        for lb, w in [("ФИО", nm), ("Логин", lg), ("Пароль", pw), ("Предметы", sj)]:
            lay.addWidget(lbl(lb.upper(), 10, C['text3'])); lay.addWidget(w)
        btns   = QHBoxLayout()
        save   = btn("Добавить", "green")
        cancel = btn("Отмена",   "ghost")
        cancel.clicked.connect(d.reject); btns.addWidget(cancel); btns.addWidget(save)
        def _add():
            n = nm.text().strip(); p = pw.text().strip()
            if not n: QMessageBox.warning(d, "Ошибка", "Введите ФИО"); return
            gh = get_gh_store()
            ts = gh.get_teachers() if gh else {}
            if not lg.text().strip():
                QMessageBox.warning(d, "Ошибка", "Введите логин"); return
            ts[n] = {
                "login": lg.text().strip(),
                "password": p,
                "subjects": _get_checked(sj),
                "group_assignments": {},
            }
            if gh: gh.set_teachers(ts)
            d.accept(); self._render_teachers(); self._refresh_dash()
        save.clicked.connect(_add); lay.addLayout(btns); d.exec()

    def _export_teachers(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт преподавателей", "teachers.json", "JSON (*.json)")
        if not path: return
        gh = get_gh_store()
        ts = gh.get_teachers() if gh else {}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ts, f, ensure_ascii=False, indent=2)
        # Аудит: экспорт персональных данных — значимое событие (152-ФЗ).
        log_event("export_personal_data", "admin", f"teachers={len(ts)}")
        QMessageBox.information(self, "Готово", f"Экспортировано {len(ts)} преподавателей")

    def _import_teachers(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт", "", "JSON (*.json)")
        if not path: return
        try:
            with open(path, encoding="utf-8") as f: new_t = json.load(f)
            if not isinstance(new_t, dict):
                QMessageBox.warning(self, "Ошибка", "Неверный формат"); return
            gh = get_gh_store()
            cur   = gh.get_teachers() if gh else {}
            added = [n for n in new_t if n not in cur]
            for n in added: cur[n] = new_t[n]
            if gh: gh.set_teachers(cur)
            self._render_teachers(); self._refresh_dash()
            QMessageBox.information(self, "Готово", f"Добавлено: {len(added)}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    # Студенты 

    def _build_students(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(12)
        hdr = QHBoxLayout(); hdr.addWidget(title_lbl("Студенты"), 1)
        for txt, cb in [
            ("+ Добавить",  self._add_student_admin),
            ("💾 Экспорт",  self._export_students),
            ("📥 Импорт",   self._import_students),
        ]:
            b = btn(txt, "ghost" if txt != "+ Добавить" else "green")
            b.clicked.connect(cb); hdr.addWidget(b)
        lay.addLayout(hdr)
        fltr = QHBoxLayout()
        self._s_search = field_input("Поиск..."); self._s_search.textChanged.connect(self._render_students)
        gh = get_gh_store()
        self._s_grp_filter = combo(
            ["Все группы"] + [g["name"] for g in (gh.get_groups() if gh else [])]
        )
        self._s_grp_filter.currentTextChanged.connect(self._render_students)
        fltr.addWidget(self._s_search, 1); fltr.addWidget(self._s_grp_filter)
        lay.addLayout(fltr)
        self._s_list = QListWidget()
        self._s_list.itemDoubleClicked.connect(lambda it: self._open_student(it.data(Qt.UserRole)))
        lay.addWidget(self._s_list, 1)
        self.pages["students"] = w; self.stack.addWidget(w)

    def _render_students(self):
        q   = self._s_search.text().lower()
        grp = self._s_grp_filter.currentText()
        def _fetch():
            gh = get_gh_store()
            return gh.get_students() if gh else []
        def _apply(students):
            self._s_list.clear()
            for i, s in enumerate(students):
                name = f"{s.get('surname', '')} {s.get('name', '')}".strip()
                if q and q not in name.lower(): continue
                if grp != "Все группы" and s.get("group", "") != grp: continue
                has_pw = "✅" if (s.get("password_hash") or s.get("password")) else "❌"
                it = QListWidgetItem(f"{has_pw}  {name}  [{s.get('group', '—')}]")
                it.setData(Qt.UserRole, i); self._s_list.addItem(it)
        self._run_bg(_fetch, _apply)

    def _open_student(self, idx):
        gh = get_gh_store()
        students = gh.get_students() if gh else []
        if idx >= len(students): return
        s = students[idx]
        d = QDialog(self); d.setWindowTitle("Студент"); d.resize(400, 350)
        lay = QVBoxLayout(d); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(10)
        lay.addWidget(title_lbl(f"{s.get('surname', '')} {s.get('name', '')}", 18))
        sn = field_input(); sn.setText(s.get("surname", ""))
        nm = field_input(); nm.setText(s.get("name", ""))
        grp = field_input(); grp.setText(s.get("group", ""))
        lg = field_input(); lg.setText(s.get("login", ""))
        pw = field_input("Новый пароль", password=True)
        for lb, w in [("Фамилия", sn), ("Имя", nm), ("Группа", grp), ("Логин", lg), ("Новый пароль", pw)]:
            lay.addWidget(lbl(lb.upper(), 10, C['text3'])); lay.addWidget(w)
        btns  = QHBoxLayout()
        del_b = btn("🗑 Удалить", "red")
        def _del():
            if QMessageBox.question(d, "Удалить?", "Удалить студента?",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
            sts = gh.get_students() if gh else []
            del sts[idx]
            if gh: gh.set_students(sts)
            d.accept(); self._render_students(); self._refresh_dash()
        del_b.clicked.connect(_del)
        save_b = btn("Сохранить", "green")
        def _save():
            sts = gh.get_students() if gh else []
            p   = pw.text().strip()
            nd  = {"surname": sn.text().strip(), "name": nm.text().strip(), "group": grp.text().strip(),
                   "login": lg.text().strip()}
            old = sts[idx]
            if old.get("password_hash") and not p:
                nd["password_hash"] = old["password_hash"]
            if p: nd["password"] = p
            sts[idx] = nd
            if gh: gh.set_students(sts)
            d.accept(); self._render_students()
        save_b.clicked.connect(_save)
        btns.addWidget(del_b); btns.addStretch()
        btns.addWidget(btn("Отмена", "ghost")); btns.addWidget(save_b)
        lay.addLayout(btns); d.exec()

    def _add_student_admin(self):
        d = QDialog(self); d.setWindowTitle("Новый студент"); d.resize(380, 300)
        lay = QVBoxLayout(d); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(10)
        lay.addWidget(title_lbl("Добавить студента", 18))
        sn = field_input("Иванов"); nm = field_input("Иван")
        grp = field_input("ИС-21"); pw = field_input("Пароль", password=True)
        lg = field_input("ivanov")
        for lb, w in [("Фамилия", sn), ("Имя", nm), ("Группа", grp), ("Логин", lg), ("Пароль", pw)]:
            lay.addWidget(lbl(lb.upper(), 10, C['text3'])); lay.addWidget(w)
        btns   = QHBoxLayout()
        save   = btn("Добавить", "green")
        cancel = btn("Отмена",   "ghost")
        cancel.clicked.connect(d.reject); btns.addWidget(cancel); btns.addWidget(save)
        def _add():
            s = sn.text().strip(); n = nm.text().strip()
            if not s or not n:
                QMessageBox.warning(d, "Ошибка", "Введите фамилию и имя"); return
            gh = get_gh_store()
            sts = gh.get_students() if gh else []
            if not lg.text().strip():
                QMessageBox.warning(d, "Ошибка", "Введите логин"); return
            sts.append({"surname": s, "name": n, "group": grp.text().strip(),
                        "login": lg.text().strip(), "password": pw.text().strip()})
            if gh: gh.set_students(sts)
            d.accept(); self._render_students(); self._refresh_dash()
        save.clicked.connect(_add); lay.addLayout(btns); d.exec()

    def _export_students(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", "students.json", "JSON (*.json)")
        if not path: return
        gh = get_gh_store()
        sts = gh.get_students() if gh else []
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sts, f, ensure_ascii=False, indent=2)
        # Аудит: экспорт персональных данных — значимое событие (152-ФЗ).
        log_event("export_personal_data", "admin", f"students={len(sts)}")
        QMessageBox.information(self, "Готово", f"Экспортировано {len(sts)}")

    def _import_students(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт", "", "JSON (*.json)")
        if not path: return
        try:
            with open(path, encoding="utf-8") as f: new_s = json.load(f)
            if not isinstance(new_s, list):
                QMessageBox.warning(self, "Ошибка", "Неверный формат"); return
            gh = get_gh_store()
            cur   = gh.get_students() if gh else []
            added = [s for s in new_s
                     if not any(x.get("surname") == s.get("surname")
                                and x.get("name") == s.get("name") for x in cur)]
            cur.extend(added)
            if gh: gh.set_students(cur)
            self._render_students(); self._refresh_dash()
            QMessageBox.information(self, "Готово", f"Добавлено: {len(added)}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    # Группы 

    def _build_groups(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(12)
        hdr = QHBoxLayout(); hdr.addWidget(title_lbl("Группы"), 1)
        add_b = btn("+ Добавить группу", "green"); add_b.clicked.connect(self._add_group)
        hdr.addWidget(add_b); lay.addLayout(hdr)
        self._g_table = QTableWidget(); self._g_table.setColumnCount(3)
        self._g_table.setHorizontalHeaderLabels(["Название", "Предметы", ""])
        self._g_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._g_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._g_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._g_table.setColumnWidth(2, 60)
        self._g_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self._g_table, 1)
        self.pages["groups"] = w; self.stack.addWidget(w)

    def _render_groups(self):
        def _fetch():
            gh = get_gh_store()
            return gh.get_groups() if gh else []
        def _apply(groups):
            self._g_table.setRowCount(len(groups))
            for r, g in enumerate(groups):
                self._g_table.setItem(r, 0, QTableWidgetItem(g["name"]))
                subj_str = ", ".join(g.get("subjects", [])[:4])
                if len(g.get("subjects", [])) > 4: subj_str += "…"
                self._g_table.setItem(r, 1, QTableWidgetItem(subj_str))
                del_b = QPushButton("✕"); del_b.setStyleSheet(BTN["sm_red"])
                del_b.clicked.connect(lambda _, n=g["name"]: self._del_group(n))
                self._g_table.setCellWidget(r, 2, del_b)
        self._run_bg(_fetch, _apply)

    def _add_group(self):
        d = QDialog(self); d.setWindowTitle("Новая группа"); d.resize(420, 480)
        lay = QVBoxLayout(d); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(10)
        lay.addWidget(title_lbl("Добавить группу", 18))
        nm = field_input("ИС-21")
        sj = _subject_picker(d, [])
        for lb, w in [("Название группы", nm), ("Предметы", sj)]:
            lay.addWidget(lbl(lb.upper(), 10, C['text3'])); lay.addWidget(w)
        btns   = QHBoxLayout()
        save   = btn("Создать", "green")
        cancel = btn("Отмена",  "ghost")
        cancel.clicked.connect(d.reject); btns.addWidget(cancel); btns.addWidget(save)
        def _add():
            n = nm.text().strip()
            if not n: QMessageBox.warning(d, "Ошибка", "Введите название"); return
            _gh = get_gh_store()
            gs = _gh.get_groups() if _gh else []
            if any(g["name"] == n for g in gs):
                QMessageBox.warning(d, "Ошибка", "Группа уже есть"); return
            gs.append({"name": n, "subjects": _get_checked(sj)})
            if _gh: _gh.set_groups(gs)
            d.accept(); self._render_groups(); self._refresh_dash()
        save.clicked.connect(_add); lay.addLayout(btns); d.exec()

    def _del_group(self, name):
        if QMessageBox.question(self, "Удалить?", f"Удалить группу {name}?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        _gh = get_gh_store()
        gs = [g for g in (_gh.get_groups() if _gh else []) if g["name"] != name]
        if _gh: _gh.set_groups(gs)
        self._render_groups(); self._refresh_dash()

    # Предметы

    def _build_subjects(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(12)
        hdr = QHBoxLayout(); hdr.addWidget(title_lbl("Предметы"), 1)
        add_b = btn("+ Добавить", "green"); add_b.clicked.connect(self._add_subject)
        hdr.addWidget(add_b); lay.addLayout(hdr)
        self._subj_search = field_input("Поиск предмета...")
        self._subj_search.textChanged.connect(self._render_subjects)
        lay.addWidget(self._subj_search)
        self._subj_list = QListWidget(); lay.addWidget(self._subj_list, 1)
        btn_row = QHBoxLayout()
        del_b = btn("Удалить выбранные", "red"); del_b.clicked.connect(self._del_selected_subjects)
        btn_row.addWidget(del_b); btn_row.addStretch()
        lay.addLayout(btn_row)
        self.pages["subjects"] = w; self.stack.addWidget(w)

    def _render_subjects(self):
        q = self._subj_search.text().lower()
        subjects = load_subjects()
        self._subj_list.clear()
        for s in subjects:
            if q and q not in s.lower(): continue
            self._subj_list.addItem(QListWidgetItem(s))

    def _add_subject(self):
        from subjects import add_subject
        nm, ok = QInputDialog.getText(self, "Новый предмет", "Название предмета:")
        if ok and nm.strip():
            add_subject(nm.strip()); self._render_subjects()

    def _del_selected_subjects(self):
        from subjects import delete_subject
        items = self._subj_list.selectedItems()
        if not items: return
        if QMessageBox.question(self, "Удалить?", f"Удалить {len(items)} предметов?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        for it in items: delete_subject(it.text())
        self._render_subjects()

    # API ключ

    def _build_api(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("API Ключ OpenRouter"))
        c = card(); cl = QVBoxLayout(c); cl.setContentsMargins(20, 18, 20, 18); cl.setSpacing(10)
        cl.addWidget(section_lbl("🔑 OpenRouter AI"))
        self._api_status = lbl("", 12); cl.addWidget(self._api_status)
        cl.addWidget(lbl("ВВЕДИТЕ НОВЫЙ КЛЮЧ", 10, C['text3']))
        self._api_inp = field_input("sk-or-v1-...", password=True); cl.addWidget(self._api_inp)
        btn_row = QHBoxLayout()
        save_b = btn("💾 Сохранить", "green"); del_b = btn("🗑 Удалить", "red")
        save_b.clicked.connect(self._save_api); del_b.clicked.connect(self._del_api)
        btn_row.addWidget(save_b); btn_row.addWidget(del_b); btn_row.addStretch()
        cl.addLayout(btn_row)
        lay.addWidget(c)

        # ── Карточка: ИИ-помощник «Вектор» (офлайн / GigaChat / ollama) ──
        from PySide6.QtWidgets import QComboBox as _QC, QCheckBox as _QCB
        vc = card(); vl = QVBoxLayout(vc); vl.setContentsMargins(20, 18, 20, 18); vl.setSpacing(10)
        vl.addWidget(section_lbl("🐯 ИИ-помощник «Вектор»"))
        vl.addWidget(lbl("Кто озвучивает ответы Вектора", 11, C['text3']))

        self._vec_provider = _QC()
        self._vec_provider.addItem("Офлайн — без интернета, точно, суховато", "offline")
        self._vec_provider.addItem("GigaChat — живой тон, РФ-серверы (152-ФЗ)", "gigachat")
        self._vec_provider.addItem("Локальная модель ollama — живой тон, без сети", "local")
        self._vec_provider.currentIndexChanged.connect(self._toggle_vec_blocks)
        vl.addWidget(self._vec_provider)

        # — GigaChat —
        self._vec_giga_box = QWidget(); gbl = QVBoxLayout(self._vec_giga_box)
        gbl.setContentsMargins(0, 0, 0, 0); gbl.setSpacing(6)
        gbl.addWidget(lbl("Ключ авторизации GigaChat", 10, C['text3']))
        self._vec_giga_key = field_input("Authorization key из личного кабинета", password=True)
        gbl.addWidget(self._vec_giga_key)
        show = _QCB("Показать ключ")
        show.toggled.connect(lambda on: self._vec_giga_key.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        gbl.addWidget(show)
        gbl.addWidget(lbl("SCOPE", 10, C['text3']))
        self._vec_giga_scope = _QC()
        self._vec_giga_scope.addItem("GIGACHAT_API_PERS — физлицо (для теста)", "GIGACHAT_API_PERS")
        self._vec_giga_scope.addItem("GIGACHAT_API_B2B — юрлицо (для продажи)", "GIGACHAT_API_B2B")
        self._vec_giga_scope.addItem("GIGACHAT_API_CORP — корпоративный", "GIGACHAT_API_CORP")
        gbl.addWidget(self._vec_giga_scope)
        test_b = btn("Проверить ключ", "blue"); test_b.clicked.connect(self._test_giga)
        gbl.addWidget(test_b)
        self._vec_giga_status = lbl("", 12); self._vec_giga_status.setWordWrap(True)
        gbl.addWidget(self._vec_giga_status)
        gbl.addWidget(lbl("Персональный ключ обычно требует SCOPE = GIGACHAT_API_PERS. "
                          "Нужен пакет: pip install gigachat", 10, C['text3']))
        vl.addWidget(self._vec_giga_box)

        # — ollama —
        self._vec_local_box = QWidget(); lbx = QVBoxLayout(self._vec_local_box)
        lbx.setContentsMargins(0, 0, 0, 0); lbx.setSpacing(6)
        lbx.addWidget(lbl("Модель ollama", 10, C['text3']))
        self._vec_local_model = field_input("qwen2.5:3b")
        lbx.addWidget(self._vec_local_model)
        lbx.addWidget(lbl("Нужен запущенный ollama на http://localhost:11434. "
                          "Данные наружу не уходят вообще.", 10, C['text3']))
        vl.addWidget(self._vec_local_box)

        vsave = btn("💾 Сохранить настройки Вектора", "green")
        vsave.clicked.connect(self._save_vector_cfg)
        vrow = QHBoxLayout(); vrow.addWidget(vsave); vrow.addStretch()
        vl.addLayout(vrow)
        lay.addWidget(vc)

        lay.addStretch()
        self.pages["api"] = w; self.stack.addWidget(w)
        self._refresh_api()
        self._refresh_vector_cfg()

    def _refresh_api(self):
        def _fetch():
            gh = get_gh_store()
            if not gh: return None
            try: return gh.get_api_key()
            except: return None

        def _apply(k):
            gh = get_gh_store()
            if not gh:
                self._api_status.setText("❌ Ключ не задан")
                self._api_status.setStyleSheet(f"font-size:12px;color:{C['red']};")
                return
            if k:
                masked = k[:8] + "..." + k[-4:] if len(k) > 12 else "***"
                self._api_status.setText(f"✅ Ключ установлен: {masked}")
                self._api_status.setStyleSheet(f"font-size:12px;color:{C['green']};")
                self._api_inp.setText(k)
            else:
                self._api_status.setText("❌ Ключ не установлен — ИИ не будет работать")
                self._api_status.setStyleSheet(f"font-size:12px;color:{C['red']};")
                self._api_inp.clear()

        self._run_bg(_fetch, _apply)

    def _save_api(self):
        k = self._api_inp.text().strip()
        if not k: 
            QMessageBox.warning(self, "Ошибка", "Введите ключ")
            return
        gh = get_gh_store()
        if not gh:
            QMessageBox.critical(self, "Ошибка", "Хранилище недоступно")
            return
        if gh.set_api_key(k):
            self._refresh_api()
            QMessageBox.information(self, "Сохранено", "API ключ сохранён.")
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить ключ")

    def _del_api(self):
        if QMessageBox.question(self, "Удалить?", "Удалить API ключ?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: 
            return
        gh = get_gh_store()
        if gh:
            if gh.set_api_key(""):
                self._refresh_api()
                QMessageBox.information(self, "Удалено", "API ключ удалён.")
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось удалить ключ")

    # ── ИИ-помощник «Вектор»: провайдер озвучки ──────────────
    def _vec_cfg(self) -> dict:
        try:
            return dict(get_gh_store()._config() or {})
        except Exception:
            return {}

    def _toggle_vec_blocks(self, *_):
        kind = self._vec_provider.currentData()
        self._vec_giga_box.setVisible(kind == "gigachat")
        self._vec_local_box.setVisible(kind == "local")

    def _refresh_vector_cfg(self):
        cfg = self._vec_cfg()
        i = self._vec_provider.findData(cfg.get("vector_llm", "offline"))
        self._vec_provider.setCurrentIndex(max(0, i))
        self._vec_giga_key.setText(cfg.get("gigachat_credentials", ""))
        si = self._vec_giga_scope.findData(cfg.get("gigachat_scope", "GIGACHAT_API_PERS"))
        self._vec_giga_scope.setCurrentIndex(max(0, si))
        self._vec_local_model.setText(cfg.get("local_model", "qwen2.5:3b"))
        self._toggle_vec_blocks()

    def _save_vector_cfg(self):
        try:
            from data_store import _kv_set
            cfg = self._vec_cfg()
            cfg.update({
                "vector_llm": self._vec_provider.currentData(),
                "gigachat_credentials": self._vec_giga_key.text().strip(),
                "gigachat_scope": self._vec_giga_scope.currentData(),
                "local_model": self._vec_local_model.text().strip() or "qwen2.5:3b",
            })
            _kv_set("config", cfg)
            QMessageBox.information(
                self, "Сохранено",
                "Настройки Вектора сохранены. Они применятся при следующем "
                "открытии журнала или панели Вектора.")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить: {e}")

    def _test_giga(self):
        creds = self._vec_giga_key.text().strip()
        scope = self._vec_giga_scope.currentData()
        if not creds:
            self._vec_giga_status.setText("Введите ключ.")
            return
        self._vec_giga_status.setText("Проверяю…")
        self._vec_giga_status.setStyleSheet(f"font-size:12px;color:{C['text3']};")

        def _check():
            from gigachat import GigaChat
            with GigaChat(credentials=creds, scope=scope, verify_ssl_certs=False,
                          timeout=20.0) as g:
                g.get_token()
            return True

        def _ok(_):
            self._vec_giga_status.setText("✓ Ключ принят, соединение установлено.")
            self._vec_giga_status.setStyleSheet(f"font-size:12px;color:{C['green']};")

        def _err(e):
            try:
                from vector.llm import explain_giga_error
                hint = explain_giga_error(e)
            except Exception:
                hint = str(e)
            self._vec_giga_status.setText("✗ " + hint)
            self._vec_giga_status.setStyleSheet("font-size:12px;color:#b9772b;")

        self._run_bg(_check, _ok, _err)

    # База данных

    # База данных (PostgreSQL — сервер колледжа)

    def _build_pg(self):
        from db_config import load_pg_config, get_install_key
        w = QScrollArea(); w.setWidgetResizable(True); w.setStyleSheet("border:none;")
        inner = QWidget(); lay = QVBoxLayout(inner); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("База данных"))

        # ── Карточка: сервер синхронизации (API) — основной способ ────────
        from app_settings import get_api_url
        ac = card(); al = QVBoxLayout(ac); al.setContentsMargins(18, 16, 18, 16); al.setSpacing(10)
        al.addWidget(section_lbl("🌐 Сервер синхронизации (рекомендуется)"))
        al.addWidget(lbl("Адрес сервера колледжа. Прописывается один раз на ПК; "
                         "учителя и студенты просто входят, данные подтягиваются сами.",
                         11, C['text3']))
        self._api_url = field_input("http://10.0.0.5:8000"); self._api_url.setText(get_api_url())
        al.addWidget(self._api_url)
        arow = QHBoxLayout()
        asave = btn("💾 Сохранить адрес", "green"); asave.clicked.connect(self._save_api_url)
        arow.addWidget(asave); arow.addStretch(); al.addLayout(arow)
        lay.addWidget(ac)

        cfg = load_pg_config()
        gc = card(); gl = QVBoxLayout(gc); gl.setContentsMargins(18, 16, 18, 16); gl.setSpacing(10)
        gl.addWidget(section_lbl("🐘 PostgreSQL (сервер колледжа)"))
        self._pg_status = lbl("Проверка...", 12, C['text3']); gl.addWidget(self._pg_status)

        self._pg_host = field_input("192.168.1.100");      self._pg_host.setText(str(cfg.get("host", "")))
        self._pg_port = field_input("5432");                self._pg_port.setText(str(cfg.get("port", 5432)))
        self._pg_db   = field_input("vsgutu_grades");       self._pg_db.setText(str(cfg.get("database", "vsgutu_grades")))
        self._pg_user = field_input("vsgutu_user");         self._pg_user.setText(str(cfg.get("user", "")))
        self._pg_pass = field_input("пароль БД", password=True); self._pg_pass.setText(str(cfg.get("password", "")))
        for lab, wdg in [("СЕРВЕР (IP)", self._pg_host), ("ПОРТ", self._pg_port),
                         ("БАЗА ДАННЫХ", self._pg_db), ("ПОЛЬЗОВАТЕЛЬ", self._pg_user),
                         ("ПАРОЛЬ БД", self._pg_pass)]:
            gl.addWidget(lbl(lab, 10, C['text3'])); gl.addWidget(wdg)

        row = QHBoxLayout()
        save_b = btn("💾 Сохранить и подключить", "green")
        test_b = btn("🔌 Проверить", "ghost")
        save_b.clicked.connect(self._save_pg)
        test_b.clicked.connect(self._test_pg)
        row.addWidget(save_b); row.addWidget(test_b); row.addStretch()
        gl.addLayout(row)

        info = lbl(f"Ключ этого ПК: {get_install_key()}\n\n"
                   "PostgreSQL ставится на один сервер/ПК в колледже — остальные ПК "
                   "подключаются к нему по локальной сети. Данные не уходят в интернет. "
                   "Если PostgreSQL не настроен, программа работает на локальном SQLite.",
                   10, C['text3'])
        info.setWordWrap(True)
        info.setStyleSheet(f"background:{C['green_glow']};border:1px solid {C['border']};border-radius:8px;padding:10px;")
        gl.addWidget(info)
        lay.addWidget(gc)

        # ── Карточка: смена пароля администратора ──────────────────
        sc = card(); sl = QVBoxLayout(sc); sl.setContentsMargins(18, 16, 18, 16); sl.setSpacing(10)
        sl.addWidget(section_lbl("🔐 Пароль администратора"))
        self._adm_old = field_input("Текущий пароль", password=True)
        self._adm_new = field_input("Новый пароль (мин. 8 символов)", password=True)
        self._adm_new2 = field_input("Повтор нового пароля", password=True)
        for lab, wdg in [("ТЕКУЩИЙ ПАРОЛЬ", self._adm_old),
                         ("НОВЫЙ ПАРОЛЬ", self._adm_new),
                         ("ПОВТОР", self._adm_new2)]:
            sl.addWidget(lbl(lab, 10, C['text3'])); sl.addWidget(wdg)
        chg = btn("💾 Сменить пароль", "green"); chg.clicked.connect(self._change_admin_pw)
        srow = QHBoxLayout(); srow.addWidget(chg); srow.addStretch(); sl.addLayout(srow)
        lay.addWidget(sc)

        lay.addStretch()
        w.setWidget(inner)
        self.pages["pg"] = w; self.stack.addWidget(w)

    def _save_api_url(self):
        from app_settings import set_api_url
        url = self._api_url.text().strip()
        if set_api_url(url):
            QMessageBox.information(
                self, "Сохранено",
                "Адрес сервера сохранён.\n\nПерезапустите программу, чтобы включить "
                "синхронизацию. Если поле пустое — программа работает только локально.")
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить адрес сервера")

    def _change_admin_pw(self):
        """Смена пароля администратора. Меняется в общем конфиге → синхронизируется
        на все ПК через PostgreSQL."""
        gh = get_gh_store()
        if not gh:
            QMessageBox.critical(self, "Ошибка", "Хранилище недоступно"); return
        old = self._adm_old.text()
        new = self._adm_new.text()
        new2 = self._adm_new2.text()
        if not gh.check_admin_password(old):
            QMessageBox.warning(self, "Ошибка", "Текущий пароль неверен"); return
        if len(new) < 8:
            QMessageBox.warning(self, "Ошибка", "Новый пароль должен быть не короче 8 символов"); return
        if new != new2:
            QMessageBox.warning(self, "Ошибка", "Новый пароль и повтор не совпадают"); return
        if gh.set_admin_password(new):
            log_event("admin_password_changed", "admin")
            self._adm_old.clear(); self._adm_new.clear(); self._adm_new2.clear()
            QMessageBox.information(self, "Готово", "Пароль администратора изменён.")
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить новый пароль")

    def _refresh_pg(self):
        def _fetch():
            from data_store import get_store
            try: return get_store().test_connection()
            except Exception as e: return False, str(e)
        def _apply(result):
            ok, msg = result
            self._pg_status.setText((("✅ " if ok else "⚠️ ") + str(msg))[:70])
            self._pg_status.setStyleSheet(f"font-size:12px;color:{C['green'] if ok else C['red']};")
        self._run_bg(_fetch, _apply)

    def _collect_pg_cfg(self):
        try: port = int(self._pg_port.text().strip() or "5432")
        except ValueError: port = 5432
        return {
            "host": self._pg_host.text().strip(),
            "port": port,
            "database": self._pg_db.text().strip() or "vsgutu_grades",
            "user": self._pg_user.text().strip(),
            "password": self._pg_pass.text(),
        }

    def _test_pg(self):
        from db_config import test_connection
        cfg = self._collect_pg_cfg()
        if not cfg["host"] or not cfg["user"]:
            QMessageBox.warning(self, "Ошибка", "Укажите адрес сервера и пользователя"); return
        ok, msg = test_connection(cfg)
        if ok: QMessageBox.information(self, "✅ Подключение есть", str(msg)[:300])
        else:  QMessageBox.critical(self, "❌ Не удалось подключиться", str(msg)[:400])

    def _save_pg(self):
        from db_config import save_pg_config, test_connection, get_install_key
        cfg = self._collect_pg_cfg()
        if not cfg["host"] or not cfg["user"]:
            QMessageBox.warning(self, "Ошибка", "Укажите адрес сервера и пользователя"); return
        ok, msg = test_connection(cfg)
        if not ok:
            QMessageBox.critical(self, "❌ Ошибка подключения", str(msg)[:400]); return
        cfg["install_key"] = get_install_key()
        if save_pg_config(cfg):
            QMessageBox.information(self, "Сохранено",
                "Настройки PostgreSQL сохранены.\n\nПерезапустите программу, чтобы все ПК "
                "работали с общей базой колледжа.")
            self._refresh_pg()
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить настройки")

    # ИИ

    def _build_ai(self):
        """Вкладка «ИИ Помощник» — теперь Вектор (вместо облачного чата)."""
        try:
            from vector import VectorEngine, VectorScope, get_provider
            from vector.widget import VectorPanel
            try:
                from data_store import get_store
                _cfg = get_store()._config()
            except Exception:
                _cfg = {}
            self.vector_engine = VectorEngine(VectorScope(role="admin"), get_provider(_cfg))
            ai = VectorPanel(self.vector_engine, docked=False)
        except Exception as _e:
            print(f"[Vector] вкладка не собралась (админ): {_e}")
            ai = AIWidget(
                role="admin",
                context_fn=self._admin_context,
                back_fn=lambda: self.pages.get("dash"),
                stack_ref=self.stack
            )
        self.pages["ai"] = ai; self.stack.addWidget(ai)

    def _admin_context(self):
        gh = get_gh_store()
        try: t = len(gh.get_teachers()) if gh else 0
        except: t = 0
        try: s = len(gh.get_students()) if gh else 0
        except: s = 0
        try: g = len(gh.get_groups()) if gh else 0
        except: g = 0
        return (
            f"Ты ИИ-ассистент системы ВСГУТУ для администратора.\n"
            f"Преподавателей: {t}, Студентов: {s}, Групп: {g}.\n"
            "Отвечай только на русском, кратко и по делу."
        )

    #Роутинг

    def _switch(self, key):
        if getattr(self, '_switching', False):
            return
        self._switching = True
        try:
            if key == "dash":     self._refresh_dash()
            if key == "teachers": self._render_teachers()
            if key == "students": self._refresh_students_combo(); self._render_students()
            if key == "groups":   self._render_groups()
            if key == "subjects": self._render_subjects()
            if key == "api":      self._refresh_api()
            if key == "pg":       self._refresh_pg()
            if key in self.pages:
                self.stack.setCurrentWidget(self.pages[key])
                self.sidebar.set_active(key)
        finally:
            self._switching = False

    def _refresh_students_combo(self):
        """Обновить список групп в фильтре студентов (фоновая загрузка)."""
        def _fetch():
            gh = get_gh_store()
            return ["Все группы"] + [g["name"] for g in (gh.get_groups() if gh else [])]
        def _apply(groups):
            current = self._s_grp_filter.currentText()
            self._s_grp_filter.blockSignals(True)
            self._s_grp_filter.clear()
            self._s_grp_filter.addItems(groups)
            idx = self._s_grp_filter.findText(current)
            self._s_grp_filter.setCurrentIndex(max(idx, 0))
            self._s_grp_filter.blockSignals(False)
        self._run_bg(_fetch, _apply)
