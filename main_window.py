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

        #Сессия (роль + данные) текущего входа — нужна, чтобы пересобрать дашборд
        #при смене темы (reapply_current). None — пока никто не вошёл.
        self._session = None

        #Тема оформления вуза — применяем ДО построения экрана входа, чтобы и он был
        #в нужной палитре. Источник — общий config (если админ уже задал тему).
        self._apply_theme_startup()

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

    def _apply_theme_startup(self):
        """Применить тему вуза (или дефолт) до показа экрана входа."""
        try:
            import theme_service
            import styles
            theme_service.apply_startup_default()
            self.setStyleSheet(styles.APP_STYLE)
        except Exception as e:
            print(f"[theme] стартовая тема пропущена: {e}")

    def _session_identity(self):
        """(role, identity) текущей сессии для theme_service ('', {} — не вошёл)."""
        if not self._session:
            return "", {}
        role, payload = self._session
        if role == "student":
            return role, {"f": payload.get("f", ""), "n": payload.get("n", ""),
                          "g": payload.get("g", "")}
        if role == "teacher":
            name, _data = payload
            return role, {"name": name}
        return role, {}

    def _apply_session_theme(self):
        """Выбрать и применить тему вошедшего пользователя (до сборки дашборда)."""
        try:
            import theme_service
            import styles
            role, identity = self._session_identity()
            if role:
                theme_service.resolve_and_apply(role, identity)
                self.setStyleSheet(styles.APP_STYLE)
        except Exception as e:
            print(f"[theme] тема пользователя пропущена: {e}")

    def _build_dashboard(self):
        """Создаёт виджет дашборда по текущей сессии (роль + данные)."""
        role, payload = self._session
        if role == "student":
            return StudentDashboard(payload), ("Ученик", f"{payload['f']} {payload['n']}")
        if role == "teacher":
            name, data = payload
            if TeacherDashboard is None:
                raise RuntimeError("Модуль TeacherDashboard не загружен")
            #показываем ПОЛНОЕ ФИО (раньше была только фамилия name.split()[0]);
            #длинные ФИО шапка сама укоротит эллипсисом (ElidingLabel)
            return TeacherDashboard(name, data), ("Учитель", name)
        if role == "admin":
            if AdminDashboard is None:
                raise RuntimeError("Модуль AdminDashboard не загружен")
            return (AdminDashboard(back_to_login_cb=self._logout),
                    ("Администратор", "Администратор"))
        raise RuntimeError(f"Неизвестная роль: {role}")

    def _open_dashboard(self):
        """Применяет тему, собирает дашборд текущей сессии и показывает его.
        Используется и при входе, и при пересборке после смены темы."""
        #тему ставим ДО сборки — первая отрисовка сразу в нужной палитре
        self._apply_session_theme()
        #убираем прежние дашборды (всё, кроме страницы входа — она всегда первая)
        while self._stack.count() > 1:
            w = self._stack.widget(self._stack.count() - 1)
            self._stack.removeWidget(w)
            w.deleteLater()
        dash, (role_text, user_text) = self._build_dashboard()
        self._stack.addWidget(dash)
        self._stack.setCurrentWidget(dash)
        #шапка создаётся один раз и не пересобирается с дашбордом — красим её явно
        self._header.refresh_theme()
        self._header.set_role(role_text, user_text)
        self._header.show()

    def reapply_current(self):
        """Пересобрать текущий дашборд (после «Сохранить» в кастомизации) — чтобы
        новая тема применилась целиком, включая инлайн-стили уже собранных виджетов."""
        if not self._session:
            return
        try:
            self._open_dashboard()
        except Exception as e:
            print(f"[theme] пересборка интерфейса не удалась: {e}")

    def _on_synced(self):
        """Пришли свежие данные с сервера — обновляем текущий экран, если умеет.
        Заодно догоняем тему: персональную с другого ПК или новую тему вуза."""
        #Если тема пользователя/вуза изменилась на сервере — переприменяем и
        #пересобираем интерфейс (а не просто refresh данных).
        try:
            import theme_service
            role, identity = self._session_identity()
            if role and theme_service.on_sync_refresh(role, identity):
                self.reapply_current()
                return
        except Exception as e:
            print(f"[theme] обновление темы по синку: {e}")
        w = self._stack.currentWidget()
        if hasattr(w, "refresh"):
            try:
                w.refresh()
            except Exception as e:
                print(f"[sync] обновление экрана: {e}")

    def _on_student_login(self, stud: dict):
        """Обработать вход студента"""
        try:
            self._session = ("student", stud)
            self._open_dashboard()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть журнал:\n{e}")

    def _on_teacher_login(self, name: str, data: dict):
        """Обработать вход учителя"""
        try:
            if TeacherDashboard is None:
                QMessageBox.warning(self, "Ошибка", "Модуль TeacherDashboard не загружен")
                return
            self._session = ("teacher", (name, data))
            self._open_dashboard()
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
            self._session = ("admin", None)
            self._open_dashboard()
        except Exception as e:
            import traceback
            traceback.print_exc()  # полный стек в консоль
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть панель администратора:\n{e}")

    def _logout(self):
        """Выход из системы"""
        self._session = None   #сессия закрыта — пересобирать по теме больше нечего
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
