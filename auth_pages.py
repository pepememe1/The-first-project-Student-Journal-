"""
auth_pages.py — Страница аутентификации (LoginPage).

Вход единый: студент / преподаватель / администратор определяются по логину и
паролю автоматически. При первом запуске на главном ПК, если пароль администратора
ещё не задан, форма предложит его создать (см. _prompt_admin_setup).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QFrame, QInputDialog
)

from styles import C
from ui_components import HexLogoWidget, AnimatedBackground


#  LOGIN PAGE (STUDENT & TEACHER)

class LoginPage(QWidget):
    """Страница входа для студентов и учителей"""
    
    from PySide6.QtCore import Signal as QSignal
    login_student = QSignal(dict)
    login_teacher = QSignal(str, dict)
    login_admin   = QSignal()

    def __init__(self, teachers_db: dict, parent=None):
        super().__init__(parent)
        self.teachers_db   = teachers_db
        self._role         = "student"

        # Animated background
        self._bg = AnimatedBackground(self)
        self._bg.lower()

        # Main layout
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        outer.setContentsMargins(0, 0, 0, 0)

        # Card frame
        c = QFrame()
        c.setObjectName("loginCard")
        c.setFixedWidth(420)
        c.setStyleSheet(
            "QFrame#loginCard{"
            f"  background:#FFFFFF;"
            f"  border:1px solid {C['border2']};"
            "  border-radius:18px;"
            "}"
        )
        lay = QVBoxLayout(c)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(12)

        # Logo
        hex_w = HexLogoWidget(54)
        hex_w.setFixedSize(54, 54)
        hex_row = QHBoxLayout()
        hex_row.setAlignment(Qt.AlignCenter)
        hex_row.addWidget(hex_w)
        lay.addLayout(hex_row)

        # Title
        t_lbl = QLabel("GradeBookAI")
        t_lbl.setAlignment(Qt.AlignCenter)
        t_lbl.setStyleSheet(
            f"font-size:24px;font-weight:800;color:{C['text']};"
            "margin-top:6px;margin-bottom:0px;"
        )
        
        sub_lbl = QLabel("Система учёта успеваемости")
        sub_lbl.setAlignment(Qt.AlignCenter)
        sub_lbl.setStyleSheet(f"font-size:12px;color:{C['text3']};margin-bottom:0px;")
        college_lbl = QLabel("Технологический колледж ВСГУТУ")
        college_lbl.setAlignment(Qt.AlignCenter)
        college_lbl.setStyleSheet(
            f"font-size:12px;font-weight:700;color:{C['green']};margin-bottom:4px;"
        )
        lay.addWidget(t_lbl)
        lay.addWidget(sub_lbl)
        lay.addWidget(college_lbl)

        # Поля входа: логин + пароль
        lay.addSpacing(6)
        lay.addWidget(self._mk_label("Логин"))
        self.login_inp = self._mk_input("Введите логин")
        lay.addWidget(self.login_inp)
        lay.addSpacing(8)
        lay.addWidget(self._mk_label("Пароль"))
        self.pass_inp = self._mk_input("••••••••", password=True)
        lay.addWidget(self.pass_inp)
        lay.addSpacing(12)
        b_go = self._mk_btn("Войти")
        b_go.clicked.connect(self._do_login)
        self.login_inp.returnPressed.connect(self._do_login)
        self.pass_inp.returnPressed.connect(self._do_login)
        lay.addWidget(b_go)

        # Сообщение об ошибке
        self.err_lbl = QLabel("")
        self.err_lbl.setWordWrap(True)
        self.err_lbl.setStyleSheet(
            f"color:{C['red']};background:rgba(200,69,62,0.08);"
            f"border:1px solid rgba(200,69,62,0.25);border-radius:8px;"
            "padding:8px 12px;font-size:12px;margin-top:4px;"
        )
        self.err_lbl.hide()
        lay.addWidget(self.err_lbl)

        # Подсказка: студенты и преподаватели входят по выданным логину/паролю.
        hint = QLabel("Студенты и преподаватели входят по логину и паролю, "
                      "которые выдал администратор.")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color:{C['text3']};font-size:11px;margin-top:8px;")
        lay.addWidget(hint)

        outer.addWidget(c)

    # ── Helper methods
    def _mk_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{C['text3']};font-size:11px;font-weight:600;"
            "margin-bottom:0px;"
        )
        return l

    def _mk_input(self, placeholder: str, password=False) -> QLineEdit:
        f = QLineEdit()
        f.setPlaceholderText(placeholder)
        if password:
            f.setEchoMode(QLineEdit.Password)
        f.setFixedHeight(40)
        f.setStyleSheet(
            f"QLineEdit{{"
            f"  background:{C['card2']};"
            f"  border:1px solid {C['border2']};"
            f"  border-radius:9px;"
            f"  padding:0px 12px;"
            f"  font-size:13px;"
            f"  color:{C['text']};"
            f"}}"
            f"QLineEdit:focus{{"
            f"  border:1px solid {C['green']};"
            f"  background:{C['card']};"
            f"}}"
        )
        return f

    def _mk_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setFixedHeight(42)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{C['green']};color:#FFFFFF;"
            "border:none;border-radius:10px;"
            "font-size:14px;font-weight:600;}"
            f"QPushButton:hover{{background:{C['green2']};}}"
            "QPushButton:pressed{background:#0E6271;}"
        )
        return b

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bg.setGeometry(0, 0, self.width(), self.height())

    def _show_err(self, msg):
        self.err_lbl.setText(msg)
        self.err_lbl.show()

    def _do_login(self):
        """Единый вход по логину и паролю. Роль определяется автоматически."""
        self.err_lbl.hide()
        login = self.login_inp.text().strip()
        pw    = self.pass_inp.text()
        if not login:
            self._show_err("Введите логин")
            return

        from data_store import get_store, AccountLocked
        store = get_store()

        # Первый запуск на хост-ПК: пароль администратора ещё не задан. Просим
        # администратора задать его прямо сейчас. На остальных ПК конфиг приходит
        # из PostgreSQL уже с хешем, поэтому эта ветка там не сработает.
        if login == store.get_admin_login() and not store.has_admin_password():
            self._prompt_admin_setup(store)
            return

        try:
            res = store.authenticate(login, pw)
        except AccountLocked as e:
            mins = e.seconds // 60 + 1
            self._show_err(f"Слишком много неверных попыток. "
                           f"Повторите через {mins} мин.")
            return
        except Exception as e:
            self._show_err(f"Ошибка входа: {e}")
            return
        if not res:
            self._show_err("Неверный логин или пароль")
            return
        self.login_inp.clear()
        self.pass_inp.clear()
        role = res.get("role")
        if role == "admin":
            self.login_admin.emit()
        elif role == "teacher":
            self.login_teacher.emit(res["name"], res["data"])
        elif role == "student":
            self.login_student.emit(res["stud"])

    def _prompt_admin_setup(self, store):
        """Диалог первичной установки пароля администратора (только хост-ПК)."""
        QMessageBox.information(
            self, "Первый запуск",
            "Пароль администратора ещё не задан. Сейчас нужно его создать — "
            "это делается один раз на главном ПК. Остальные компьютеры получат "
            "доступ автоматически после синхронизации.")
        pw1, ok = QInputDialog.getText(
            self, "Пароль администратора",
            "Придумайте пароль (не менее 8 символов):", QLineEdit.Password)
        if not ok:
            return
        if len(pw1) < 8:
            self._show_err("Пароль должен быть не короче 8 символов")
            return
        pw2, ok = QInputDialog.getText(
            self, "Подтверждение", "Повторите пароль:", QLineEdit.Password)
        if not ok:
            return
        if pw1 != pw2:
            self._show_err("Пароли не совпадают")
            return
        if store.setup_admin_password(pw1):
            from audit import log_event
            log_event("admin_password_created", store.get_admin_login())
            self.login_inp.clear()
            self.pass_inp.clear()
            QMessageBox.information(self, "Готово", "Пароль администратора создан.")
            self.login_admin.emit()
        else:
            self._show_err("Не удалось сохранить пароль (возможно, он уже задан)")

    def update_teachers(self, db):
        self.teachers_db = db
