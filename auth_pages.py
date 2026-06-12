"""
auth_pages.py — Страницы аутентификации (LoginPage, AdminLoginPage)
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, 
    QStackedWidget, QMessageBox, QFrame, QSizePolicy
)

from styles import C
from widgets import lbl, badge, btn, field_input
from ui_components import HexLogoWidget, AnimatedBackground
from utils import parse_logins
from data_store import get_store as get_gh_store


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
        self._secret_cnt   = 0
        self._secret_timer = QTimer()
        self._secret_timer.setSingleShot(True)
        self._secret_timer.timeout.connect(lambda: setattr(self, "_secret_cnt", 0))

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

        outer.addWidget(c)

        # Secret trigger for admin (invisible corner button)
        self._secret = QPushButton(self)
        self._secret.setFixedSize(14, 14)
        self._secret.setStyleSheet("QPushButton{background:transparent;border:none;}")
        self._secret.clicked.connect(self._secret_click)
        self._secret.raise_()

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
        self._secret.move(4, self.height() - 18)

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
        try:
            from data_store import get_store
            res = get_store().authenticate(login, pw)
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

    def _secret_click(self):
        """Зарезервировано. Вход администратора — через обычную форму (логин/пароль)."""
        pass

    def update_teachers(self, db):
        self.teachers_db = db


#  ADMIN LOGIN PAGE

class AdminLoginPage(QWidget):
    """Страница входа администратора"""
    
    from PySide6.QtCore import Signal as QSignal
    login_success = QSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        
        from widgets import card
        
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        
        c = card()
        c.setFixedWidth(400)
        lay = QVBoxLayout(c)
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(14)
        
        # Emoji icon
        emoji = QLabel("🔐")
        emoji.setAlignment(Qt.AlignCenter)
        emoji.setStyleSheet("font-size:42px;")
        lay.addWidget(emoji)
        
        # Title
        t = QLabel("Администратор")
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(f"font-size:22px;font-weight:800;color:{C['text']};")
        lay.addWidget(t)
        
        lay.addWidget(lbl("Введите пароль администратора", 12, C['text3']))
        
        self.pw = field_input("Пароль", password=True)
        self.pw.returnPressed.connect(self._login)
        lay.addWidget(self.pw)
        
        self.err = lbl("", 12, C['red'])
        self.err.hide()
        lay.addWidget(self.err)
        
        b_row = QHBoxLayout()
        back = btn("← Назад", "back")
        back.clicked.connect(lambda: self.pw.clear() or self.err.hide())
        go   = btn("Войти", "green")
        go.clicked.connect(self._login)
        self.back_btn = back
        b_row.addWidget(back)
        b_row.addWidget(go)
        lay.addLayout(b_row)
        
        outer.addWidget(c)

    def _login(self):
        pw = self.pw.text()
        ok = False
        try:
            from data_store import get_store
            ok = get_store().check_admin_password(pw)
        except Exception:
            ok = False

        if ok:
            self.pw.clear()
            self.err.hide()
            self.login_success.emit()
        else:
            self.err.setText("Неверный пароль")
            self.err.show()
