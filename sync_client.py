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
import requests

DEFAULT_TIMEOUT = 10


class SyncClient:
    def __init__(self, base_url: str, token: str = None):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token

    def _headers(self) -> dict:
        #ngrok-skip-browser-warning — чтобы бесплатные туннели (ngrok и пр.) не
        #подсовывали HTML-страницу-предупреждение вместо JSON ответа API.
        h = {"ngrok-skip-browser-warning": "true"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def health(self) -> bool:
        """True, если сервер отвечает. Не кидает исключений."""
        try:
            r = requests.get(f"{self.base_url}/health", headers=self._headers(), timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def login(self, login: str, password: str) -> dict:
        """Возвращает {access_token, role, name} и запоминает токен."""
        r = requests.post(f"{self.base_url}/auth/login",
                          json={"login": login, "password": password},
                          headers=self._headers(), timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        self.token = data.get("access_token")
        return data

    def bootstrap_admin(self, login: str, password: str,
                        full_name: str = "Администратор") -> dict:
        """Создаёт первого администратора на сервере (только если его ещё нет)."""
        r = requests.post(f"{self.base_url}/auth/bootstrap-admin",
                          json={"login": login, "password": password,
                                "full_name": full_name},
                          headers=self._headers(), timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        self.token = data.get("access_token")
        return data

    def pull(self, since: str = "") -> dict:
        """Изменения позже метки since. Возвращает {server_time, changes}."""
        r = requests.get(f"{self.base_url}/sync/pull",
                        params={"since": since}, headers=self._headers(),
                        timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def push(self, changes: dict) -> dict:
        """Отправляет изменения. changes = {users:[...], grades:[...], ...}."""
        r = requests.post(f"{self.base_url}/sync/push",
                         json={"changes": changes}, headers=self._headers(),
                         timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
