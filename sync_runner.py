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

    def start(self, login: str, password: str, role: str):
        """Запустить фоновую синхронизацию для вошедшего пользователя."""
        url = get_api_url()
        if not url:
            return   #офлайн-режим без сервера — синк не нужен
        self._login, self._password, self._role = login, password, role
        #Новый вход — снова разрешаем попытку по сохранённому токену именно этого
        #пользователя (на одном ПК мог входить другой).
        self._saved_token_tried = False
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, args=(url,), daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._client = None

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
        """Гарантирует наличие токена. Сначала пробуем сохранённый токен (без
        дорогого PBKDF2), затем — вход по паролю. При первом запуске сервера без
        админа бутстрапит администратора теми же кредами (только для роли admin)."""
        from sync_client import SyncClient
        import app_settings
        if self._client is None:
            self._client = SyncClient(url)
        if self._client.token:
            return True

        #Переиспользование токена: пробуем сохранённый JWT РОВНО один раз за сессию.
        #Если он протух — сервер отдаст 401 на pull/push, цикл сбросит клиента, и в
        #следующий заход (флаг уже взведён) мы пойдём по паролю.
        if not self._saved_token_tried:
            self._saved_token_tried = True
            saved = app_settings.get_saved_token(self._login)
            if saved:
                self._client.token = saved
                return True

        #Нет годного токена — обычный вход по паролю. Перед ним — jitter (размазать герд).
        self._apply_login_jitter()
        try:
            self._client.login(self._login, self._password)
            app_settings.set_saved_token(self._login, self._client.token)
            return True
        except Exception:
            if self._role == "admin":
                try:
                    self._client.bootstrap_admin(self._login, self._password)
                    app_settings.set_saved_token(self._login, self._client.token)
                    return True
                except Exception:
                    return False
            return False

    def _loop(self, url: str):
        import sync_engine
        while self._running:
            try:
                if self._ensure_auth(url):
                    sync_engine.sync_once(self._client)
                    if self._on_synced:
                        try:
                            self._on_synced()   #сигнал «данные обновились» в UI
                        except Exception:
                            pass
            except Exception as e:
                #Сеть/токен/сервер недоступны — не критично, повторим позже.
                self._client = None   # сбросим, чтобы перелогиниться
                print(f"[sync] отложено: {e}")
            #Ждём интервал ИЛИ «будильник» (trigger при изменении данных).
            self._wake.wait(timeout=self._interval)
            self._wake.clear()


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
