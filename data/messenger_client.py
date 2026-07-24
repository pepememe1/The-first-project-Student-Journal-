"""
messenger_client.py — HTTP-клиент мессенджера для ДЕСКТОПА.

Мессенджер — онлайн-подсистема (см. docs/MESSENGER-PLAN.md), поэтому идёт НЕ через
sync-движок, а прямыми REST-запросами к тем же эндпоинтам /web/messenger/*, что и веб.
Адрес и токен берём из sync_runner.current_auth() (обновляются при входе/refresh). Все
функции возвращают распарсенный JSON или None (нет сети/сессии) и НЕ бросают наверх —
вызывающий код (UI) работает в фоне и просто показывает пустое состояние при сбое.
"""
from urllib.parse import quote

import requests

_TIMEOUT = 10


def _auth():
    try:
        from sync_runner import current_auth
        return current_auth()
    except Exception:
        return ("", "")


def _headers(token: str) -> dict:
    #X-Device-Id ОБЯЗАТЕЛЕН: на десктопе device-барьер применяется ко всем ролям, и без
    #этого заголовка /web/messenger/* отвечает 403 (сервер не может опознать одобренный ПК).
    h = {"Authorization": f"Bearer {token}", "X-Client": "desktop",
         "ngrok-skip-browser-warning": "true"}
    try:
        import app_settings
        dev = app_settings.get_device_id()
        if dev:
            h["X-Device-Id"] = dev
    except Exception:
        pass
    return h


def _get(path: str, params: dict = None):
    url, token = _auth()
    if not (url and token):
        return None
    try:
        r = requests.get(f"{url}{path}", params=params or {},
                         headers=_headers(token), timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _post(path: str, payload: dict = None):
    url, token = _auth()
    if not (url and token):
        return None
    try:
        r = requests.post(f"{url}{path}", json=payload or {},
                          headers=_headers(token), timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _q(conv_id: str) -> str:
    """id беседы содержит ':' и '|' (direct:...|...) — экранируем для пути."""
    return quote(conv_id, safe="")


# ── Публичный API (зеркало web/src/api/endpoints.js::messengerApi) ────────────────────
def chats():
    return _get("/web/messenger/chats")


def messages(conv_id: str, after: int = 0):
    params = {"after": after} if after else {}
    return _get(f"/web/messenger/chats/{_q(conv_id)}/messages", params)


def send(conv_id: str, body: str, reply_to_id: int = 0):
    return _post(f"/web/messenger/chats/{_q(conv_id)}/messages",
                 {"body": body, "reply_to_id": reply_to_id})


def open_direct(user_id: str):
    return _post(f"/web/messenger/chats/direct/{_q(user_id)}")


def read(conv_id: str, last_message_id: int = 0):
    return _post(f"/web/messenger/chats/{_q(conv_id)}/read",
                 {"last_message_id": last_message_id})


def users(role: str = "student", q: str = ""):
    return _get("/web/messenger/users", {"role": role, "q": q})
