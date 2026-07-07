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
    #Восстановление сессии идёт в фоновом потоке (сеть), а собирать дашборд/возвращать
    #на экран входа можно только в UI-потоке — поэтому через сигналы.
    restore_local = Signal(str)   #данные готовы (после реконсиляции/офлайн) — собрать дашборд по логину
    show_login = Signal()         #восстановить не удалось (токен протух) — оставить вход
    state = Signal(bool, str)     #смена онлайн/офлайн синка (для индикатора в шапке)

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

        #Идёт ли сейчас восстановление сохранённой сессии (персистентный вход). Пока
        #True — не дёргаем окно подключения (см. _maybe_prompt_server).
        self._session_restoring = False

        #Авто-обновление UI после фоновой синхронизации (если включён сервер).
        self._sync_bridge = _SyncBridge()
        self._sync_bridge.synced.connect(self._on_synced)
        self._sync_bridge.restore_local.connect(self._restore_from_local)
        self._sync_bridge.show_login.connect(self._restore_failed)
        self._sync_bridge.state.connect(self._on_sync_state)
        try:
            from sync_runner import set_on_synced, set_on_state
            set_on_synced(self._sync_bridge.synced.emit)
            set_on_state(self._sync_bridge.state.emit)
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

        #Тёмная тема ПО РАСПИСАНИЮ: раз в минуту проверяем, не наступило ли время
        #переключиться (напр. 18:00 → тёмная). Реальная отрисовка режима уже зависит
        #от времени (themes.effective_mode), здесь лишь ловим МОМЕНТ перехода и
        #пересобираем интерфейс. _applied_mode — последний применённый режим.
        self._applied_mode = None
        self._theme_timer = QTimer(self)
        self._theme_timer.timeout.connect(self._tick_theme_schedule)
        self._theme_timer.start(60 * 1000)               #тик раз в минуту

        #На ПК-хосте сначала сам поднимаем его сервер (постоянная связь — см.
        #_maybe_autostart_server), и только потом — стартовая проверка адреса.
        QTimer.singleShot(0, self._maybe_autostart_server)

        #Персистентный вход: если есть сохранённая сессия — восстанавливаем её (с
        #реконсиляцией данных от сервера). Ставится ДО _maybe_prompt_server: если сессия
        #восстанавливается, окно подключения не показываем.
        QTimer.singleShot(0, self._maybe_restore_session)

        #Стартовая проверка адреса сервера. singleShot(0) — показываем уже после
        #появления окна, а не в конструкторе. Само окно решает, показываться ли
        #(не трогает админа/хост и офлайн-режим) — см. _maybe_prompt_server.
        QTimer.singleShot(0, self._maybe_prompt_server)

        #Авто-обновление расписания при старте: подтягиваем свежий снимок с портала
        #ВСГУТУ в фоне, чтобы вкладка «Расписание» открылась уже актуальной. Запускаем
        #чуть погодя после показа окна, чтобы не тормозить старт.
        QTimer.singleShot(3000, self._maybe_refresh_schedule)

    def _maybe_refresh_schedule(self):
        """Фоновое авто-обновление кэша расписания при запуске программы.

        Тянем расписание с публичного портала и кладём в локальный кэш. Чтобы не
        дёргать портал на КАЖДЫЙ запуск (десятки GET), обновляем только если кэша нет
        или он старше порога (расписание меняется редко). Сеть — в отдельном потоке
        (UI не блокируем); офлайн/ошибка — тихо выходим, остаётся прежний кэш."""
        try:
            import schedule as sched
        except Exception as e:
            print(f"[schedule] модуль расписания недоступен: {e}")
            return
        #Порог свежести: если кэшу меньше 3 часов — не обновляем (хватает).
        age = sched.cache_age_minutes()
        if age is not None and age < 180:
            return

        from PySide6.QtCore import QThread

        class _SchedRefreshThread(QThread):
            def run(self_inner):
                try:
                    snap = sched.build_snapshot()
                    sched.save(snap)
                    print(f"[schedule] авто-обновление: групп {len(snap.group_names())}, "
                          f"предметов {len(snap.subjects)}")
                except Exception as ex:
                    print(f"[schedule] авто-обновление пропущено: {ex}")

        self._sched_thread = _SchedRefreshThread(self)   # держим ссылку (GC)
        self._sched_thread.start()

    def _maybe_autostart_server(self):
        """ПК-хост сам поднимает свой сервер при старте программы (постоянная связь).

        Зачем. Раньше сервер жил только пока администратор держал свою сессию: вышел
        из аккаунта или закрыл и открыл программу — сервер для всех «отваливался», и
        админу приходилось каждый раз снова входить и жать «Запустить сервер». Теперь,
        если этот ПК уже был хостом и автозапуск включён (его ставит удачный запуск из
        админки), сервер поднимается сам — в фоне, ДО и НЕЗАВИСИМО от входа. Админ
        спокойно выходит из аккаунта: сервер живёт в фоновом потоке до закрытия
        программы, а после перезапуска встаёт заново сам."""
        try:
            from app_settings import is_host, host_autostart_enabled
            if not (is_host() and host_autostart_enabled()):
                return
        except Exception as e:
            print(f"[server] проверка автозапуска пропущена: {e}")
            return

        import threading

        def _do():
            #Поднимаем сервер в фоновом потоке: старт uvicorn + (для serveo) туннеля
            #может занять секунды, а UI блокировать нельзя.
            try:
                import server_control
                import app_settings
                ok, url, msg = server_control.autostart()
                if ok and url:
                    app_settings.set_api_url(url)
                    try:
                        import sync_runner
                        sync_runner.trigger()   #разбудить синк — адрес уже есть
                    except Exception:
                        pass
                print(f"[server] автозапуск хоста: {msg}")
            except Exception as e:
                print(f"[server] автозапуск хоста пропущен: {e}")

        threading.Thread(target=_do, daemon=True).start()

    #Персистентный вход + реконсиляция данных с сервером
    def _maybe_restore_session(self):
        """Восстанавливает сохранённую сессию при старте (персистентный вход).

        Логика «сервер = истина, только онлайн»:
          • ХОСТ (админ) — источник данных для сервера: НЕ реконсилим, восстанавливаем
            из локали, синк подключится сам.
          • КЛИЕНТ — в фоне проверяем токен и, если сервер доступен, делаем реконсиляцию
            (стереть локальный кэш + полный pull), чтобы убрать «осиротевшие» записи
            прошлых сессий; офлайн — восстанавливаем из локали (offline-first); токен
            протух (401) — возвращаемся на экран входа."""
        try:
            from app_settings import get_saved_session, is_host
            sess = get_saved_session()
        except Exception as e:
            print(f"[restore] сохранённая сессия не прочитана: {e}")
            return
        login = (sess or {}).get("login", "")
        role = (sess or {}).get("role", "")
        if not login:
            return
        #Синхронно (до сетевых задержек) помечаем восстановление, чтобы окно подключения
        #не выскочило параллельно.
        self._session_restoring = True

        if is_host():
            #Хост: данные локальные и авторитетные — просто собираем дашборд.
            self._restore_from_local(login)
            return

        import threading
        threading.Thread(target=self._restore_client_bg, args=(login,), daemon=True).start()

    def _restore_client_bg(self, login: str):
        """Фоновая часть восстановления клиента: проверка токена + реконсиляция.
        UI трогаем только через сигналы моста (restore_local / show_login)."""
        from datetime import datetime, timezone
        try:
            from app_settings import (get_api_url, get_saved_token,
                                      clear_saved_session, clear_saved_token)
            url = get_api_url()
            token = get_saved_token(login)
            #Нет адреса/токена — работаем офлайн: восстановим из локали (если есть данные).
            if not url or not token:
                self._sync_bridge.restore_local.emit(login)
                return
            from sync_client import SyncClient
            c = SyncClient(url, token=token)
            #Сервер недоступен — offline-first: не трогаем локаль, собираем из неё.
            if not c.health():
                self._sync_bridge.restore_local.emit(login)
                return
            #Лёгкий pull проверяет токен (200 — жив; 401/403 — исключение). Берём
            #«сейчас» как since, чтобы вернулось почти пусто (это только проверка).
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                c.pull(since=now_iso)
            except Exception:
                #Токен протух / устройство не одобрено — чистим сессию, на экран входа.
                clear_saved_session(); clear_saved_token()
                self._sync_bridge.show_login.emit()
                return
            #Токен жив и сервер на месте — реконсиляция: стереть кэш + полный pull.
            import sync_engine
            sync_engine.reconcile(c)
            self._sync_bridge.restore_local.emit(login)
        except Exception as e:
            print(f"[restore] клиентское восстановление не удалось: {e}")
            self._sync_bridge.show_login.emit()

    def _restore_from_local(self, login: str):
        """Собирает дашборд по сохранённому логину из ТЕКУЩИХ локальных данных (UI-поток).
        Зовётся после реконсиляции (или сразу — для хоста/офлайна)."""
        try:
            from data_store import get_store
            found = get_store().lookup_session(login)
        except Exception as e:
            print(f"[restore] поиск пользователя не удался: {e}")
            found = None
        if not found:
            #Данных нет (пустой кэш + офлайн, или пользователь удалён на сервере) —
            #оставляем экран входа.
            self._restore_failed()
            return
        role, payload = found
        self._session = (role, payload)
        try:
            self._open_dashboard()
        except Exception as e:
            print(f"[restore] дашборд не собрался: {e}")
            self._restore_failed()
            return
        #Запускаем фоновый синк по СОХРАНЁННОМУ токену (пароль пуст — синк возьмёт токен;
        #протухнет — синк тихо отложится, чинится перезапуском/повторным входом).
        try:
            from sync_runner import start as _sync_start
            _sync_start(login, "", role)
        except Exception as e:
            print(f"[restore] синк не запущен: {e}")
        self._session_restoring = False

    def _restore_failed(self):
        """Восстановление не удалось — снимаем флаг, остаёмся на экране входа."""
        self._session_restoring = False

    def _maybe_prompt_server(self):
        """Предлагает подключиться (адрес + подтверждение устройства) на свежем ПК.

        НЕ показываем, если устройство УЖЕ подтверждено на этом ПК, это ПК-хоста (там
        админ сам поднимает сервер и одобряет остальных — иначе замкнутый круг) или
        пользователь осознанно выбрал офлайн. Раньше условием было «адрес уже задан»,
        но теперь барьер устройства важнее: даже с адресом ПК должен пройти
        подтверждение, поэтому ориентируемся на флаг device_connected."""
        #Идёт восстановление сессии или она уже восстановлена — окно подключения не нужно
        #(устройство уже подключалось ранее, раз есть сохранённая сессия).
        if getattr(self, "_session_restoring", False) or self._session is not None:
            return
        try:
            from app_settings import is_host, get_offline_ack, is_device_connected
            if is_device_connected() or is_host() or get_offline_ack():
                return
            from auth_pages import ask_server_address
            ask_server_address(self, first_run=True)
        except Exception as e:
            print(f"[startup] окно подключения пропущено: {e}")

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
        self._refresh_applied_mode()   #синхронизируем «текущий режим» для таймера расписания

    def reapply_current(self):
        """Пересобрать текущий дашборд (после «Сохранить» в кастомизации) — чтобы
        новая тема применилась целиком, включая инлайн-стили уже собранных виджетов."""
        if not self._session:
            return
        try:
            self._open_dashboard()
        except Exception as e:
            print(f"[theme] пересборка интерфейса не удалась: {e}")

    def _active_theme_spec(self) -> dict:
        """Spec темы, актуальный сейчас (личный — если вошли, иначе вуза/дефолт)."""
        import theme_service
        role, identity = self._session_identity()
        return theme_service.current_spec(role, identity)

    def _refresh_applied_mode(self):
        """Запомнить, какой режим (light/dark) сейчас применён — чтобы таймер
        расписания ловил именно МОМЕНТ перехода, а не дёргал пересборку зря."""
        try:
            import themes
            self._applied_mode = themes.effective_mode(self._active_theme_spec())
        except Exception:
            pass

    def _tick_theme_schedule(self):
        """Раз в минуту: если по расписанию пора сменить режим — применяем и
        пересобираем интерфейс. Если расписание выключено — режим стабилен, тик пустой."""
        try:
            import themes, styles
            spec = self._active_theme_spec()
            desired = themes.effective_mode(spec)
            if self._applied_mode is None:
                self._applied_mode = desired      #первичная инициализация без пересборки
                return
            if desired != self._applied_mode:
                self._applied_mode = desired
                themes.apply_spec(spec)
                self.setStyleSheet(styles.APP_STYLE)
                if self._session:
                    self._open_dashboard()        #перекрасить инлайн-виджеты под новый режим
        except Exception as e:
            print(f"[theme] тик расписания: {e}")

    def _on_sync_state(self, online: bool, error: str):
        """Синк перешёл в онлайн/офлайн — показываем индикатор в шапке (UI-поток)."""
        try:
            if hasattr(self._header, "set_online"):
                self._header.set_online(online)
        except Exception:
            pass

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
        """Выход из системы.

        Чтобы данные одного аккаунта не «протекали» в следующий на этом ПК (баг с
        фантомным студентом), на выходе сбрасываем локальный кэш — но БЕЗОПАСНО:
          • КЛИЕНТ онлайн → сперва flush (push текущих правок на сервер), потом сброс
            кэша. Так чистый старт для следующего пользователя и без потери правок;
          • офлайн или ХОСТ → кэш не трогаем (offline-first; хост — источник истины).
        Сохранённую сессию и токен снимаем ВСЕГДА — это и есть «выход»."""
        from app_settings import (is_host, get_saved_session, clear_saved_session,
                                  clear_saved_token)
        login = (get_saved_session() or {}).get("login", "")
        was_host = is_host()
        self._session = None   #сессия закрыта — пересобирать по теме больше нечего

        #Останавливаем фоновую синхронизацию текущего пользователя.
        try:
            from sync_runner import stop as _sync_stop
            _sync_stop()
        except Exception:
            pass

        #Клиент онлайн: flush правок и сброс кэша (под курсором ожидания — операция
        #короткая). Хост/офлайн — пропускаем (см. докстринг).
        if not was_host:
            self._client_logout_reset(login)

        #«Выход»: убираем сохранённую сессию и ОБА токена — следующий старт покажет вход.
        try:
            from app_settings import clear_saved_refresh_token
            clear_saved_session()
            if login:
                clear_saved_token()
                clear_saved_refresh_token()
        except Exception as e:
            print(f"[logout] очистка сессии: {e}")

        #Удалить все виджеты, кроме страницы входа (она всегда первая в стеке)
        while self._stack.count() > 1:
            w = self._stack.widget(self._stack.count() - 1)
            self._stack.removeWidget(w)
            w.deleteLater()

        self._stack.setCurrentWidget(self._login)
        self._header.hide()

        #Тему вошедшего пользователя сбрасываем СРАЗУ на выходе — на дефолт/тему вуза.
        #Раньше личная тема оставалась на экране входа и «отваливалась» лишь позже, на
        #тике расписания тем (отсюда жалоба «тема пропадает через некоторое время»).
        try:
            import theme_service, styles
            theme_service.apply_startup_default()
            self.setStyleSheet(styles.APP_STYLE)
            self._header.refresh_theme()
            self._refresh_applied_mode()
            if hasattr(self._login, "refresh_theme"):
                self._login.refresh_theme()
            self._login.update()      #перерисовать живой фон входа в новой палитре
        except Exception as e:
            print(f"[logout] сброс темы пропущен: {e}")

        #Обновить базу учителей
        self.teachers_db, _ = parse_logins()
        self._login.update_teachers(self.teachers_db)

    def _client_logout_reset(self, login: str):
        """Flush правок на сервер и сброс локального кэша при выходе (только клиент,
        только онлайн). Офлайн/без токена — НЕ трогаем локаль (offline-first): тогда
        чистка произойдёт при следующем онлайн-входе через реконсиляцию."""
        try:
            from app_settings import get_api_url, get_saved_token
            url = get_api_url()
            token = get_saved_token(login) if login else ""
            if not url or not token:
                return
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import Qt
            from sync_client import SyncClient
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                c = SyncClient(url, token=token)
                if not c.health():
                    return   #сервер недоступен — офлайн, локаль не трогаем
                import sync_engine
                from data_store import reset_synced_local_data
                c.push(sync_engine.collect_local())   #flush правок этой сессии на сервер
                #Безопасный выход: просим сервер ОТОЗВАТЬ токен (чёрный список), чтобы
                #перехваченный до выхода токен нельзя было использовать до истечения срока.
                c.logout()
                reset_synced_local_data()             #чистый старт для следующего юзера
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as e:
            print(f"[logout] сброс кэша пропущен: {e}")
