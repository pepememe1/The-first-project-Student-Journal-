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
import base64
import json
import os
import re
import time

import requests

DEFAULT_TIMEOUT = 10

#Таймаут синка — КОРТЕЖ (connect, read): быстро понять, что сервера нет (5 c на
#соединение), но дать серверу время отдать/принять КРУПНЫЙ первый обмен (30 c на
#чтение). Раньше единый 10 c рвал большой первый pull/push на медленном канале —
#отсюда «Read timed out» в логе. connect короткий → офлайн определяется быстро.
SYNC_TIMEOUT = (5, 30)


def is_token_expired(token: str, skew_sec: int = 30) -> bool:
    """True, если JWT просрочен (или не разобрался). Разбираем payload БЕЗ проверки
    подписи — это обычный base64url-JSON, а поле exp — абсолютная метка времени сервера.

    Зачем: не дёргать сеть заведомо мёртвым токеном и заранее (за skew_sec до exp)
    обновить его через refresh. Подпись здесь проверять не нужно — решение «идти в сеть
    или обновиться» не связано с доверием, а exp сервер всё равно перепроверит сам.
    Офлайн-время тоже учитывается: exp абсолютный, «заморозить» его нельзя."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)          #добить паддинг base64
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        return time.time() > (payload.get("exp", 0) - skew_sec)
    except Exception:
        return True


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
    def __init__(self, base_url: str, token: str = None, refresh_token: str = None):
        self.base_url = _prefer_ipv4((base_url or "").rstrip("/"))
        self.token = token
        self.refresh_token = refresh_token or ""
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
        #X-Device-Id — идентификатор этого ПК для барьера подтверждения: сервер по
        #нему решает, одобрено ли устройство (см. server/app/connect.py). Шлём на КАЖДОМ
        #запросе, в т.ч. при входе — иначе неодобренный ПК не отличить от одобренного.
        try:
            import app_settings
            dev = app_settings.get_device_id()
            if dev:
                h["X-Device-Id"] = dev
        except Exception:
            pass
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
        """Возвращает {access_token, refresh_token, role, name} и запоминает оба токена."""
        r = self._req("POST", "/auth/login",
                      json={"login": login, "password": password})
        r.raise_for_status()
        data = r.json()
        self.token = data.get("access_token")
        self.refresh_token = data.get("refresh_token", "") or self.refresh_token
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
        self.refresh_token = data.get("refresh_token", "") or self.refresh_token
        return data

    def refresh(self, refresh_token: str = None) -> dict:
        """Тихо обновляет access по refresh-токену (/auth/refresh). Обновляет self.token
        и возвращает данные {access_token, refresh_token, role, name}. Бросает HTTPError,
        если refresh недействителен/отозван — тогда вызывающий делает полный re-login."""
        rt = (refresh_token or self.refresh_token or "").strip()
        if not rt:
            raise ValueError("нет refresh-токена для обновления")
        r = self._req("POST", "/auth/refresh", json={"refresh_token": rt})
        r.raise_for_status()
        data = r.json()
        self.token = data.get("access_token") or self.token
        self.refresh_token = data.get("refresh_token", "") or self.refresh_token
        return data

    def logout(self) -> dict:
        """Безопасный выход: просит сервер ОТОЗВАТЬ текущий токен (чёрный список), чтобы
        украденный до выхода токен нельзя было использовать. Best-effort (ошибку глушим)."""
        try:
            r = self._req("POST", "/auth/logout", timeout=5)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {"revoked": 0}

    def pull(self, since: str = "") -> dict:
        """Изменения позже метки since. Возвращает {server_time, changes}.
        Долгий read-таймаут: первый полный pull может быть большим на медленном канале."""
        r = self._req("GET", "/sync/pull", params={"since": since}, timeout=SYNC_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def push(self, changes: dict) -> dict:
        """Отправляет изменения. changes = {users:[...], grades:[...], ...}.
        Долгий read-таймаут: первый пуш накопленного офлайн бывает объёмным."""
        r = self._req("POST", "/sync/push", json={"changes": changes}, timeout=SYNC_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def set_my_prefs(self, prefs: dict) -> dict:
        """Сохранить личные настройки текущего пользователя (self-scope /me/prefs).
        Меняет ТОЛЬКО свою строку — личность берётся из JWT на сервере."""
        r = self._req("POST", "/me/prefs", json={"prefs": prefs}, timeout=5)
        r.raise_for_status()
        return r.json()

    #Барьер подтверждения подключения (см. server/app/connect.py)
    #Эндпоинты /connect/{request,status,verify} — БЕЗ авторизации (новый ПК ещё не вошёл).
    def connect_request(self, device_id: str, hostname: str = "") -> dict:
        """Новый ПК просит доступ. Возвращает {status}."""
        r = self._req("POST", "/connect/request",
                      json={"device_id": device_id, "hostname": hostname}, timeout=8)
        r.raise_for_status()
        return r.json()

    def connect_status(self, device_id: str) -> str:
        """Опрос статуса запроса (pending|code_issued|approved|rejected|none)."""
        r = self._req("GET", "/connect/status",
                      params={"device_id": device_id}, timeout=8)
        r.raise_for_status()
        return (r.json() or {}).get("status", "none")

    def connect_verify(self, device_id: str, code: str) -> dict:
        """Ввод кода подтверждения. Бросает HTTPError при неверном/просроченном коде."""
        r = self._req("POST", "/connect/verify",
                      json={"device_id": device_id, "code": code}, timeout=8)
        r.raise_for_status()
        return r.json()

    #Действия администратора над запросами (на сервере — require_admin)
    def list_connect_requests(self) -> dict:
        """Активные запросы на подключение. {requests:[...], count}."""
        r = self._req("GET", "/connect/requests", timeout=5)
        r.raise_for_status()
        return r.json()

    def approve_device(self, device_id: str) -> dict:
        """Принять запрос — сервер вернёт 6-значный код для пользователя. {code}."""
        r = self._req("POST", "/connect/approve", json={"device_id": device_id}, timeout=5)
        r.raise_for_status()
        return r.json()

    def reject_device(self, device_id: str) -> dict:
        """Отклонить запрос. {ok}."""
        r = self._req("POST", "/connect/reject", json={"device_id": device_id}, timeout=5)
        r.raise_for_status()
        return r.json()

    #Заявки студентов на самостоятельную регистрацию (на сервере — require_admin).
    #Те же эндпоинты, что и веб-админка, — десктоп теперь видит и решает заявки 1:1.
    def list_registrations(self) -> dict:
        """Заявки на регистрацию, ждущие решения. {requests:[{id,full_name,group,phone,email,created_at}]}."""
        r = self._req("GET", "/web/admin/registrations", timeout=8)
        r.raise_for_status()
        return r.json()

    def approve_registration(self, req_id: str) -> dict:
        """Одобрить заявку: сервер заведёт студента и вышлет пароль на почту. {ok,sent,login,password}."""
        r = self._req("POST", "/web/admin/registrations/approve", json={"id": req_id}, timeout=15)
        r.raise_for_status()
        return r.json()

    def reject_registration(self, req_id: str, note: str = "") -> dict:
        """Отклонить заявку (с необязательной причиной). {ok}."""
        r = self._req("POST", "/web/admin/registrations/reject",
                      json={"id": req_id, "note": note or ""}, timeout=8)
        r.raise_for_status()
        return r.json()

    #Контактные данные с сервера (телефон, IP, последний вход) — для карточек студентов
    #и преподавателей в десктопе, как на сайте (require_admin).
    def admin_students(self, group: str = "") -> dict:
        """Студенты с сервера + контакты (login, phone, last_login, ip). {students:[...]}."""
        r = self._req("GET", "/web/admin/students", params={"group": group or ""}, timeout=8)
        r.raise_for_status()
        return r.json()

    def admin_teachers(self) -> dict:
        """Преподаватели с сервера + контакты (login, phone, last_login, ip). {teachers:[...]}."""
        r = self._req("GET", "/web/admin/teachers", timeout=8)
        r.raise_for_status()
        return r.json()

    #Управление сессиями/токенами (на сервере — require_admin)
    def list_sessions(self, active: bool = True) -> dict:
        """Активные выданные токены (сессии): кто, роль, устройство, до когда. {sessions,count}."""
        r = self._req("GET", "/admin/sessions",
                      params={"active": "true" if active else "false"}, timeout=5)
        r.raise_for_status()
        return r.json()

    def revoke_session(self, jti: str = "", login: str = "") -> dict:
        """Отозвать сессию по jti (конкретный токен) ИЛИ по логину (все сессии юзера). {revoked}."""
        r = self._req("POST", "/admin/sessions/revoke",
                      json={"jti": jti or "", "login": login or ""}, timeout=5)
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
