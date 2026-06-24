"""
sync_client.py — Клиент синхронизации десктопа с бэкендом GradeBookAI.

Offline-first: программа ВСЕГДА работает на локальном SQLite. Этот модуль нужен
только для обмена с сервером, когда сеть доступна:
  • login()      — получить JWT по логину/паролю (те же, что вводит пользователь).
  • pull(since)   — забрать изменения с сервера (дельта по метке времени).
  • push(changes) — отправить накопленные офлайн изменения.
  • health()      — быстро проверить, доступен ли сервер.

Адрес API берётся из конфигурации (в боевой сборке — зашит/прописан один раз).
Любая сетевая ошибка НЕ критична: синхронизация просто откладывается, программа
продолжает работать офлайн. Поэтому методы кидают исключения, а вызывающий код
(фоновый синкер) ловит их и повторяет позже.
"""
import os
import re

import requests

DEFAULT_TIMEOUT = 10


def _verify_setting():
    """Что передавать в requests как verify (проверку TLS-сертификата).

    По умолчанию True — сертификат проверяется (Caddy с публичным доменом даёт
    доверенный сертификат Let's Encrypt, ничего настраивать не нужно). Для
    ВНУТРЕННЕГО ЛВС с самоподписанным сертификатом укажите путь к доверенному CA в
    переменной GRADEBOOK_CA_BUNDLE — тогда https в ЛВС заработает без отключения
    проверки. Проверку TLS НИКОГДА не выключаем (verify=False открыл бы канал для
    подмены сервера)."""
    return os.environ.get("GRADEBOOK_CA_BUNDLE", "").strip() or True


def _prefer_ipv4(url: str) -> str:
    """localhost → 127.0.0.1 в адресе сервера.

    На чистом IPv4-окружении (типично для РФ) имя localhost резолвится сначала в
    IPv6 ::1; если сервер слушает только IPv4, запрос сперва виснет на таймауте
    ::1 и лишь потом падает на 127.0.0.1 — отсюда заметная задержка входа и
    синхронизации. Явный 127.0.0.1 убирает этот лишний круг."""
    return re.sub(r"^(https?://)localhost(?=[:/]|$)", r"\g<1>127.0.0.1", url)


class SyncClient:
    def __init__(self, base_url: str, token: str = None):
        self.base_url = _prefer_ipv4((base_url or "").rstrip("/"))
        self.token = token
        #verify (проверка TLS) и заголовки общие для всех запросов — держим в сессии.
        self._verify = _verify_setting()
        self._warn_if_insecure()

    def _warn_if_insecure(self):
        """Предупреждаем, если адрес сервера — http к удалённому хосту: тогда ПДн
        (логины, пароли, оценки) пойдут по сети открытым текстом. Не блокируем —
        в ЛВС на этапе настройки это бывает временно нужно, но админ должен знать."""
        try:
            import app_settings
            if self.base_url and not app_settings.is_secure_transport(self.base_url):
                print("[SyncClient] ВНИМАНИЕ: сервер задан по http:// к удалённому "
                      "адресу — персональные данные пойдут по сети В ОТКРЫТОМ виде. "
                      "Для боевой работы используйте https:// (см. server/DEPLOY.md, "
                      "раздел про Caddy и TLS).")
        except Exception:
            pass

    def _headers(self) -> dict:
        #ngrok-skip-browser-warning — чтобы бесплатные туннели (ngrok и пр.) не
        #подсовывали HTML-страницу-предупреждение вместо JSON ответа API.
        h = {"ngrok-skip-browser-warning": "true"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _req(self, method: str, path: str, timeout=DEFAULT_TIMEOUT, **kwargs):
        """Единая точка сетевого вызова: общие заголовки и проверка TLS (verify) в
        одном месте, чтобы их нельзя было случайно забыть на отдельном запросе."""
        return requests.request(method, f"{self.base_url}{path}",
                                headers=self._headers(), timeout=timeout,
                                verify=self._verify, **kwargs)

    def health(self) -> bool:
        """True, если сервер отвечает. Не кидает исключений."""
        try:
            return self._req("GET", "/health", timeout=3).status_code == 200
        except Exception:
            return False

    def login(self, login: str, password: str) -> dict:
        """Возвращает {access_token, role, name} и запоминает токен."""
        r = self._req("POST", "/auth/login",
                      json={"login": login, "password": password})
        r.raise_for_status()
        data = r.json()
        self.token = data.get("access_token")
        return data

    def bootstrap_admin(self, login: str, password: str,
                        full_name: str = "Администратор") -> dict:
        """Создаёт первого администратора на сервере (только если его ещё нет)."""
        r = self._req("POST", "/auth/bootstrap-admin",
                      json={"login": login, "password": password,
                            "full_name": full_name})
        r.raise_for_status()
        data = r.json()
        self.token = data.get("access_token")
        return data

    def pull(self, since: str = "") -> dict:
        """Изменения позже метки since. Возвращает {server_time, changes}."""
        r = self._req("GET", "/sync/pull", params={"since": since})
        r.raise_for_status()
        return r.json()

    def push(self, changes: dict) -> dict:
        """Отправляет изменения. changes = {users:[...], grades:[...], ...}."""
        r = self._req("POST", "/sync/push", json={"changes": changes})
        r.raise_for_status()
        return r.json()

    #Админский мониторинг (доступ на сервере ограничен ролью admin — см. /admin/*)
    def get_online(self) -> dict:
        """Кто сейчас подключён к серверу. {online:[...], count, window_sec}."""
        r = self._req("GET", "/admin/online", timeout=5)
        r.raise_for_status()
        return r.json()

    def get_events(self, since: int = 0) -> dict:
        """Журнал событий сервера дельтой (since — последний полученный id).
        {events:[...], last_id}."""
        r = self._req("GET", "/admin/events", params={"since": since}, timeout=5)
        r.raise_for_status()
        return r.json()
