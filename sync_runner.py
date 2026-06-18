"""
sync_runner.py — Фоновая синхронизация десктопа с сервером (через API).

Работает в отдельном потоке-демоне (как PGSyncer в core), чтобы не блокировать
интерфейс. Запускается после входа пользователя, ЕСЛИ задан адрес сервера
(app_settings.get_api_url). Нет сети/сервера — тихо ждёт и повторяет позже:
offline-first сохраняется, прога продолжает работать на локальном SQLite.

Авторизация к API — теми же логином/паролем, что ввёл пользователь. Токен живёт
в памяти на время сессии; при сбое — перелогин на следующем цикле.
"""
import threading
import time

from app_settings import get_api_url


class SyncManager:
    def __init__(self, interval_sec: int = 60):
        self._thread = None
        self._running = False
        self._client = None
        self._login = ""
        self._password = ""
        self._role = ""
        self._interval = interval_sec
        self._on_synced = None   # колбэк после успешного цикла (для обновления UI)

    def set_on_synced(self, cb):
        """Колбэк, вызываемый после успешной синхронизации. UI подключает сюда
        обновление текущего экрана (через потокобезопасный сигнал Qt)."""
        self._on_synced = cb

    def start(self, login: str, password: str, role: str):
        """Запустить фоновую синхронизацию для вошедшего пользователя."""
        url = get_api_url()
        if not url:
            return   # офлайн-режим без сервера — синк не нужен
        self._login, self._password, self._role = login, password, role
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, args=(url,), daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._client = None

    def _ensure_auth(self, url: str) -> bool:
        """Гарантирует наличие токена. При первом запуске сервера без админа —
        бутстрапит администратора теми же кредами (только для роли admin)."""
        from sync_client import SyncClient
        if self._client is None:
            self._client = SyncClient(url)
        if self._client.token:
            return True
        try:
            self._client.login(self._login, self._password)
            return True
        except Exception:
            if self._role == "admin":
                try:
                    self._client.bootstrap_admin(self._login, self._password)
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
                            self._on_synced()   # сигнал «данные обновились» в UI
                        except Exception:
                            pass
            except Exception as e:
                # Сеть/токен/сервер недоступны — не критично, повторим позже.
                self._client = None   # сбросим, чтобы перелогиниться
                print(f"[sync] отложено: {e}")
            # Ждём интервал, но быстро реагируем на stop().
            for _ in range(self._interval):
                if not self._running:
                    break
                time.sleep(1)


# Глобальный менеджер на процесс.
_manager = SyncManager()


def start(login: str, password: str, role: str):
    _manager.start(login, password, role)


def stop():
    _manager.stop()


def set_on_synced(cb):
    _manager.set_on_synced(cb)
