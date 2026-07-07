"""
admin_dashboard.py — AdminDashboard
Часть рефакторинга GUI.py → модульная архитектура
"""

import json
import os

from PySide6.QtCore import Qt, QTimer
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
    separator, stat_card, vector_unavailable_widget
)
from ui_components import Sidebar

from PySide6.QtCore import QThread, Signal as QSignal

from core import DBManager
from subjects import load_subjects
from data_store import get_store
from audit import log_event, read_events


#Фоновый воркер для сетевых/долгих запросов
class _BgWorker(QThread):
    """Выполняет fn() в фоновом потоке, возвращает результат через сигнал."""
    done  = QSignal(object)   #успех — данные
    error = QSignal(str)      #ошибка

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
        self._workers = []   #держим ссылки чтобы GC не убил потоки
        self._build()

    def _build(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        items = [
            ("__label__", "", "Управление"),
            ("dash",     "home",         "Дашборд"),
            ("teachers", "presentation", "Преподаватели"),
            ("students", "users",        "Студенты"),
            ("groups",   "school",       "Группы"),
            ("subjects", "book",         "Предметы"),
            ("schedule", "calendar",     "Расписание"),
            ("__label__", "", "Система"),
            ("api",   "cpu",      "Настройки ИИ"),
            ("pg",    "globe",    "Сервер"),
            ("reg",   "clipboard", "Запросы на регистрацию"),
            ("requests", "link",  "Запросы на подключение"),
            ("sessions", "shield", "Сессии и доступ"),
            ("theme", "palette",  "Оформление"),
            ("mon",   "activity", "Мониторинг"),
            ("ai",    "bot",      "ИИ Помощник"),
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
        self._build_schedule()
        self._build_api()
        self._build_pg()
        self._build_registrations()
        self._build_requests()
        self._build_sessions()
        self._build_theme()
        self._build_mon()
        self._build_ai()
        self.sidebar.set_active("dash")

        #Вектор постоянно слева (⇄ — вправо, — свернуть/вернуть 🐯)
        try:
            from vector.widget import VectorPanel, VectorHost
            self._ensure_vector_session()
            self.vector_dock = VectorHost(
                body, VectorPanel(self.vector_session, docked=True))
            self.vector_dock.mount(side="left")
        except Exception as _e:
            print(f"[Vector] панель сбоку (админ): {_e}")

    def _ensure_vector_session(self):
        """Общая сессия Вектора (одна история для шторки и вкладки «ИИ Помощник»)."""
        if getattr(self, "vector_session", None) is not None:
            return self.vector_session
        from vector import VectorEngine, VectorScope, get_provider
        from vector.widget import VectorSession
        try:
            _cfg0 = get_store()._config()
        except Exception:
            _cfg0 = {}
        eng = VectorEngine(VectorScope(role="admin"), get_provider(_cfg0))
        self.vector_engine = eng
        self.vector_session = VectorSession(eng)
        return self.vector_session

    def _run_bg(self, fn, on_done, on_error=None):
        """Запустить fn() в фоновом потоке; on_done(result) вызовется в UI-потоке."""
        def _safe_done(result):
            #Пока шёл фоновый запрос, дерево виджетов могло быть пересобрано или закрыто
            #(смена роли/темы, выход) — тогда целевые QLabel/поля уже удалены на стороне
            #C++, и обращение к ним из on_done бросает RuntimeError «already deleted».
            #Это не ошибка логики: обновлять просто нечего — молча выходим. Прочие
            #RuntimeError пробрасываем (не маскируем реальные баги).
            try:
                on_done(result)
            except RuntimeError as e:
                if "already deleted" in str(e).lower():
                    return
                raise
        w = _BgWorker(fn)
        self._workers.append(w)
        w.done.connect(_safe_done)
        w.done.connect(lambda _: self._workers.remove(w) if w in self._workers else None)
        if on_error:
            w.error.connect(on_error)
        else:
            w.error.connect(lambda e: print(f"[BG] фоновая ошибка: {e}"))
        w.start()

    #Дашборд

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
            ("api",      "🐯",   "Настройки ИИ",   "Озвучка Вектора"),
            ("pg",       "🌐",   "Сервер",         "Адрес и пароль"),
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
            gh = get_store()
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

    #Преподаватели

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

    def _server_contacts(self, kind: str) -> dict:
        """Контакты с сервера по логину: {login: {phone, last_login, ip, device}}.

        kind — 'teachers' или 'students'. Данные (телефон/IP/последний вход) живут ТОЛЬКО
        на сервере (заявки + сессии), поэтому тянем их отдельным запросом — как на сайте.
        Вызывается ИЗ фонового потока (_fetch). Оффлайн/ошибка/не-админ → {} (список всё
        равно покажется по локальным данным, просто без контактной строки)."""
        try:
            import sync_runner
            url, token = sync_runner.current_auth()
            if not url or not token:
                return {}
            from sync_client import SyncClient
            c = SyncClient(url, token=token)
            data = c.admin_teachers() if kind == "teachers" else c.admin_students()
            rows = data.get("teachers" if kind == "teachers" else "students", [])
            return {r.get("login", ""): r for r in rows if r.get("login")}
        except Exception:
            return {}

    @staticmethod
    def _contact_line(c: dict) -> str:
        """Короткая строка контактов для списка: телефон · последний вход · IP (что есть)."""
        parts = []
        if c.get("phone"):      parts.append(f"📞 {c['phone']}")
        if c.get("last_login"): parts.append(f"🕒 {c['last_login'][:16].replace('T', ' ')}")
        if c.get("ip"):         parts.append(f"🌐 {c['ip']}")
        return "   ·   ".join(parts)

    def _render_teachers(self):
        q = self._t_search.text().lower()
        def _fetch():
            gh = get_store()
            teachers = gh.get_teachers() if gh else {}
            return teachers, self._server_contacts("teachers")
        def _apply(payload):
            teachers, contacts = payload
            self._t_list.clear()
            for name, data in teachers.items():
                if q and q not in name.lower(): continue
                has_pw = "✅" if (data.get("password_hash") or data.get("password")) else "❌"
                login = data.get("login", "")
                c = contacts.get(login, {})
                line = f"{has_pw}  {name}"
                if login:
                    line += f"   ·   {login}"
                cl = self._contact_line(c)
                if cl:
                    line += f"\n        {cl}"
                it = QListWidgetItem(line); it.setData(Qt.UserRole, name)
                self._t_list.addItem(it)
        self._run_bg(_fetch, _apply)

    def _open_teacher(self, name):
        gh = get_store()
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
        del_b = btn("Удалить", "red", icon_name="trash")
        def _del():
            gh = get_store()
            ts = gh.get_teachers() if gh else {}
            ts.pop(name, None)
            if gh: gh.set_teachers(ts)
            d.accept(); self._render_teachers()
        del_b.clicked.connect(_del)
        save_b = btn("Сохранить", "green")
        def _save():
            gh       = get_store()
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
            gh = get_store()
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
        gh = get_store()
        ts = gh.get_teachers() if gh else {}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ts, f, ensure_ascii=False, indent=2)
        #Аудит: экспорт персональных данных — значимое событие (152-ФЗ).
        log_event("export_personal_data", "admin", f"teachers={len(ts)}")
        QMessageBox.information(self, "Готово", f"Экспортировано {len(ts)} преподавателей")

    def _import_teachers(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт", "", "JSON (*.json)")
        if not path: return
        try:
            with open(path, encoding="utf-8") as f: new_t = json.load(f)
            if not isinstance(new_t, dict):
                QMessageBox.warning(self, "Ошибка", "Неверный формат"); return
            gh = get_store()
            cur   = gh.get_teachers() if gh else {}
            added = [n for n in new_t if n not in cur]
            for n in added: cur[n] = new_t[n]
            if gh: gh.set_teachers(cur)
            self._render_teachers(); self._refresh_dash()
            QMessageBox.information(self, "Готово", f"Добавлено: {len(added)}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    #Студенты 

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
        gh = get_store()
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
            gh = get_store()
            students = gh.get_students() if gh else []
            return students, self._server_contacts("students")
        def _apply(payload):
            students, contacts = payload
            self._s_list.clear()
            for i, s in enumerate(students):
                name = f"{s.get('surname', '')} {s.get('name', '')}".strip()
                if q and q not in name.lower(): continue
                if grp != "Все группы" and s.get("group", "") != grp: continue
                has_pw = "✅" if (s.get("password_hash") or s.get("password")) else "❌"
                login = s.get("login", "")
                c = contacts.get(login, {})
                line = f"{has_pw}  {name}  [{s.get('group', '—')}]"
                if login:
                    line += f"   ·   {login}"
                cl = self._contact_line(c)
                if cl:
                    line += f"\n        {cl}"
                it = QListWidgetItem(line)
                it.setData(Qt.UserRole, i); self._s_list.addItem(it)
        self._run_bg(_fetch, _apply)

    def _open_student(self, idx):
        gh = get_store()
        students = gh.get_students() if gh else []
        if idx >= len(students): return
        s = students[idx]
        d = QDialog(self); d.setWindowTitle("Студент"); d.resize(400, 350)
        lay = QVBoxLayout(d); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(10)
        lay.addWidget(title_lbl(f"{s.get('surname', '')} {s.get('name', '')}", 18))
        sn = field_input(); sn.setText(s.get("surname", ""))
        nm = field_input(); nm.setText(s.get("name", ""))
        grp = combo(self._all_group_choices()); grp.setEditable(True)
        grp.setCurrentText(s.get("group", ""))
        lg = field_input(); lg.setText(s.get("login", ""))
        pw = field_input("Новый пароль", password=True)
        for lb, w in [("Фамилия", sn), ("Имя", nm), ("Группа", grp), ("Логин", lg), ("Новый пароль", pw)]:
            lay.addWidget(lbl(lb.upper(), 10, C['text3'])); lay.addWidget(w)
        btns  = QHBoxLayout()
        del_b = btn("Удалить", "red", icon_name="trash")
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
            group = grp.currentText().strip()
            self._ensure_group_exists(group)   #новую/спарсенную группу заводим в БД
            nd  = {"surname": sn.text().strip(), "name": nm.text().strip(), "group": group,
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
        #Группа — выпадающий список спарсенных групп колледжа (+ уже заведённых);
        #редактируемый, чтобы при необходимости завести свою. По умолчанию не выбрана.
        grp = combo(self._all_group_choices()); grp.setEditable(True)
        grp.setCurrentText(""); grp.lineEdit().setPlaceholderText("Выберите или введите группу")
        pw = field_input("Пароль", password=True)
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
            gh = get_store()
            sts = gh.get_students() if gh else []
            if not lg.text().strip():
                QMessageBox.warning(d, "Ошибка", "Введите логин"); return
            group = grp.currentText().strip()
            self._ensure_group_exists(group)   #спарсенную/новую группу заводим в БД
            sts.append({"surname": s, "name": n, "group": group,
                        "login": lg.text().strip(), "password": pw.text().strip()})
            if gh: gh.set_students(sts)
            d.accept(); self._render_students(); self._refresh_dash()
        save.clicked.connect(_add); lay.addLayout(btns); d.exec()

    def _export_students(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", "students.json", "JSON (*.json)")
        if not path: return
        gh = get_store()
        sts = gh.get_students() if gh else []
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sts, f, ensure_ascii=False, indent=2)
        #Аудит: экспорт персональных данных — значимое событие (152-ФЗ).
        log_event("export_personal_data", "admin", f"students={len(sts)}")
        QMessageBox.information(self, "Готово", f"Экспортировано {len(sts)}")

    def _import_students(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт", "", "JSON (*.json)")
        if not path: return
        try:
            with open(path, encoding="utf-8") as f: new_s = json.load(f)
            if not isinstance(new_s, list):
                QMessageBox.warning(self, "Ошибка", "Неверный формат"); return
            gh = get_store()
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

    #Группы: источник (спарсенное расписание) и привязка студентов

    def _parsed_group_names(self):
        """Названия групп колледжа из спарсенного расписания. Офлайн/нет снимка →
        пустой список (тихо). Источник — локальный зашифрованный кэш расписания."""
        try:
            from schedule import store as _sched_store
            snap = _sched_store.load_cached()
            return snap.group_names() if snap else []
        except Exception:
            return []

    def _all_group_choices(self):
        """Слитый список для выбора группы: уже заведённые в БД + спарсенные из
        расписания, без дублей (сначала заведённые)."""
        gh = get_store()
        existing = [g.get("name", "") for g in (gh.get_groups() if gh else [])]
        seen, out = set(), []
        for name in existing + self._parsed_group_names():
            if name and name not in seen:
                seen.add(name); out.append(name)
        return out

    def _ensure_group_exists(self, name):
        """Заводит группу в БД, если её ещё нет (предметы пустые). Вызывается при
        добавлении/правке студента: выбрал спарсенную/новую группу — она сразу
        появляется в «Группах», а не остаётся «висячим» именем у студента."""
        name = (name or "").strip()
        if not name:
            return
        gh = get_store()
        gs = gh.get_groups() if gh else []
        if not any(g.get("name") == name for g in gs):
            gs.append({"name": name, "subjects": []})
            if gh:
                gh.set_groups(gs)

    def _import_parsed_groups(self):
        """Кнопка «🏫 Из расписания»: заводит спарсенные группы колледжа И ПРИВЯЗЫВАЕТ к
        каждой её предметы из расписания — предметы группы видны сразу, без ручного
        ввода (для группы К74/1 берутся все предметы из ЕЁ расписания и т.д.). Все
        предметы попадают и в общий каталог. Группы/предметы синкаются на сервер и сайт."""
        try:
            from schedule import store as _sched_store
            snap = _sched_store.load_cached()
        except Exception:
            snap = None
        if not snap or not snap.groups:
            QMessageBox.information(self, "Расписание",
                "Спарсенных групп нет — обнови расписание во вкладке «Расписание».")
            return
        store = get_store()
        gs = store.get_groups() if store else []
        by_name = {g.get("name"): g for g in gs}
        added = updated = 0
        all_subjects = set()
        for name, gsched in snap.groups.items():
            subs = [s for s in gsched.subjects() if s]   #предметы ИЗ расписания этой группы
            all_subjects.update(subs)
            if name in by_name:
                g = by_name[name]
                merged = sorted(set(g.get("subjects") or []) | set(subs))
                if merged != (g.get("subjects") or []):
                    g["subjects"] = merged
                    updated += 1
            else:
                grp = {"name": name, "subjects": sorted(subs)}
                gs.append(grp); by_name[name] = grp
                added += 1
        if store:
            store.set_groups(gs)
        #Предметы расписания — в общий каталог (чтобы были в списках выбора/нагрузки).
        try:
            from subjects import load_subjects, save_subjects
            save_subjects(sorted(set(load_subjects()) | all_subjects))
        except Exception as e:
            print(f"[groups] каталог предметов: {e}")
        self._render_groups(); self._refresh_dash()
        QMessageBox.information(self, "Готово",
            f"Групп добавлено: {added}, обновлено (привязаны предметы): {updated}.\n"
            f"Предметов из расписания: {len(all_subjects)}.")

    #Группы

    def _build_groups(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(12)
        hdr = QHBoxLayout(); hdr.addWidget(title_lbl("Группы"), 1)
        imp_b = btn("🏫 Из расписания", "ghost"); imp_b.clicked.connect(self._import_parsed_groups)
        hdr.addWidget(imp_b)
        add_b = btn("Добавить группу", "green", icon_name="plus"); add_b.clicked.connect(self._add_group)
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
            gh = get_store()
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
            store = get_store()
            gs = store.get_groups() if store else []
            if any(g["name"] == n for g in gs):
                QMessageBox.warning(d, "Ошибка", "Группа уже есть"); return
            gs.append({"name": n, "subjects": _get_checked(sj)})
            if store: store.set_groups(gs)
            d.accept(); self._render_groups(); self._refresh_dash()
        save.clicked.connect(_add); lay.addLayout(btns); d.exec()

    def _del_group(self, name):
        if QMessageBox.question(self, "Удалить?", f"Удалить группу {name}?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        store = get_store()
        gs = [g for g in (store.get_groups() if store else []) if g["name"] != name]
        if store: store.set_groups(gs)
        self._render_groups(); self._refresh_dash()

    #Предметы

    def _build_subjects(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(12)
        hdr = QHBoxLayout(); hdr.addWidget(title_lbl("Предметы"), 1)
        add_b = btn("Добавить", "green", icon_name="plus"); add_b.clicked.connect(self._add_subject)
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

    #Расписание (просмотр любой группы/преподавателя + обновление кэша с портала)

    def _build_schedule(self):
        from schedule_view import ScheduleView
        w = ScheduleView(role="admin", login="admin", app_hint="")
        self.pages["schedule"] = w
        self.stack.addWidget(w)

    #API ключ

    def _build_api(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("Настройки ИИ-помощника «Вектор»"))

        #Карточка: ИИ-помощник «Вектор» (офлайн / GigaChat / ollama)
        from PySide6.QtWidgets import QComboBox as _QC, QCheckBox as _QCB
        vc = card(); vl = QVBoxLayout(vc); vl.setContentsMargins(20, 18, 20, 18); vl.setSpacing(10)
        vl.addWidget(section_lbl("ИИ-помощник «Вектор»"))
        vl.addWidget(lbl("Кто озвучивает ответы Вектора", 11, C['text3']))

        self._vec_provider = _QC()
        self._vec_provider.addItem("Офлайн — без интернета, точно, суховато", "offline")
        self._vec_provider.addItem("GigaChat — живой тон, РФ-серверы (152-ФЗ)", "gigachat")
        self._vec_provider.addItem("Локальная модель ollama — живой тон, без сети", "local")
        self._vec_provider.currentIndexChanged.connect(self._toggle_vec_blocks)
        vl.addWidget(self._vec_provider)

        #GigaChat
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

        #ollama
        self._vec_local_box = QWidget(); lbx = QVBoxLayout(self._vec_local_box)
        lbx.setContentsMargins(0, 0, 0, 0); lbx.setSpacing(6)
        lbx.addWidget(lbl("Модель ollama", 10, C['text3']))
        self._vec_local_model = field_input("qwen2.5:3b")
        lbx.addWidget(self._vec_local_model)
        lbx.addWidget(lbl("Нужен запущенный ollama на http://localhost:11434. "
                          "Данные наружу не уходят вообще.", 10, C['text3']))
        vl.addWidget(self._vec_local_box)

        vsave = btn("Сохранить настройки Вектора", "green", icon_name="save")
        vsave.clicked.connect(self._save_vector_cfg)
        vrow = QHBoxLayout(); vrow.addWidget(vsave); vrow.addStretch()
        vl.addLayout(vrow)
        lay.addWidget(vc)

        lay.addStretch()
        self.pages["api"] = w; self.stack.addWidget(w)
        self._refresh_vector_cfg()

    #ИИ-помощник «Вектор»: провайдер озвучки
    def _vec_cfg(self) -> dict:
        try:
            return dict(get_store()._config() or {})
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
            self._vec_giga_status.setStyleSheet(f"font-size:12px;color:{C['orange']};")

        self._run_bg(_check, _ok, _err)

    #Сервер синхронизации (адрес API + пароль администратора)

    def _build_pg(self):
        from app_settings import get_api_url
        w = QScrollArea(); w.setWidgetResizable(True); w.setStyleSheet("border:none;")
        inner = QWidget(); lay = QVBoxLayout(inner); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("Сервер и сайт"))

        #Карточка СОСТОЯНИЯ — самое важное сверху: работает ли сервер и сайт ПРЯМО СЕЙЧАС.
        #Статус по РЕАЛЬНОЙ доступности адреса (а не только локального процесса): если
        #сервер поднят на VPS, админ сразу видит зелёное «работает», а не «Запустить».
        stc = card(); stl = QVBoxLayout(stc); stl.setContentsMargins(18, 16, 18, 16); stl.setSpacing(6)
        stl.addWidget(section_lbl("Состояние"))
        self._srv_status = lbl("Проверяю…", 13, wrap=True)
        stl.addWidget(self._srv_status)
        lay.addWidget(stc)

        #Карточка: единый адрес сайта и онлайн-базы. По умолчанию вшит боевой адрес
        #esstu-gradebook.ru; менять нужно только если сервер переехал.
        ac = card(); al = QVBoxLayout(ac); al.setContentsMargins(18, 16, 18, 16); al.setSpacing(10)
        al.addWidget(section_lbl("Адрес сайта и онлайн-базы"))
        al.addWidget(lbl("Единый адрес сайта и общей онлайн-базы колледжа. Обычно уже вшит "
                         "в программу — менять нужно только если сервер переехал. Студенты и "
                         "преподаватели просто входят, данные подтягиваются сами.",
                         11, C['text3'], wrap=True))
        self._api_url = field_input("https://esstu-gradebook.ru"); self._api_url.setText(get_api_url())
        al.addWidget(self._api_url)
        arow = QHBoxLayout()
        asave = btn("Сохранить адрес", "green", icon_name="save"); asave.clicked.connect(self._save_api_url)
        arefresh = btn("Проверить", "ghost", icon_name="refresh")
        arefresh.clicked.connect(lambda: (self._refresh_server_status(), self._refresh_compliance()))
        arow.addWidget(asave); arow.addWidget(arefresh); arow.addStretch(); al.addLayout(arow)
        lay.addWidget(ac)

        #Карточка: РАЗМЕСТИТЬ сервер на этом ПК. Сейчас боевой сервер — на VPS
        #(esstu-gradebook.ru); позже его можно поднять прямо на ПК ВСГУТУ этой кнопкой:
        #одним нажатием стартуют и САЙТ, и онлайн-БД (один адрес, один процесс).
        from PySide6.QtWidgets import QComboBox as _QC, QCheckBox as _QCB
        hc = card(); hl = QVBoxLayout(hc); hl.setContentsMargins(18, 16, 18, 16); hl.setSpacing(10)
        hl.addWidget(section_lbl("Разместить сервер на этом ПК"))
        hl.addWidget(lbl("Поднять сайт и онлайн-базу прямо на этом компьютере (он станет "
                         "сервером колледжа). Нужно только на ОДНОМ ПК. Сейчас сервер работает "
                         "на VPS — эта кнопка понадобится, когда сервер переедет на ПК ВСГУТУ.",
                         11, C['text3'], wrap=True))

        #Движок базы данных: SQLite 3 (проще, по умолчанию) или PostgreSQL (нагрузка/много ПК).
        hl.addWidget(lbl("БАЗА ДАННЫХ", 10, C['text3']))
        self._srv_engine = _QC()
        self._srv_engine.addItem("SQLite 3 — проще, по умолчанию", "sqlite")
        self._srv_engine.addItem("PostgreSQL — нагрузка и много ПК", "postgres")
        self._srv_engine.currentIndexChanged.connect(self._toggle_server_fields)
        hl.addWidget(self._srv_engine)

        #Реквизиты PostgreSQL — видны только когда выбран движок PostgreSQL.
        self._pg_box = QWidget(); pgl = QVBoxLayout(self._pg_box)
        pgl.setContentsMargins(0, 0, 0, 0); pgl.setSpacing(6)
        self._pg_host = field_input("localhost")
        self._pg_port = field_input("5432")
        self._pg_db   = field_input("vsgutu_grades")
        self._pg_user = field_input("vsgutu_user")
        self._pg_pass = field_input("пароль БД", password=True)
        for lab, wdg in [("ХОСТ", self._pg_host), ("ПОРТ", self._pg_port),
                         ("БАЗА", self._pg_db), ("ПОЛЬЗОВАТЕЛЬ", self._pg_user),
                         ("ПАРОЛЬ", self._pg_pass)]:
            pgl.addWidget(lbl(lab, 10, C['text3'])); pgl.addWidget(wdg)
        show_pg = _QCB("Показать пароль")
        show_pg.toggled.connect(lambda on: self._pg_pass.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        pgl.addWidget(show_pg)
        test_pg = btn("Проверить подключение", "blue"); test_pg.clicked.connect(self._test_pg_conn)
        pgl.addWidget(test_pg)
        self._pg_status = lbl("", 12, wrap=True)
        pgl.addWidget(self._pg_status)
        hl.addWidget(self._pg_box)

        prow = QHBoxLayout()
        prow.addWidget(lbl("ПОРТ", 10, C['text3']))
        self._srv_port = field_input("8000"); self._srv_port.setFixedWidth(90)
        self._srv_port.setText("8000")
        prow.addWidget(self._srv_port); prow.addStretch()
        hl.addLayout(prow)

        btnrow = QHBoxLayout()
        self._srv_start = btn("Запустить сайт и онлайн-базу", "green", icon_name="play")
        self._srv_start.clicked.connect(self._start_server)
        self._srv_stop  = btn("Остановить", "red", icon_name="stop")
        self._srv_stop.clicked.connect(self._stop_server)
        btnrow.addWidget(self._srv_start); btnrow.addWidget(self._srv_stop); btnrow.addStretch()
        hl.addLayout(btnrow)
        self._srv_host_status = lbl("", 12, wrap=True)
        hl.addWidget(self._srv_host_status)

        #Адрес запущенного сайта/БД (один и тот же) — появляется после старта и копируется
        #в буфер обмена, чтобы отправить студентам и преподавателям.
        hl.addWidget(separator())
        hl.addWidget(lbl("Адрес сайта и онлайн-базы (отправьте пользователям):", 11, C['text3'], wrap=True))
        self._site_url = field_input("появится после запуска")
        self._site_url.setReadOnly(True)
        hl.addWidget(self._site_url)

        lay.addWidget(hc)

        #Карточка: ГОТОВНОСТЬ к 152-ФЗ (УЗ-3). Жмёшь «Проверить» — видишь зелёным/красным,
        #что готово в самой проге, и список того, что ОДИН РАЗ настраивает IT ВСГУТУ
        #(ViPNet/ГОСТ-TLS — это их инфраструктура, прога её не создаёт).
        cc = card(); cl = QVBoxLayout(cc); cl.setContentsMargins(18, 16, 18, 16); cl.setSpacing(8)
        cl.addWidget(section_lbl("Готовность к 152-ФЗ (УЗ-3)"))
        cl.addWidget(lbl("Что прога делает сама — зелёным ниже. ViPNet / ГОСТ-TLS / HTTPS — "
                         "это «броня» вокруг сервера, её один раз ставит IT-отдел ВСГУТУ "
                         "(прога её не создаёт). Жми «Проверить готовность» после запуска сервера.",
                         11, C['text3']))
        self._cmp_server = lbl("…", 12); self._cmp_server.setWordWrap(True)
        self._cmp_channel = lbl("…", 12); self._cmp_channel.setWordWrap(True)
        self._cmp_hash = lbl("…", 12); self._cmp_hash.setWordWrap(True)
        self._cmp_app = lbl("…", 12); self._cmp_app.setWordWrap(True)
        for wlbl in (self._cmp_server, self._cmp_channel, self._cmp_hash, self._cmp_app):
            cl.addWidget(wlbl)
        cl.addWidget(separator())
        cl.addWidget(lbl("Один раз настраивает IT ВСГУТУ (инфраструктура, см. server/DEPLOY.md, "
                         "раздел 7.7):\n"
                         "•  ViPNet / ГОСТ-TLS на канал (HTTPS отечественной криптой)\n"
                         "•  межсетевой экран + DMZ (сервер БД не виден из интернета)\n"
                         "•  антивирус • СЗИ от НСД на сервере • физдоступ к серверу\n"
                         "•  изолированное хранилище для резервных копий", 11, C['text3']))
        cbtnrow = QHBoxLayout()
        cbtn = btn("Проверить готовность", "blue", icon_name="refresh"); cbtn.clicked.connect(self._refresh_compliance)
        cbtnrow.addWidget(cbtn); cbtnrow.addStretch(); cl.addLayout(cbtnrow)
        lay.addWidget(cc)

        #Карточка: смена пароля администратора
        sc = card(); sl = QVBoxLayout(sc); sl.setContentsMargins(18, 16, 18, 16); sl.setSpacing(10)
        sl.addWidget(section_lbl("Пароль администратора"))
        self._adm_old = field_input("Текущий пароль", password=True)
        self._adm_new = field_input("Новый пароль (мин. 8 символов)", password=True)
        self._adm_new2 = field_input("Повтор нового пароля", password=True)
        for lab, wdg in [("ТЕКУЩИЙ ПАРОЛЬ", self._adm_old),
                         ("НОВЫЙ ПАРОЛЬ", self._adm_new),
                         ("ПОВТОР", self._adm_new2)]:
            sl.addWidget(lbl(lab, 10, C['text3'])); sl.addWidget(wdg)
        chg = btn("Сменить пароль", "green", icon_name="key"); chg.clicked.connect(self._change_admin_pw)
        srow = QHBoxLayout(); srow.addWidget(chg); srow.addStretch(); sl.addLayout(srow)
        lay.addWidget(sc)

        #Карточка: ОПАСНАЯ ЗОНА — где лежат данные и полный локальный сброс.
        #Тут же отвечаем на вопрос «где физически база»: показываем путь и даём
        #кнопку открыть папку в проводнике.
        from core import DATA_DIR
        dz = card(); dl = QVBoxLayout(dz); dl.setContentsMargins(18, 16, 18, 16); dl.setSpacing(10)
        dl.addWidget(section_lbl("Опасная зона"))
        dl.addWidget(lbl("Данные этого ПК (база, резервные копии, журнал входов) лежат в папке:",
                         11, C['text3']))
        path_lbl = lbl(DATA_DIR, 11, C['text']); path_lbl.setWordWrap(True)
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dl.addWidget(path_lbl)
        orow = QHBoxLayout()
        openb = btn("Открыть папку с данными", "blue", icon_name="folder"); openb.clicked.connect(self._open_data_folder)
        orow.addWidget(openb); orow.addStretch(); dl.addLayout(orow)
        dl.addWidget(separator())
        dl.addWidget(lbl("Полностью удалить ВСЕ локальные данные этого ПК: студентов, "
                         "преподавателей, группы, оценки, пароль администратора, адрес "
                         "сервера, сохранённый вход и резервные копии. Программа вернётся "
                         "к состоянию первого запуска. Общую базу колледжа на сервере это "
                         "НЕ затрагивает.", 11, C['red']))
        wrow = QHBoxLayout()
        wipeb = btn("Очистить все локальные данные", "red", icon_name="trash"); wipeb.clicked.connect(self._wipe_all_data)
        wrow.addWidget(wipeb); wrow.addStretch(); dl.addLayout(wrow)
        lay.addWidget(dz)

        lay.addStretch()
        #Перенос во ВСЕХ подписях страницы — длинные пояснения не уезжают за правый край.
        #ВАЖНО: ширину НЕ ограничиваем и alignment у QScrollArea НЕ трогаем — их сочетание
        #с setWidgetResizable(True) приводило к удалению дочерних виджетов на стороне C++
        #(«Internal C++ object already deleted»), из-за чего вкладка переставала открываться.
        for _q in inner.findChildren(QLabel):
            _q.setWordWrap(True)
        self.pages["pg"] = w; self.stack.addWidget(w)
        self._refresh_server_cfg()
        self._refresh_server_status()
        self._refresh_compliance()

    #ЭТОТ ПК как сервер: выбор движка БД, запуск/остановка
    def _current_type(self):
        """(access, engine). Движок — из выбора БД (SQLite/PostgreSQL); доступ — 'domain',
        если адрес это https-домен (Caddy поднимет HTTPS), иначе 'direct' (ЛВС)."""
        try:
            engine = self._srv_engine.currentData() or "sqlite"
            url = (self._api_url.text() or "").strip()
        except RuntimeError:
            return "direct", "sqlite"
        access = "domain" if url.startswith("https://") else "direct"
        return access, engine

    def _toggle_server_fields(self, *_):
        """Реквизиты PostgreSQL показываем только когда выбран движок PostgreSQL."""
        try:
            _, engine = self._current_type()
            self._pg_box.setVisible(engine == "postgres")
        except RuntimeError:
            pass

    def _refresh_server_cfg(self):
        """Подтягивает сохранённый движок БД и реквизиты PostgreSQL из server/.env."""
        try:
            import server_control
        except Exception:
            return
        is_pg = server_control.is_postgres()
        try:
            self._srv_engine.setCurrentIndex(1 if is_pg else 0)
            self._srv_port.setText(str(server_control.get_server_port()))
        except Exception:
            pass
        if is_pg:
            #Разбираем строку подключения, чтобы заполнить поля (без пароля — он
            #остаётся в .env; пустое поле = «не менять» при запуске).
            try:
                from urllib.parse import urlparse, unquote
                u = urlparse(server_control.get_db_url())
                self._pg_host.setText(u.hostname or "localhost")
                self._pg_port.setText(str(u.port or 5432))
                self._pg_db.setText((u.path or "/vsgutu_grades").lstrip("/"))
                self._pg_user.setText(unquote(u.username or ""))
            except Exception:
                pass
        self._toggle_server_fields()

    def _refresh_server_status(self):
        """Показывает, работает ли сервер и сайт ПРЯМО СЕЙЧАС — по РЕАЛЬНОЙ доступности
        настроенного адреса (ловит и сервер на VPS), а не только локального процесса.
        Управляет доступностью кнопок «Запустить/Остановить»."""
        #Виджеты вкладки могли быть уничтожены (пересборка дашборда при смене темы) —
        #обращение к ним бросает RuntimeError. Молча выходим: обновлять нечего.
        try:
            port = int(self._srv_port.text().strip() or "8000")
        except ValueError:
            port = 8000
        except RuntimeError:
            return
        try:
            url = (self._api_url.text() or "").strip()
        except RuntimeError:
            return

        def _check():
            import server_control
            local = server_control.server_running(port)
            remote = False
            if url:
                try:
                    from sync_client import SyncClient
                    remote = SyncClient(url).health()
                except Exception:
                    remote = False
            return local, remote

        def _apply(res):
            local, remote = res
            if remote:
                self._srv_status.setText(f"✅ Сервер и сайт работают: {url}\n"
                                         "Синхронизация активна — данные общие для всех ПК.")
                self._srv_status.setStyleSheet(f"font-size:13px;color:{C['green']};font-weight:700;")
            elif local:
                self._srv_status.setText(f"✅ Локальный сервер запущен на порту {port} "
                                         "(адрес сайта ещё не прописан выше).")
                self._srv_status.setStyleSheet(f"font-size:13px;color:{C['green']};font-weight:700;")
            elif url:
                self._srv_status.setText(f"⏹ Сервер недоступен по адресу {url}.\n"
                                         "Проверьте адрес или запустите сервер ниже.")
                self._srv_status.setStyleSheet(f"font-size:13px;color:{C['orange']};")
            else:
                self._srv_status.setText("⏹ Адрес не задан — работа только локально. "
                                         "Впишите адрес выше или запустите сервер ниже.")
                self._srv_status.setStyleSheet(f"font-size:13px;color:{C['text3']};")
            #Если сервер работает (локальный или удалённый) — «Запустить» гасим. «Остановить»
            #доступно только для ЛОКАЛЬНОГО процесса (сервер на VPS отсюда не остановить).
            self._srv_start.setEnabled(not (local or remote))
            self._srv_stop.setEnabled(local)

        self._run_bg(_check, _apply)

    def _refresh_compliance(self):
        """Панель готовности к 152-ФЗ: что прога обеспечивает сама (зелёным), и
        что остаётся на инфраструктуру ВСГУТУ. Живые проверки: сервер запущен,
        защищён ли канал, активен ли ГОСТ-бэкенд хеша."""
        #Проба: живы ли виджеты вкладки (дашборд мог быть пересобран при смене темы,
        #тогда C++-объекты удалены). Если нет — молча выходим, обновлять нечего.
        try:
            self._cmp_hash.text()
        except RuntimeError:
            return
        ok, warn, bad = C['green'], C['orange'], C['red']

        def _set(widget, text, color):
            widget.setText(text)
            widget.setStyleSheet(f"font-size:12px;color:{color};")

        #ГОСТ-хеш пароля (всегда активен — гибрид; показываем бэкенд)
        try:
            import security
            label, _fast = security.gost_backend_info()
            _set(self._cmp_hash, f"✅ ГОСТ-хеш пароля включён (бэкенд: {label})", ok)
        except Exception:
            _set(self._cmp_hash, "✅ ГОСТ-хеш пароля включён", ok)

        #Канал: HTTPS / ГОСТ-TLS / локальный / открытый
        try:
            from app_settings import get_api_url, is_secure_transport
            url = (get_api_url() or "").strip()
        except Exception:
            url = ""
        if not url:
            _set(self._cmp_channel, "⚠️ Адрес сервера не задан — канал ещё не настроен", warn)
        elif url.startswith("https://"):
            _set(self._cmp_channel, f"✅ Канал защищён (HTTPS/TLS): {url}", ok)
        elif is_secure_transport(url):
            _set(self._cmp_channel, "◻ Сервер локальный (127.0.0.1). Снаружи защиту даёт "
                                    "ГОСТ-TLS/ViPNet перед сервером — настраивает IT ВСГУТУ", warn)
        else:
            _set(self._cmp_channel, f"❌ Канал НЕ защищён (http к удалённому адресу): {url}. "
                                    "Нужен ViPNet ГОСТ-TLS или HTTPS!", bad)

        #Прикладные меры — всегда включены
        _set(self._cmp_app, "✅ Роли, анти-брутфорс, журнал входов/событий, авто-бэкап — включены", ok)

        #Сервер запущен? — фоновая проверка
        try:
            port = int(self._srv_port.text().strip() or "8000")
        except ValueError:
            port = 8000

        def _chk():
            import server_control
            return server_control.server_running(port)

        def _apply(running):
            if running:
                _set(self._cmp_server, f"✅ Сервер (API) запущен на порту {port}", ok)
            else:
                _set(self._cmp_server, "⏹ Сервер не запущен — нажмите «Запустить сервер» выше", warn)

        self._run_bg(_chk, _apply)

    def _test_pg_conn(self):
        import server_control
        self._pg_status.setText("⏳ Проверяю подключение...")
        self._pg_status.setStyleSheet(f"font-size:12px;color:{C['text3']};")
        host, port = self._pg_host.text(), self._pg_port.text()
        db, user, pw = self._pg_db.text(), self._pg_user.text(), self._pg_pass.text()

        def _check():
            return server_control.test_postgres(host, port, db, user, pw)

        def _apply(res):
            ok, msg = res
            if ok:
                self._pg_status.setText(f"✓ Подключение успешно: {str(msg)[:60]}")
                self._pg_status.setStyleSheet(f"font-size:12px;color:{C['green']};")
            else:
                self._pg_status.setText("✗ " + str(msg))
                self._pg_status.setStyleSheet(f"font-size:12px;color:{C['orange']};")

        self._run_bg(_check, _apply)

    def _start_server(self):
        """Одна кнопка: поднять на этом ПК и САЙТ, и онлайн-БД (один процесс, один адрес).
        Движок берём из выбора БД; домен — из адреса выше (https-домен → Caddy поднимет
        HTTPS сам). Полученный адрес записывается в программу автоматически."""
        import server_control
        try:
            port = int(self._srv_port.text().strip() or "8000")
        except ValueError:
            port = 8000
        access, engine = self._current_type()
        name = ""
        #Домен для боевого HTTPS берём из адреса сайта выше (напр. esstu-gradebook.ru).
        domain = ""
        if access == "domain":
            try:
                from urllib.parse import urlparse
                domain = urlparse((self._api_url.text() or "").strip()).hostname or ""
            except Exception:
                domain = ""
            if domain:
                try:
                    server_control.set_domain(domain)
                except Exception:
                    pass
        pg = None
        if engine == "postgres":
            pw = self._pg_pass.text()
            if not pw:
                #Пустой пароль при уже настроенном PG — берём прежний из .env.
                from urllib.parse import urlparse, unquote
                try:
                    u = urlparse(server_control.get_db_url())
                    pw = unquote(u.password or "") if server_control.is_postgres() else ""
                except Exception:
                    pw = ""
            pg = {"host": self._pg_host.text(), "port": self._pg_port.text(),
                  "db": self._pg_db.text(), "user": self._pg_user.text(), "password": pw}

        _startmsg = ("⏳ Запускаю сайт и онлайн-базу с HTTPS (Caddy)…" if access == "domain"
                     else "⏳ Запускаю сайт и онлайн-базу…")
        self._srv_host_status.setText(_startmsg)
        self._srv_host_status.setStyleSheet(f"font-size:12px;color:{C['text3']};")
        self._srv_start.setEnabled(False)

        def _do():
            return server_control.launch(access, engine, port, name, pg, domain)

        def _apply(res):
            ok, url, message = res
            if ok and url:
                #Этот ПК — хост и теперь должен поднимать свой сервер сам при каждом
                #старте программы (постоянная связь): запоминаем порт и включаем
                #автозапуск. Свой адрес у хоста — всегда localhost (сервер локальный),
                #а публичный/ЛВС-адрес для других ПК показан в message ниже.
                from app_settings import set_api_url, set_host_autostart, mark_host
                try:
                    server_control.set_server_port(port)
                except Exception:
                    pass
                mark_host()
                set_host_autostart(True)
                #Адрес берём из launch(): для домена это https://<домен>, для serveo —
                #ссылка serveo.net, для прямого — http://127.0.0.1:port. Он же и адрес
                #САЙТА (сервер отдаёт фронтенд с того же адреса).
                set_api_url(url)
                self._api_url.setText(url)
                self._site_url.setText(url)
                #Копируем адрес в буфер обмена — админу останется отправить ссылку.
                try:
                    from PySide6.QtWidgets import QApplication
                    cb = QApplication.clipboard()
                    if cb is not None:
                        cb.setText(url)
                except Exception:
                    pass
                #Будим фоновый синк: на хост-ПК он стартовал при входе ещё без адреса
                #и idle-ждёт. Теперь адрес есть — пусть сразу залогинится на сервер,
                #отдаст пользователей (иначе препод/студент получат 401) и подтянет
                #токен для мониторинга, не дожидаясь интервала.
                try:
                    import sync_runner
                    sync_runner.trigger()
                except Exception:
                    pass
                self._srv_host_status.setText("✅ Запущено.")
                self._srv_host_status.setStyleSheet(f"font-size:12px;color:{C['green']};")
                QMessageBox.information(self, "Сайт и онлайн-база запущены",
                                       message + "\n\nАдрес скопирован в буфер обмена — "
                                       "отправьте ссылку студентам и преподавателям.")
            else:
                self._srv_host_status.setText("")
                QMessageBox.critical(self, "Сервер",
                                     message or "Не удалось запустить сервер.")
            self._refresh_server_status()

        self._run_bg(_do, _apply)

    def _stop_server(self):
        """Останавливает ЛОКАЛЬНЫЙ сервер+сайт на этом ПК (и связанный туннель), после чего
        синхронизация с ним прекращается. (Закрытие программы их не гасит — только эта
        кнопка.) Сервер на VPS отсюда не останавливается — он живёт своей жизнью."""
        import server_control
        try:
            port = int(self._srv_port.text().strip() or "8000")
        except ValueError:
            port = 8000
        self._srv_host_status.setText("⏳ Останавливаю сайт и онлайн-базу…")
        self._srv_host_status.setStyleSheet(f"font-size:12px;color:{C['text3']};")
        self._srv_stop.setEnabled(False)

        def _do():
            return server_control.stop_processes(port)   #туннель + сервер по PID

        def _apply(res):
            ok, msg = res
            if ok:
                #Явная остановка = «больше не поднимать сервер сам». Снимаем автозапуск,
                #иначе при следующем старте программы хост опять поднял бы сервер.
                try:
                    from app_settings import set_host_autostart
                    set_host_autostart(False)
                except Exception:
                    pass
                self._srv_host_status.setText("⏹ Остановлено. Синхронизация с этим ПК прекращена.")
                self._srv_host_status.setStyleSheet(f"font-size:12px;color:{C['text3']};")
                self._site_url.setText("")
            else:
                self._srv_host_status.setText("")
                QMessageBox.warning(self, "Сервер", msg)
            self._refresh_server_status()

        self._run_bg(_do, _apply)

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
        на все ПК через сервер (API)."""
        gh = get_store()
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

    #Опасная зона: расположение данных и полный локальный сброс
    def _open_data_folder(self):
        """Открыть в проводнике папку, где физически лежат база и резервные копии."""
        from core import DATA_DIR
        try:
            os.startfile(DATA_DIR)   #Windows: открыть каталог в проводнике
        except Exception as e:
            QMessageBox.information(self, "Папка с данными",
                                    f"{DATA_DIR}\n\n(открыть автоматически не вышло: {e})")

    def _wipe_all_data(self):
        """Полный локальный сброс. Двойное подтверждение (предупреждение + ввод слова),
        потому что действие необратимо. После очистки закрываем программу: текущая
        сессия админа держится на уже удалённой базе, чистый старт даст перезапуск."""
        warn = QMessageBox(self)
        warn.setIcon(QMessageBox.Warning)
        warn.setWindowTitle("Очистка всех данных")
        warn.setText("Будут БЕЗВОЗВРАТНО удалены все локальные данные этого ПК:\n"
                     "•  студенты, преподаватели, группы, оценки\n"
                     "•  пароль администратора и сохранённый вход\n"
                     "•  адрес сервера и резервные копии\n\n"
                     "Общую базу колледжа на сервере это не затрагивает. Продолжить?")
        warn.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        warn.setDefaultButton(QMessageBox.No)
        if warn.exec() != QMessageBox.Yes:
            return
        word, ok = QInputDialog.getText(
            self, "Подтверждение",
            "Действие необратимо. Введите слово  УДАЛИТЬ  заглавными, чтобы подтвердить:")
        if not ok or word.strip() != "УДАЛИТЬ":
            QMessageBox.information(self, "Отменено", "Очистка отменена.")
            return

        res = DBManager.wipe_all_local_data(remove_backups=True)
        log_event("local_data_wiped", "admin", f"removed={len(res.get('removed', []))}")
        errs = res.get("errors") or []
        if errs:
            QMessageBox.warning(
                self, "Очищено с замечаниями",
                "Часть файлов удалить не удалось (возможно, заняты другим процессом):\n\n"
                + "\n".join(errs[:8])
                + "\n\nЗакройте программу и при необходимости удалите остаток вручную.")
        else:
            QMessageBox.information(
                self, "Готово",
                "Все локальные данные удалены. Программа закроется — запустите её заново "
                "для настройки с чистого листа.")
        QApplication.quit()

    #ИИ

    def _build_ai(self):
        """Вкладка «ИИ Помощник» — Вектор. Делит ОБЩУЮ сессию со шторкой."""
        try:
            from vector.widget import VectorPanel
            self._ensure_vector_session()
            ai = VectorPanel(self.vector_session, docked=False)
        except Exception as _e:
            print(f"[Vector] вкладка не собралась (админ): {_e}")
            ai = vector_unavailable_widget()
        self.pages["ai"] = ai; self.stack.addWidget(ai)

    def _build_theme(self):
        """Вкладка «Оформление»: админ задаёт тему учебного заведения по умолчанию.
        Палитра уезжает в общий config и применяется всем, у кого нет своей темы."""
        from theme_ui import ThemeCustomizer
        import theme_service
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        def _save(s):
            theme_service.save_institution_theme(s)
            win = self.window()
            if hasattr(win, "reapply_current"):
                win.reapply_current()

        lay.addWidget(ThemeCustomizer(initial_spec=theme_service.current_spec("admin", {}),
                                      on_save=_save))
        self.pages["theme"] = w; self.stack.addWidget(w)

    #Роутинг

    #Запросы на подключение (барьер подтверждения устройств; данные с /connect/requests)
    #Заявки студентов на самостоятельную регистрацию (с экрана входа сайта). Десктоп
    #видит и решает их 1:1 с веб-админкой: одобрил → сервер заводит студента и шлёт
    #пароль на почту (или показывает его тут, если письмо не ушло), отклонил → закрыл.
    def _build_registrations(self):
        w = QScrollArea(); w.setWidgetResizable(True); w.setStyleSheet("border:none;")
        inner = QWidget(); lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("Запросы на регистрацию"))
        hint = lbl("Студенты сами оставляют заявку на регистрацию с экрана входа сайта. "
                   "Проверьте ФИО и группу — одобрите, и сервер заведёт студента и вышлет "
                   "пароль ему на почту (если письмо не уйдёт — покажем пароль здесь, "
                   "передадите вручную). Список обновляется автоматически.", 11, C['text3'])
        hint.setWordWrap(True)
        lay.addWidget(hint)

        rc = card(); rl = QVBoxLayout(rc); rl.setContentsMargins(18, 16, 18, 16); rl.setSpacing(8)
        self._reg_title = section_lbl("Ожидают решения")
        rl.addWidget(self._reg_title)
        self._reg_box = QVBoxLayout(); self._reg_box.setSpacing(8)
        rl.addLayout(self._reg_box)
        self._reg_status = lbl("", 11, C['text3']); self._reg_status.setWordWrap(True)
        rl.addWidget(self._reg_status)
        lay.addWidget(rc)

        lay.addStretch()
        inner.setMaximumWidth(820)
        w.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        w.setWidget(inner)
        self.pages["reg"] = w; self.stack.addWidget(w)

        self._reg_timer = QTimer(self)
        self._reg_timer.setInterval(5000)             #раз в 5 секунд
        self._reg_timer.timeout.connect(self._poll_registrations)

    def _start_registrations(self):
        self._reg_status.setText("⏳ Запрашиваю заявки...")
        self._poll_registrations()
        self._reg_timer.start()

    def _stop_registrations(self):
        if getattr(self, "_reg_timer", None) is not None:
            self._reg_timer.stop()

    def _poll_registrations(self):
        import sync_runner
        url, token = sync_runner.current_auth()
        if not url or not token:
            self._reg_status.setText("⏹ Сервер не подключён. Запустите сервер во вкладке "
                                     "«Сервер» и войдите администратором.")
            self._clear_reg_rows()
            return

        def _do():
            from sync_client import SyncClient
            return SyncClient(url, token=token).list_registrations()

        def _apply(data):
            self._render_registrations(data)
            self._reg_status.setText("")

        def _err(e):
            self._reg_status.setText(f"⚠️ Не удалось получить заявки: {e}")

        self._run_bg(_do, _apply, _err)

    def _clear_reg_rows(self):
        while self._reg_box.count():
            it = self._reg_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _render_registrations(self, data):
        rows = (data or {}).get("requests", [])
        self._reg_title.setText(f"Ожидают решения: {len(rows)}")
        self._clear_reg_rows()
        if not rows:
            self._reg_box.addWidget(lbl("— новых заявок нет —", 12, C['text3']))
            return
        for r in rows:
            self._reg_box.addWidget(self._make_reg_row(r))

    def _make_reg_row(self, r: dict) -> QFrame:
        """Строка заявки: ФИО · группа · телефон · e-mail · дата и кнопки решения."""
        rid = r.get("id", "")
        who = r.get("full_name", "") or "—"
        grp = r.get("group", "") or "—"
        phone = r.get("phone", "") or "—"
        email = r.get("email", "") or "—"
        created = (r.get("created_at", "") or "")[:16].replace("T", " ")
        f = QFrame(); f.setObjectName("card")
        h = QHBoxLayout(f); h.setContentsMargins(14, 10, 14, 10); h.setSpacing(10)
        info = (f"👤 {who}   ·   🏫 {grp}\n"
                f"📞 {phone}   ·   ✉️ {email}" + (f"   ·   🕒 {created}" if created else ""))
        info_lbl = lbl(info, 12, C['text']); info_lbl.setWordWrap(True)
        h.addWidget(info_lbl, 1)
        b_ok = btn("Одобрить", "green", icon_name="check")
        b_ok.clicked.connect(lambda _=0, i=rid, n=who: self._approve_registration(i, n))
        h.addWidget(b_ok)
        b_no = btn("Отклонить", "red", icon_name="x")
        b_no.clicked.connect(lambda _=0, i=rid: self._reject_registration(i))
        h.addWidget(b_no)
        return f

    def _approve_registration(self, req_id: str, who: str = ""):
        import sync_runner
        url, token = sync_runner.current_auth()
        if not url or not token:
            QMessageBox.warning(self, "Сервер", "Сервер не подключён."); return

        def _do():
            from sync_client import SyncClient
            return SyncClient(url, token=token).approve_registration(req_id)

        def _apply(res):
            res = res or {}
            login = res.get("login", "")
            pw = res.get("password")
            if pw:   #письмо не ушло — показываем пароль админу, чтобы передать вручную
                QMessageBox.information(
                    self, "Заявка одобрена",
                    f"Студент {who} заведён.\n\nЛогин: {login}\nПароль: {pw}\n\n"
                    "Письмо на почту отправить не удалось — передайте эти данные вручную.")
            else:
                QMessageBox.information(
                    self, "Заявка одобрена",
                    f"Студент {who} заведён.\nЛогин и пароль отправлены на почту: {login}.")
            self._poll_registrations(); self._refresh_dash()

        def _err(e):
            QMessageBox.warning(self, "Сервер", f"Не удалось одобрить заявку: {e}")

        self._run_bg(_do, _apply, _err)

    def _reject_registration(self, req_id: str):
        note, ok = QInputDialog.getText(self, "Отклонить заявку",
                                        "Причина (необязательно):")
        if not ok:
            return
        import sync_runner
        url, token = sync_runner.current_auth()
        if not url or not token:
            QMessageBox.warning(self, "Сервер", "Сервер не подключён."); return

        def _do():
            from sync_client import SyncClient
            return SyncClient(url, token=token).reject_registration(req_id, note.strip())

        def _apply(_res):
            self._poll_registrations()

        def _err(e):
            QMessageBox.warning(self, "Сервер", f"Не удалось отклонить заявку: {e}")

        self._run_bg(_do, _apply, _err)

    def _build_requests(self):
        w = QScrollArea(); w.setWidgetResizable(True); w.setStyleSheet("border:none;")
        inner = QWidget(); lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("Запросы на подключение"))
        #ВАЖНО: lbl() по умолчанию НЕ переносит текст, поэтому длинное описание
        #раздувало внутренний виджет шире области прокрутки и уезжало за правый край
        #экрана. Включаем перенос явно — теперь текст всегда вписывается в ширину окна.
        req_hint = lbl("Новые компьютеры сначала запрашивают доступ к серверу. "
                       "Примите запрос — программа покажет 6-значный код; продиктуйте "
                       "его пользователю (по телефону). Отклонить можно на любом шаге. "
                       "Список обновляется автоматически, пока открыта эта вкладка.",
                       11, C['text3'])
        req_hint.setWordWrap(True)
        lay.addWidget(req_hint)

        rc = card(); rl = QVBoxLayout(rc); rl.setContentsMargins(18, 16, 18, 16); rl.setSpacing(8)
        self._req_title = section_lbl("Ожидают подтверждения")
        rl.addWidget(self._req_title)
        #Контейнер строк: на каждом опросе чистим и перезаполняем (как мониторинг).
        self._req_box = QVBoxLayout(); self._req_box.setSpacing(8)
        rl.addLayout(self._req_box)
        self._req_status = lbl("", 11, C['text3']); self._req_status.setWordWrap(True)
        rl.addWidget(self._req_status)
        lay.addWidget(rc)

        lay.addStretch()
        w.setWidget(inner)
        self.pages["requests"] = w; self.stack.addWidget(w)

        #Опрос идёт только пока открыта вкладка (start/stop в _switch).
        self._req_timer = QTimer(self)
        self._req_timer.setInterval(3000)             #раз в 3 секунды
        self._req_timer.timeout.connect(self._poll_requests)

    def _start_requests(self):
        self._req_status.setText("⏳ Запрашиваю список...")
        self._poll_requests()
        self._req_timer.start()

    def _stop_requests(self):
        if getattr(self, "_req_timer", None) is not None:
            self._req_timer.stop()

    def _poll_requests(self):
        """Один цикл опроса /connect/requests токеном текущей сессии (в фоне)."""
        import sync_runner
        url, token = sync_runner.current_auth()
        if not url or not token:
            self._req_status.setText("⏹ Сервер не подключён. Запустите сервер во "
                                     "вкладке «Сервер» и войдите.")
            self._clear_req_rows()
            return

        def _do():
            from sync_client import SyncClient
            return SyncClient(url, token=token).list_connect_requests()

        def _apply(data):
            self._render_requests(data)
            self._req_status.setText("")

        def _err(e):
            self._req_status.setText(f"⚠️ Не удалось получить запросы: {e}")

        self._run_bg(_do, _apply, _err)

    def _clear_req_rows(self):
        while self._req_box.count():
            it = self._req_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _render_requests(self, data):
        rows = (data or {}).get("requests", [])
        self._req_title.setText(f"Ожидают подтверждения: {len(rows)}")
        self._clear_req_rows()
        if not rows:
            self._req_box.addWidget(lbl("— новых запросов нет —", 12, C['text3']))
            return
        for r in rows:
            self._req_box.addWidget(self._make_request_row(r))

    def _make_request_row(self, r: dict) -> QFrame:
        """Строка запроса: IP · имя ПК · статус (+ код, если выдан) и кнопки."""
        dev = r.get("device_id", "")
        ip = r.get("ip", "") or "—"
        host = r.get("hostname", "") or "—"
        issued = r.get("status") == "code_issued"
        f = QFrame(); f.setObjectName("card")
        h = QHBoxLayout(f); h.setContentsMargins(14, 10, 14, 10); h.setSpacing(10)
        info = f"💻 {host}   ·   IP: {ip}"
        if issued and r.get("code"):
            #Код показываем КРУПНО — админ диктует его пользователю.
            info += f"\n🔑 Код: {r['code']}"
        info_lbl = lbl(info, 12, C['text']); info_lbl.setWordWrap(True)
        h.addWidget(info_lbl, 1)
        if not issued:
            b_ok = btn("Принять", "green", icon_name="check")
            b_ok.clicked.connect(lambda _=0, d=dev: self._approve_device(d))
            h.addWidget(b_ok)
        b_no = btn("Отклонить", "red", icon_name="x")
        b_no.clicked.connect(lambda _=0, d=dev: self._reject_device(d))
        h.addWidget(b_no)
        return f

    def _approve_device(self, device_id: str):
        import sync_runner
        url, token = sync_runner.current_auth()
        if not url or not token:
            QMessageBox.warning(self, "Сервер", "Сервер не подключён."); return

        def _do():
            from sync_client import SyncClient
            return SyncClient(url, token=token).approve_device(device_id)

        def _apply(res):
            code = (res or {}).get("code", "")
            if code:
                QMessageBox.information(
                    self, "Код подтверждения",
                    f"Продиктуйте пользователю код:\n\n{code}\n\nОн действует около "
                    "10 минут. Код также виден в строке запроса.")
            self._poll_requests()

        def _err(e):
            QMessageBox.warning(self, "Сервер", f"Не удалось принять запрос: {e}")

        self._run_bg(_do, _apply, _err)

    def _reject_device(self, device_id: str):
        import sync_runner
        url, token = sync_runner.current_auth()
        if not url or not token:
            QMessageBox.warning(self, "Сервер", "Сервер не подключён."); return

        def _do():
            from sync_client import SyncClient
            return SyncClient(url, token=token).reject_device(device_id)

        def _apply(_res):
            self._poll_requests()

        def _err(e):
            QMessageBox.warning(self, "Сервер", f"Не удалось отклонить запрос: {e}")

        self._run_bg(_do, _apply, _err)

    #Сессии и доступ: активные токены + отзыв (чёрный список, данные с /admin/sessions)
    def _build_sessions(self):
        w = QScrollArea(); w.setWidgetResizable(True); w.setStyleSheet("border:none;")
        inner = QWidget(); lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("Сессии и доступ"))
        hint = lbl("Здесь видно, у кого сейчас есть доступ к серверу (выданные токены) и "
                   "с какого устройства. «Отозвать» мгновенно закрывает доступ по токену — "
                   "нужно при увольнении, компрометации учётки, смене группы или роли. "
                   "Токен сам сгорает через 5 часов; refresh-токен продлевает работу тихо, "
                   "но тоже отзывается здесь.", 11, C['text3'])
        hint.setWordWrap(True); lay.addWidget(hint)

        rc = card(); rl = QVBoxLayout(rc); rl.setContentsMargins(18, 16, 18, 16); rl.setSpacing(8)
        self._sess_title = section_lbl("Активные сессии")
        rl.addWidget(self._sess_title)
        self._sess_box = QVBoxLayout(); self._sess_box.setSpacing(8)
        rl.addLayout(self._sess_box)
        self._sess_status = lbl("", 11, C['text3']); self._sess_status.setWordWrap(True)
        rl.addWidget(self._sess_status)
        lay.addWidget(rc)
        lay.addStretch()
        w.setWidget(inner)
        self.pages["sessions"] = w; self.stack.addWidget(w)

        self._sess_timer = QTimer(self)
        self._sess_timer.setInterval(5000)              #раз в 5 секунд
        self._sess_timer.timeout.connect(self._poll_sessions)

    def _start_sessions(self):
        self._sess_status.setText("⏳ Запрашиваю список сессий...")
        self._poll_sessions()
        self._sess_timer.start()

    def _stop_sessions(self):
        if getattr(self, "_sess_timer", None) is not None:
            self._sess_timer.stop()

    def _poll_sessions(self):
        import sync_runner
        url, token = sync_runner.current_auth()
        if not url or not token:
            self._sess_status.setText("⏹ Сервер не подключён. Запустите сервер во "
                                      "вкладке «Сервер» и войдите.")
            self._clear_sess_rows()
            return

        def _do():
            from sync_client import SyncClient
            return SyncClient(url, token=token).list_sessions(active=True)

        def _apply(data):
            self._render_sessions(data)
            self._sess_status.setText("")

        def _err(e):
            self._sess_status.setText(f"⚠️ Не удалось получить сессии: {e}")

        self._run_bg(_do, _apply, _err)

    def _clear_sess_rows(self):
        while self._sess_box.count():
            it = self._sess_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _render_sessions(self, data):
        rows = (data or {}).get("sessions", [])
        #В таблице сессий пара access+refresh на один вход — для админа группируем по
        #логину, чтобы список был компактным (одна строка = один пользователь/устройство).
        by_login = {}
        for s in rows:
            key = (s.get("login", ""), s.get("device_id", ""))
            cur = by_login.get(key)
            #держим строку с наибольшим сроком (обычно refresh) для показа «до когда»
            if cur is None or s.get("expires_in_sec", 0) > cur.get("expires_in_sec", 0):
                by_login[key] = s
        uniq = list(by_login.values())
        self._sess_title.setText(f"Активные сессии: {len(uniq)}")
        self._clear_sess_rows()
        if not uniq:
            self._sess_box.addWidget(lbl("— активных сессий нет —", 12, C['text3']))
            return
        for s in sorted(uniq, key=lambda x: (x.get("role", ""), x.get("login", ""))):
            self._sess_box.addWidget(self._make_session_row(s))

    def _make_session_row(self, s: dict) -> QFrame:
        """Строка сессии: роль · логин · устройство · сколько осталось + «Отозвать»."""
        login = s.get("login", "") or "—"
        role = {"admin": "Администратор", "teacher": "Преподаватель",
                "student": "Студент"}.get(s.get("role", ""), s.get("role", ""))
        dev = (s.get("device_id", "") or "—")
        dev_short = dev[:8] + "…" if len(dev) > 9 else dev
        ip = s.get("ip", "") or "—"
        mins = max(0, int(s.get("expires_in_sec", 0)) // 60)
        left = f"{mins // 60} ч {mins % 60} мин" if mins >= 60 else f"{mins} мин"
        f = QFrame(); f.setObjectName("card")
        h = QHBoxLayout(f); h.setContentsMargins(14, 10, 14, 10); h.setSpacing(10)
        info = (f"👤 {login}  ·  {role}\n💻 {dev_short}  ·  IP: {ip}  ·  доступ ещё ~{left}")
        info_lbl = lbl(info, 12, C['text']); info_lbl.setWordWrap(True)
        h.addWidget(info_lbl, 1)
        b_rev = btn("Отозвать", "red", icon_name="x")
        b_rev.clicked.connect(lambda _=0, lg=s.get("login", ""): self._revoke_login(lg))
        h.addWidget(b_rev)
        return f

    def _revoke_login(self, login: str):
        if not login:
            return
        if QMessageBox.question(
                self, "Отзыв доступа",
                f"Отозвать ВСЕ токены пользователя «{login}»?\n\nОн потеряет доступ к "
                "серверу немедленно и должен будет войти заново.") != QMessageBox.Yes:
            return
        import sync_runner
        url, token = sync_runner.current_auth()
        if not url or not token:
            QMessageBox.warning(self, "Сервер", "Сервер не подключён."); return

        def _do():
            from sync_client import SyncClient
            return SyncClient(url, token=token).revoke_session(login=login)

        def _apply(res):
            n = (res or {}).get("revoked", 0)
            QMessageBox.information(self, "Готово", f"Отозвано токенов: {n}.")
            self._poll_sessions()

        def _err(e):
            QMessageBox.warning(self, "Сервер", f"Не удалось отозвать доступ: {e}")

        self._run_bg(_do, _apply, _err)

    #Мониторинг сервера (только админу; данные с /admin/online и /admin/events)
    def _build_mon(self):
        w = QScrollArea(); w.setWidgetResizable(True); w.setStyleSheet("border:none;")
        inner = QWidget(); lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(title_lbl("Мониторинг сервера"))
        lay.addWidget(lbl("Кто сейчас подключён к серверу и журнал последних действий и "
                          "ошибок. Данные берутся с сервера (доступ только администратору) "
                          "и обновляются автоматически, пока открыта эта вкладка.",
                          11, C['text3']))

        #Кто онлайн
        oc = card(); ol = QVBoxLayout(oc); ol.setContentsMargins(18, 16, 18, 16); ol.setSpacing(8)
        self._mon_online_title = section_lbl("Сейчас онлайн")
        ol.addWidget(self._mon_online_title)
        self._mon_online = QListWidget(); self._mon_online.setMinimumHeight(150)
        ol.addWidget(self._mon_online)
        lay.addWidget(oc)

        #Консоль событий
        ec = card(); el = QVBoxLayout(ec); el.setContentsMargins(18, 16, 18, 16); el.setSpacing(8)
        el.addWidget(section_lbl("Консоль событий"))
        self._mon_console = QTextEdit(); self._mon_console.setReadOnly(True)
        #Ограничиваем число строк — консоль не должна растить память бесконечно.
        self._mon_console.document().setMaximumBlockCount(1000)
        self._mon_console.setStyleSheet(
            f"QTextEdit{{background:{C['card2']};color:{C['text3']};border:1px solid "
            f"{C['border2']};border-radius:8px;font-family:Consolas,'Courier New',"
            "monospace;font-size:12px;padding:8px;}")
        self._mon_console.setMinimumHeight(240)
        el.addWidget(self._mon_console)
        self._mon_status = lbl("", 11, C['text3']); self._mon_status.setWordWrap(True)
        el.addWidget(self._mon_status)
        lay.addWidget(ec)

        #Локальный журнал безопасности ЭТОГО ПК (152-ФЗ): входы, смена пароля,
        #экспорт ПДн. Хранится в зашифрованной БД программы (не открытым файлом),
        #поэтому виден только здесь, у администратора. Это и есть мониторинг доступа.
        ac = card(); al = QVBoxLayout(ac); al.setContentsMargins(18, 16, 18, 16); al.setSpacing(8)
        al.addWidget(section_lbl("Локальный журнал безопасности (этот ПК)"))
        al.addWidget(lbl("События входа, смены пароля и экспорта данных на этом "
                         "компьютере. Журнал зашифрован и хранится внутри программы "
                         "(требование 152-ФЗ).", 11, C['text3']))
        self._mon_audit = QTextEdit(); self._mon_audit.setReadOnly(True)
        self._mon_audit.document().setMaximumBlockCount(1000)
        self._mon_audit.setStyleSheet(
            f"QTextEdit{{background:{C['card2']};color:{C['text3']};border:1px solid "
            f"{C['border2']};border-radius:8px;font-family:Consolas,'Courier New',"
            "monospace;font-size:12px;padding:8px;}")
        self._mon_audit.setMinimumHeight(200)
        al.addWidget(self._mon_audit)
        lay.addWidget(ac)

        lay.addStretch()
        w.setWidget(inner)
        self.pages["mon"] = w; self.stack.addWidget(w)

        #Опрос идёт только пока открыта вкладка (start/stop в _switch) — не дёргаем
        #сервер фоном, когда админ смотрит другие экраны.
        self._mon_since = 0
        self._mon_timer = QTimer(self)
        self._mon_timer.setInterval(4000)             #раз в 4 секунды
        self._mon_timer.timeout.connect(self._poll_monitor)

    def _start_monitor(self):
        """Открыли вкладку: чистим консоль и тянем всё заново, запускаем опрос."""
        self._mon_since = 0
        self._mon_console.clear()
        self._mon_status.setText("⏳ Подключаюсь к серверу...")
        self._refresh_local_audit()
        self._poll_monitor()
        self._mon_timer.start()

    def _refresh_local_audit(self):
        """Перечитывает локальный журнал безопасности (зашифрованный, этот ПК)."""
        from html import escape as _esc
        self._mon_audit.clear()
        try:
            events = read_events(limit=500)
        except Exception as e:
            self._mon_audit.append(f"⚠️ Журнал недоступен: {e}")
            return
        if not events:
            self._mon_audit.append("— записей пока нет —")
            return
        #строки уже в формате «ts \t event \t actor \t detail» — покажем читабельно
        for line in events:
            parts = line.split("\t")
            ts = parts[0] if parts else ""
            ev = parts[1] if len(parts) > 1 else ""
            actor = parts[2] if len(parts) > 2 else ""
            detail = parts[3] if len(parts) > 3 else ""
            tail = f"  ({actor}{' · ' + detail if detail else ''})" if actor or detail else ""
            self._mon_audit.append(_esc(f"[{ts}] {ev}{tail}"))

    def _stop_monitor(self):
        if getattr(self, "_mon_timer", None) is not None:
            self._mon_timer.stop()

    def _poll_monitor(self):
        """Один цикл опроса: тянем /admin/online и /admin/events токеном текущей
        сессии. Сетевую работу — в фоне (_run_bg), чтобы UI не подвисал."""
        import sync_runner
        url, token = sync_runner.current_auth()
        since = self._mon_since
        if not url or not token:
            self._mon_status.setText("⏹ Сервер не подключён. Задайте адрес и войдите "
                                     "(или запустите сервер во вкладке «Сервер»).")
            return

        def _do():
            from sync_client import SyncClient
            c = SyncClient(url, token=token)
            return c.get_online(), c.get_events(since=since)

        def _apply(res):
            online, evts = res
            self._render_online(online)
            self._append_events(evts)
            self._mon_status.setText("")

        def _err(e):
            self._mon_status.setText(f"⚠️ Сервер недоступен или ошибка опроса: {e}")

        self._run_bg(_do, _apply, _err)

    def _render_online(self, data):
        rows = (data or {}).get("online", [])
        self._mon_online_title.setText(f"Сейчас онлайн: {len(rows)}")
        self._mon_online.clear()
        role_ru = {"admin": "Администратор", "teacher": "Преподаватель", "student": "Студент"}
        if not rows:
            self._mon_online.addItem(QListWidgetItem("— сейчас никого —"))
            return
        for r in rows:
            role = role_ru.get(r.get("role", ""), r.get("role", ""))
            name = r.get("name") or r.get("login", "")
            txt = (f"{role} · {name}  ({r.get('login','')})  — был активен "
                   f"{r.get('idle_sec', 0)} c назад")
            if r.get("ip"):
                txt += f"  · {r['ip']}"
            self._mon_online.addItem(QListWidgetItem(txt))

    def _append_events(self, data):
        import time as _t
        from html import escape as _esc
        evts = (data or {}).get("events", [])
        colors = {"error": C['red'], "warn": C['orange'], "info": C['text2']}
        for e in evts:
            ts = _t.strftime("%H:%M:%S", _t.localtime(e.get("ts", 0)))
            lvl = e.get("level", "info")
            who, ip = e.get("login", ""), e.get("ip", "")
            tail = f"  ({who}{'@' + ip if ip else ''})" if (who or ip) else ""
            line = f"[{ts}] {lvl.upper():<5} {e.get('kind','')}: {e.get('message','')}{tail}"
            self._mon_console.append(
                f'<span style="color:{colors.get(lvl, C["text3"])}">{_esc(line)}</span>')
        if evts:
            self._mon_since = (data or {}).get("last_id", self._mon_since)

    def _switch(self, key):
        if getattr(self, '_switching', False):
            return
        self._switching = True
        try:
            self._stop_monitor()      #уходя с любой вкладки — гасим опрос мониторинга
            self._stop_requests()     #и опрос запросов на подключение
            self._stop_registrations() #и опрос заявок на регистрацию
            self._stop_sessions()     #и опрос активных сессий
            if key == "dash":     self._refresh_dash()
            if key == "teachers": self._render_teachers()
            if key == "students": self._refresh_students_combo(); self._render_students()
            if key == "groups":   self._render_groups()
            if key == "subjects": self._render_subjects()
            if key == "api":      self._refresh_vector_cfg()
            if key == "pg":       self._refresh_server_status(); self._refresh_compliance()
            if key == "reg":      self._start_registrations()
            if key == "requests": self._start_requests()
            if key == "sessions": self._start_sessions()
            if key == "mon":      self._start_monitor()
            #Шторка Вектора прячется на вкладке «ИИ», возвращается на остальных.
            dock = getattr(self, "vector_dock", None)
            if dock is not None:
                dock.suspend() if key == "ai" else dock.resume()
            if key in self.pages:
                self.stack.setCurrentWidget(self.pages[key])
                self.sidebar.set_active(key)
                self._current_key = key
        finally:
            self._switching = False

    def refresh(self):
        """Перерисовать текущую вкладку — вызывается после фоновой синхронизации,
        чтобы свежие данные с сервера сразу появились на экране."""
        key = getattr(self, "_current_key", "dash")
        if key == "dash":     self._refresh_dash()
        elif key == "teachers": self._render_teachers()
        elif key == "students": self._render_students()
        elif key == "groups":   self._render_groups()
        elif key == "subjects": self._render_subjects()

    def _refresh_students_combo(self):
        """Обновить список групп в фильтре студентов (фоновая загрузка)."""
        def _fetch():
            gh = get_store()
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
