"""
sync_runner.py — Фоновая синхронизация десктопа с сервером (через API).

Работает в отдельном потоке-демоне, чтобы не блокировать интерфейс.
Запускается после входа пользователя, ЕСЛИ задан адрес сервера
(app_settings.get_api_url). Нет сети/сервера — тихо ждёт и повторяет позже:
offline-first сохраняется, прога продолжает работать на локальном SQLite.

Авторизация к API — теми же логином/паролем, что ввёл пользователь. Токен живёт
в памяти на время сессии; при сбое — перелогин на следующем цикле.
"""
import threading
import time

from app_settings import get_api_url


class SyncManager:
    def __init__(self, interval_sec: int = 30):
        self._thread = None
        self._running = False
        self._client = None
        self._login = ""
        self._password = ""
        self._role = ""
        self._url = ""           #адрес сервера, под который создан текущий клиент
        self._interval = interval_sec
        self._on_synced = None   #колбэк после успешного цикла (для обновления UI)
        self._wake = threading.Event()   #«будильник» для немедленного синка
        #Сохранённый токен пробуем РОВНО один раз за сессию входа: если он протух,
        #дальше идём по паролю, а не крутим бесконечно негодный токен.
        self._saved_token_tried = False
        #Jitter перед входом по паролю — один раз за процесс (размазать «герд»).
        self._jitter_done = False

    def trigger(self):
        """Разбудить синкер прямо сейчас (например, после сохранения данных),
        чтобы изменения ушли на сервер без ожидания интервала."""
        self._wake.set()

    def set_on_synced(self, cb):
        """Колбэк, вызываемый после успешной синхронизации. UI подключает сюда
        обновление текущего экрана (через потокобезопасный сигнал Qt)."""
        self._on_synced = cb

    def current_auth(self):
        """(url, token) текущей сессии — чтобы админ-панель могла сама дёрнуть
        служебные эндпоинты /admin/*. Берём ЖИВОЙ токен синкера, иначе сохранённый
        для текущего логина. ('', '') — если адрес/вход не заданы."""
        url = get_api_url()
        token = ""
        if self._client and getattr(self._client, "token", ""):
            token = self._client.token
        elif self._login:
            import app_settings
            token = app_settings.get_saved_token(self._login)
        return url, (token or "")

    def start(self, login: str, password: str, role: str):
        """Запустить фоновую синхронизацию для вошедшего пользователя.

        Креды запоминаем ВСЕГДА, даже если адрес сервера ещё не задан. Это важно
        для хост-ПК: администратор поднимает сервер уже ПОСЛЕ входа (адрес ведь
        появляется только после запуска сервера — иначе замкнутый круг). Раньше
        здесь стоял ранний `return` при пустом адресе: поток не стартовал, креды
        терялись, и когда сервер наконец поднимали — синхронизация так и не шла.
        Из-за этого админ не отдавал на сервер пользователей (преподаватели/студенты
        получали 401 при входе через API), а мониторинг не имел токена. Теперь поток
        стартует всегда и сам подхватывает адрес, как только он появится."""
        self._login, self._password, self._role = login, password, role
        #Новый вход — снова разрешаем попытку по сохранённому токену именно этого
        #пользователя (на одном ПК мог входить другой).
        self._saved_token_tried = False
        if self._running:
            return
        self._running = True
        self._wake.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._client = None
        self._wake.set()   #будим цикл, чтобы он завершился сразу, а не через интервал

    def _apply_login_jitter(self):
        """Случайная задержка ПЕРЕД входом по паролю — один раз за процесс.

        Зачем: когда сотни ПК включают прогу в 9:00, все разом бьют в `/auth/login`,
        а PBKDF2 (600k) на сервере упирается в CPU. Случайный сдвиг 0..N секунд
        размазывает пик. Спим в фоновом потоке синка — UI не блокируется, локальные
        данные уже на экране (offline-first), задержка незаметна. N задаётся
        переменной GRADEBOOK_LOGIN_JITTER_SEC (по умолчанию 8 c; 0 — выключить)."""
        if self._jitter_done:
            return
        self._jitter_done = True
        import os
        try:
            max_s = float(os.environ.get("GRADEBOOK_LOGIN_JITTER_SEC", "8"))
        except ValueError:
            max_s = 8.0
        if max_s <= 0:
            return
        import random
        time.sleep(random.uniform(0, max_s))

    def _ensure_auth(self, url: str) -> bool:
        """Гарантирует наличие ГОДНОГО токена. Порядок (от дешёвого к дорогому):
          1) уже есть непросроченный access — берём его;
          2) сохранённый access (без дорогого PBKDF2), если он ещё жив;
          3) ТИХОЕ обновление refresh-токеном — без пароля (главное: не выкидываем
             пользователя на логин, когда короткий access протух, в т.ч. за офлайн);
          4) резерв — вход по паролю (+ bootstrap администратора при первом запуске).

        Просрочку access проверяем локально (is_token_expired, exp — абсолютная метка):
        офлайн-время учитывается, «заморозить» токен нельзя."""
        from sync_client import SyncClient, is_token_expired
        import app_settings
        if self._client is None:
            self._client = SyncClient(url)
        #Подтянем сохранённый refresh-токен (для тихого обновления) — один раз.
        if not self._client.refresh_token and self._login:
            self._client.refresh_token = app_settings.get_saved_refresh_token(self._login)

        #1) есть живой access
        if self._client.token and not is_token_expired(self._client.token):
            return True

        #2) сохранённый access (ровно один раз за сессию), если он ещё не протух
        if not self._client.token and not self._saved_token_tried:
            self._saved_token_tried = True
            saved = app_settings.get_saved_token(self._login)
            if saved and not is_token_expired(saved):
                self._client.token = saved
                return True

        #3) тихое обновление refresh-токеном — без пароля
        if self._client.refresh_token and self._try_refresh():
            return True

        #4) вход по паролю. ВАЖНО: если пароля нет (восстановленная сессия без
        #сохранённого токена — main_window запускает синк как start(login, "", role)),
        #НЕ ходим на сервер. Неудачный вход с пустым паролем каждый цикл накручивал бы
        #анти-брутфорс (429) и блокировал бы даже правильный вход. Тихо ждём, пока
        #пользователь войдёт заново с паролем (data_store передаст его в start()).
        if not (self._password or "").strip():
            return False
        #Перед входом — jitter (размазать герд входов в 9:00).
        self._client.token = None
        self._apply_login_jitter()
        try:
            self._client.login(self._login, self._password)
            self._save_tokens()
            return True
        except Exception:
            if self._role == "admin":
                try:
                    self._client.bootstrap_admin(self._login, self._password)
                    self._save_tokens()
                    return True
                except Exception:
                    return False
            return False

    def _try_refresh(self) -> bool:
        """Пробует тихо обновить access по refresh-токену. True — получилось. False —
        refresh недействителен/отозван (тогда _ensure_auth уйдёт на вход по паролю)."""
        if not self._client or not self._client.refresh_token:
            return False
        try:
            self._client.refresh()
            self._save_tokens()
            return True
        except Exception:
            return False

    def _save_tokens(self):
        """Сохраняет access и refresh в зашифрованное локальное хранилище (DPAPI/Fernet)."""
        import app_settings
        app_settings.set_saved_token(self._login, self._client.token)
        if self._client.refresh_token:
            app_settings.set_saved_refresh_token(self._login, self._client.refresh_token)

    def _loop(self):
        import sync_engine
        while self._running:
            #Адрес сервера читаем КАЖДЫЙ цикл, а не один раз при старте: на хост-ПК он
            #появляется уже после входа (админ поднимает сервер), а у serveo поддомен
            #может смениться между запусками. Нет адреса — тихо ждём и проверяем снова.
            url = get_api_url()
            if not url:
                self._sleep_cycle()
                continue
            #Сменился адрес — старый клиент/токен относятся к другому серверу и больше
            #не годятся: пересоздаём клиента и идём по паролю (сохранённый токен чужой).
            if self._url and self._url != url:
                self._client = None
                self._saved_token_tried = True
            self._url = url
            try:
                if self._ensure_auth(url):
                    sync_engine.sync_once(self._client)
                    self._flush_pending_prefs()   #до-отправляем тему, если зависла
                    if self._on_synced:
                        try:
                            self._on_synced()   #сигнал «данные обновились» в UI
                        except Exception:
                            pass
            except Exception as e:
                #Сеть/токен/сервер недоступны — не критично, повторим позже.
                self._client = None   # сбросим, чтобы перелогиниться
                print(f"[sync] отложено: {e}")
            self._sleep_cycle()

    def _sleep_cycle(self):
        """Ждём интервал ИЛИ «будильник» (trigger при изменении данных/запуске сервера)."""
        self._wake.wait(timeout=self._interval)
        self._wake.clear()

    def push_my_prefs(self, prefs: dict):
        """Отправить личные настройки (тему оформления) текущего пользователя на сервер.

        Строго self-scope (POST /me/prefs), в ОТДЕЛЬНОМ потоке — UI не блокируем.
        Если отправить сейчас нельзя (офлайн / нет токена / запрос упал) — кладём
        prefs в отложенные (app_settings.set_pending_prefs) и до-отправим при следующей
        удачной синхронизации (_flush_pending_prefs). Иначе выбранная тема осталась бы
        только локально и не уехала бы в БД (не «роумилась» на другие ПК)."""
        import app_settings
        url = get_api_url()
        token = ""
        if self._client and getattr(self._client, "token", ""):
            token = self._client.token
        elif self._login:
            token = app_settings.get_saved_token(self._login)
        if not url or not token:
            if self._login:
                app_settings.set_pending_prefs(self._login, prefs)
            return

        def _send():
            try:
                from sync_client import SyncClient
                SyncClient(url, token).set_my_prefs(prefs)
                app_settings.clear_pending_prefs()
            except Exception as e:
                print(f"[theme] не удалось отправить тему на сервер: {e}")
                if self._login:
                    app_settings.set_pending_prefs(self._login, prefs)
        threading.Thread(target=_send, daemon=True).start()

    def _flush_pending_prefs(self):
        """Если с прошлого раза тема не доехала до сервера — до-отправляем её сейчас,
        пользуясь уже живым токеном текущего цикла. Зовётся после удачного sync_once."""
        if not self._login or self._client is None:
            return
        import app_settings
        prefs = app_settings.get_pending_prefs(self._login)
        if not prefs:
            return
        try:
            from sync_client import SyncClient
            SyncClient(self._url, self._client.token).set_my_prefs(prefs)
            app_settings.clear_pending_prefs()
        except Exception as e:
            print(f"[theme] отложенная отправка темы не удалась: {e}")

    def flush_now(self):
        """Синхронный один цикл синхронизации ПРЯМО СЕЙЧАС — для выхода из аккаунта и
        закрытия проги. Пушит накопленное, если есть авторизация. Долго не блокирует:
        без пароля/токена _ensure_auth вернёт False сразу (фикс выше), а сетевые вызовы
        ограничены таймаутом клиента. Так данные не теряются при закрытии крестиком."""
        try:
            url = get_api_url()
            if not url:
                return
            self._url = url
            if self._ensure_auth(url):
                import sync_engine
                sync_engine.sync_once(self._client)
                self._flush_pending_prefs()
        except Exception as e:
            print(f"[sync] flush: {e}")


#Глобальный менеджер на процесс.
_manager = SyncManager()


def start(login: str, password: str, role: str):
    _manager.start(login, password, role)


def stop():
    _manager.stop()


def set_on_synced(cb):
    _manager.set_on_synced(cb)


def trigger():
    """Немедленно разбудить синкер (после изменения данных)."""
    _manager.trigger()


def flush():
    """Синхронно до-отправить накопленные правки перед выходом из программы.

    Обёртка над методом менеджера `flush_now` — main.py на закрытии зовёт именно
    модульную `sync_runner.flush()`. Без авторизации/сервера выходит сразу, не вешая
    закрытие приложения."""
    _manager.flush_now()


def current_auth():
    """(url, token) текущей сессии для админских запросов из UI ('', '' — нет входа)."""
    return _manager.current_auth()


def push_my_prefs(prefs: dict):
    """Отправить личные настройки (тему оформления) текущего пользователя на сервер.

    Делегируем менеджеру: он знает логин и при неудаче отложит отправку, чтобы тема
    не потерялась для БД и «роуминга». Запрос строго self-scope (/me/prefs)."""
    _manager.push_my_prefs(prefs)
