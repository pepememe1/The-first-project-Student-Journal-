"""
main_window.py — Главное окно приложения
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStackedWidget, QMessageBox
)

from core import APP_VERSION
from styles import APP_STYLE, COLLEGE_NAME
from ui_components import HeaderBar
from auth_pages import LoginPage, AdminLoginPage
from dashboards import StudentDashboard
from utils import parse_logins
from data_store import get_store as get_gh_store

# Импорты для Teacher и Admin Dashboard (создадим отдельно)
try:
    from teacher_dashboard import TeacherDashboard
except ImportError:
    TeacherDashboard = None

try:
    from admin_dashboard import AdminDashboard
except ImportError:
    AdminDashboard = None


#  MAIN APP WINDOW

class MainAppWindow(QMainWindow):
    """Главное окно приложения GradeBookAI"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GradeBookAI · {COLLEGE_NAME} — {APP_VERSION}")
        self.resize(1300, 760)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(APP_STYLE)

        # Загрузить базу учителей
        self.teachers_db, _ = parse_logins()
        
        # Стек виджетов для переключения между страницами
        self._stack = QStackedWidget()

        # Верхняя панель (скрыта на странице входа)
        self._header = HeaderBar()
        self._header.logout_clicked.connect(self._logout)
        self._header.hide()

        # Обёртка (заголовок + содержимое)
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(self._header)
        wl.addWidget(self._stack, 1)
        self.setCentralWidget(wrapper)

        # Страница входа студента/учителя
        self._login = LoginPage(self.teachers_db)
        self._login.login_student.connect(self._on_student_login)
        self._login.login_teacher.connect(self._on_teacher_login)
        self._login.login_admin.connect(self._on_admin_login)
        self._stack.addWidget(self._login)

        # Страница входа администратора
        self._admin_login = AdminLoginPage()
        self._admin_login.login_success.connect(self._on_admin_login)
        self._admin_login.back_btn.clicked.connect(lambda: self._stack.setCurrentWidget(self._login))
        self._stack.addWidget(self._admin_login)

        # Начальное состояние — страница входа
        self._stack.setCurrentWidget(self._login)

    def _on_student_login(self, stud: dict):
        """Обработать вход студента"""
        try:
            dash = StudentDashboard(stud)
            self._stack.addWidget(dash)
            self._stack.setCurrentWidget(dash)
            self._header.set_role("Ученик", f"{stud['f']} {stud['n']}")
            self._header.show()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть журнал:\n{e}")

    def _on_teacher_login(self, name: str, data: dict):
        """Обработать вход учителя"""
        try:
            if TeacherDashboard is None:
                QMessageBox.warning(self, "Ошибка", "Модуль TeacherDashboard не загружен")
                return
            
            dash = TeacherDashboard(name, data)
            self._stack.addWidget(dash)
            self._stack.setCurrentWidget(dash)
            self._header.set_role("Учитель", name.split()[0])
            self._header.show()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть журнал:\n{e}")

    def _on_admin_trigger(self):
        """Переключиться на страницу входа администратора (скрытый триггер)"""
        self._stack.setCurrentWidget(self._admin_login)

    def _on_admin_login(self):
        """Обработать вход администратора"""
        try:
            if AdminDashboard is None:
                QMessageBox.warning(self, "Ошибка", "Модуль AdminDashboard не загружен")
                return

            print("[DEBUG] Создание AdminDashboard...")
            dash = AdminDashboard(back_to_login_cb=self._logout)
            print("[DEBUG] AdminDashboard создан успешно")

            self._stack.addWidget(dash)
            self._stack.setCurrentWidget(dash)
            self._header.set_role("Администратор", "Администратор")
            self._header.show()
        except Exception as e:
            import traceback
            traceback.print_exc()  # полный стек в консоль
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть панель администратора:\n{e}")

    def _logout(self):
        """Выход из системы"""
        # Удалить все виджеты, кроме входа и админ входа
        while self._stack.count() > 2:
            w = self._stack.widget(self._stack.count() - 1)
            self._stack.removeWidget(w)
            w.deleteLater()
        
        self._stack.setCurrentWidget(self._login)
        self._header.hide()
        
        # Обновить базу учителей
        self.teachers_db, _ = parse_logins()
        self._login.update_teachers(self.teachers_db)
