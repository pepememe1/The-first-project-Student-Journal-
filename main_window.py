"""
main_window.py — Главное окно приложения
"""

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStackedWidget, QMessageBox
)


class _SyncBridge(QObject):
    """Мост из фонового потока синхронизации в UI-поток. Сигнал, испускаемый из
    другого потока, Qt безопасно доставит в слот UI (очередью)."""
    synced = Signal()

from core import APP_VERSION
from styles import APP_STYLE, COLLEGE_NAME
from ui_components import HeaderBar
from auth_pages import LoginPage
from dashboards import StudentDashboard
from utils import parse_logins

#Импорты для Teacher и Admin Dashboard (создадим отдельно)
try:
    from teacher_dashboard import TeacherDashboard
except ImportError:
    TeacherDashboard = None

try:
    from admin_dashboard import AdminDashboard
except ImportError:
    AdminDashboard = None


#MAIN APP WINDOW

class MainAppWindow(QMainWindow):
    """Главное окно приложения GradeBookAI"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GradeBookAI · {COLLEGE_NAME} — {APP_VERSION}")
        self.resize(1300, 760)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(APP_STYLE)

        #Загрузить базу учителей
        self.teachers_db, _ = parse_logins()
    
        #Стек виджетов для переключения между страницами
        self._stack = QStackedWidget()

        #Верхняя панель (скрыта на странице входа)
        self._header = HeaderBar()
        self._header.logout_clicked.connect(self._logout)
        self._header.hide()

        #Обёртка (заголовок + содержимое)
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(self._header)
        wl.addWidget(self._stack, 1)
        self.setCentralWidget(wrapper)

        #Единая страница входа: роль (студент / преподаватель / администратор)
        #определяется по логину и паролю автоматически. Отдельной страницы для
        #администратора больше нет — вход у всех через одну форму.
        self._login = LoginPage(self.teachers_db)
        self._login.login_student.connect(self._on_student_login)
        self._login.login_teacher.connect(self._on_teacher_login)
        self._login.login_admin.connect(self._on_admin_login)
        self._stack.addWidget(self._login)

        #Начальное состояние — страница входа
        self._stack.setCurrentWidget(self._login)

        #Авто-обновление UI после фоновой синхронизации (если включён сервер).
        self._sync_bridge = _SyncBridge()
        self._sync_bridge.synced.connect(self._on_synced)
        try:
            from sync_runner import set_on_synced
            set_on_synced(self._sync_bridge.synced.emit)
        except Exception as e:
            print(f"[sync] мост обновления UI не подключён: {e}")

        #Авто-бэкап по расписанию. Раньше бэкап делался только «на выходе» — при
        #аварийном завершении (зависание/выключение ПК) данные за сессию терялись бы.
        #Таймер тикает чаще интервала, а backup_if_due троттлит до раза в 30 минут.
        #Работает независимо от сервера (защищает локальную базу в любом режиме).
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._auto_backup)
        self._backup_timer.start(10 * 60 * 1000)        #тик раз в 10 минут
        QTimer.singleShot(5000, self._auto_backup)       #и один бэкап вскоре после старта

        #Стартовая проверка адреса сервера. singleShot(0) — показываем уже после
        #появления окна, а не в конструкторе. Само окно решает, показываться ли
        #(не трогает админа/хост и офлайн-режим) — см. _maybe_prompt_server.
        QTimer.singleShot(0, self._maybe_prompt_server)

    def _maybe_prompt_server(self):
        """Однократно предлагает ввести адрес сервера на свежем клиентском ПК.

        НЕ показываем, если адрес уже задан, это ПК-хоста (там админ сам поднимает
        сервер — иначе замкнутый круг) или пользователь осознанно выбрал офлайн."""
        try:
            from app_settings import has_api_url, is_host, get_offline_ack
            if has_api_url() or is_host() or get_offline_ack():
                return
            from auth_pages import ask_server_address
            ask_server_address(self, first_run=True)
        except Exception as e:
            print(f"[startup] окно адреса сервера пропущено: {e}")

    def _auto_backup(self):
        """Периодический бэкап локальной базы (троттлится по времени в DBManager)."""
        try:
            from core import DBManager
            DBManager.backup_if_due()
        except Exception as e:
            print(f"[backup] авто-бэкап: {e}")

    def _on_synced(self):
        """Пришли свежие данные с сервера — обновляем текущий экран, если умеет."""
        w = self._stack.currentWidget()
        if hasattr(w, "refresh"):
            try:
                w.refresh()
            except Exception as e:
                print(f"[sync] обновление экрана: {e}")

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

    def _on_admin_login(self):
        """Обработать вход администратора"""
        #Этот ПК — хост (администратор поднимает сервер именно здесь). Помечаем, чтобы
        #стартовое окно «введите адрес сервера» больше не доставало админа: адрес ведь
        #появляется ПОСЛЕ запуска сервера — иначе вышел бы замкнутый круг.
        try:
            from app_settings import mark_host
            mark_host()
        except Exception:
            pass
        try:
            if AdminDashboard is None:
                QMessageBox.warning(self, "Ошибка", "Модуль AdminDashboard не загружен")
                return

            dash = AdminDashboard(back_to_login_cb=self._logout)
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
        #Останавливаем фоновую синхронизацию текущего пользователя.
        try:
            from sync_runner import stop as _sync_stop
            _sync_stop()
        except Exception:
            pass
        #Удалить все виджеты, кроме страницы входа (она всегда первая в стеке)
        while self._stack.count() > 1:
            w = self._stack.widget(self._stack.count() - 1)
            self._stack.removeWidget(w)
            w.deleteLater()

        self._stack.setCurrentWidget(self._login)
        self._header.hide()
        
        #Обновить базу учителей
        self.teachers_db, _ = parse_logins()
        self._login.update_teachers(self.teachers_db)
