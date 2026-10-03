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

import threading

import requests

import log

_log = log.get("sync")

#Таймауты — КОРТЕЖ (connect, read). connect чуть щедрее (РФ-VPS за Cloudflare/TLS не
#всегда соединяется за пару секунд), read короче для быстрых вызовов. Единичный блип
#гасит retry-адаптер ниже, поэтому жёстких «5 c» больше нет.
DEFAULT_TIMEOUT = (8, 15)

#Таймаут синка — connect как у всех, но read ДЛИННЫЙ: первый полный pull/push на
#медленном канале бывает крупным (иначе «Read timed out» в логе).
SYNC_TIMEOUT = (8, 45)

#Быстрая проверка доступности (health): короткая, но не впритык.
HEALTH_TIMEOUT = (5, 5)


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
    @staticmethod
    def normalize(base_url: str) -> str:
        """Адрес в том виде, в каком его хранит клиент.

        Отдельным методом, чтобы вызывающие могли СРАВНИТЬ свой адрес с `client.base_url`
        (сменился сервер — клиента надо пересоздать, см. `sync_runner._ensure_auth`), не
        повторяя у себя ни обрезку слэша, ни подмену localhost."""
        return _prefer_ipv4((base_url or "").rstrip("/"))

    #⚠️ Токены объявлены как `str | None`, а не `str`: пустое значение здесь бывает ДВУХ
    #видов и оба настоящие — «ещё не входили» и «вышли» (`logout` гасит токен в None,
    #чтобы переиспользованный на общем ПК клиент не слал отозванный). Прежняя запись
    #`token: str = None` была неявным Optional: аннотация обещала строку, а значением по
    #умолчанию стоял None — и любой читатель (и mypy) делал по ней неверный вывод.
    def __init__(self, base_url: str, token: str | None = None,
                 refresh_token: str | None = None):
        self.base_url = self.normalize(base_url)
        if not self.base_url:
            #Пустой адрес раньше давал ОТНОСИТЕЛЬНЫЙ запрос и невнятную ошибку глубоко
            #внутри requests. Отказ на месте создания понятнее на порядок.
            raise ValueError("SyncClient: не задан адрес сервера")
        self.token = token
        self.refresh_token = refresh_token or ""
        #verify (проверка TLS) и заголовки общие для всех запросов — держим в сессии.
        self._verify = _verify_setting()
        #🔥 СЕССИИ — ПО ПОТОКУ. `requests.Session` НЕ потокобезопасна: у неё общий пул
        #соединений, и одновременные запросы из разных потоков портят его состояние
        #(симптом — редкие необъяснимые обрывы, которые не воспроизводятся). А потоков у
        #нас реально несколько: фоновый цикл синка, прокси мессенджера внутри локального
        #сервера, отправка темы, закрытие программы. Замок сеанса в sync_engine защищает
        #только сам цикл, но не эти вызовы. Держим сессию в thread-local: у каждого потока
        #своя, keep-alive при этом сохраняется (потоки долгоживущие).
        self._local = threading.local()
        self._warn_if_insecure()

    def _sess(self, retry_post: bool):
        """Сессия ЭТОГО потока. `retry_post` — можно ли повторять POST (см. _build_session)."""
        key = "idem" if retry_post else "plain"
        got = getattr(self._local, key, None)
        if got is None:
            got = self._build_session(retry_post)
            setattr(self._local, key, got)
        return got

    @staticmethod
    def _build_session(retry_post: bool = False):
        """Сессия с АВТО-РЕТРАЯМИ на транзиентные сетевые сбои. Одиночный блип канала
        до РФ-VPS (обрыв соединения `RemoteDisconnected`, кратковременный отказ TCP,
        502/503/504 от Caddy/Cloudflare, пока бэкенд перезапускается) повторяется на
        уровне HTTP и НЕ доходит до синк-раннера как «сбой» — синхронизация проходит
        прозрачно, а лог не засоряется. Бэкофф между попытками: 0.6 → 1.2 → 2.4 c."""
        s = requests.Session()
        try:
            from urllib3.util.retry import Retry
            from requests.adapters import HTTPAdapter
            retry = Retry(
                total=3, connect=3, read=2, backoff_factor=0.6,
                status_forcelist=(502, 503, 504),
                #🔥 POST ЗДЕСЬ НЕ ПОВТОРЯЕМ. Раньше повторялся с оговоркой «наши POST
                #идемпотентны» — это верно ровно для трёх из них (push сверяет содержимое,
                #login/refresh безопасны), но НЕ для остальных: `create_event`,
                #`approve_registration`, `create_parent`, `create_parent_link` (методы
                #нативной админки, 30.09.2026 перенесены в archive/fragments) при
                #повторе создавали ВТОРУЮ запись. Правило остаётся для любого нового POST. Блип сети на такой отправке давал бы
                #дубль заявки или родителя — молча, потому что оба запроса «успешны».
                #Идемпотентные вызовы просят повтор явно: `_req(..., retry_post=True)`.
                allowed_methods=(frozenset(["GET", "PUT", "DELETE", "HEAD", "OPTIONS",
                                            "POST"]) if retry_post else
                                 frozenset(["GET", "PUT", "DELETE", "HEAD", "OPTIONS"])),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
        except Exception as e:
            #Без ретраев работать можно, но знать об этом надо: одиночный блип канала
            #станет «сбоем синка» вместо прозрачного повтора.
            _log.warning("авто-ретраи HTTP недоступны (%s) — блипы сети пойдут как сбои", e)
        return s

    def _warn_if_insecure(self):
        """Предупреждаем, если адрес сервера — http к удалённому хосту: тогда ПДн
        (логины, пароли, оценки) пойдут по сети открытым текстом. Не блокируем —
        в ЛВС на этапе настройки это бывает временно нужно, но админ должен знать."""
        try:
            from data import app_settings
            if self.base_url and not app_settings.is_secure_transport(self.base_url):
                _log.warning("сервер задан по http:// к удалённому адресу — персональные "
                             "данные пойдут по сети В ОТКРЫТОМ виде. Для боевой работы "
                             "нужен https:// (server/DEPLOY.md, раздел про Caddy и TLS)")
        except Exception as e:
            _log.debug("проверка безопасности адреса не выполнена: %s", e)

    def _headers(self) -> dict:
        #ngrok-skip-browser-warning — чтобы бесплатные туннели (ngrok и пр.) не
        #подсовывали HTML-страницу-предупреждение вместо JSON ответа API.
        h = {"ngrok-skip-browser-warning": "true"}
        #X-Device-Id — идентификатор этого ПК для барьера подтверждения: сервер по
        #нему решает, одобрено ли устройство (см. server/app/connect.py). Шлём на КАЖДОМ
        #запросе, в т.ч. при входе — иначе неодобренный ПК не отличить от одобренного.
        try:
            from data import app_settings
            dev = app_settings.get_device_id()
            if dev:
                h["X-Device-Id"] = dev
        except Exception:
            pass
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _req(self, method: str, path: str, timeout=DEFAULT_TIMEOUT,
             retry_post: bool = False, **kwargs):
        """Единая точка сетевого вызова: общие заголовки, проверка TLS (verify) и
        авто-ретраи в одном месте — их нельзя случайно забыть.

        `retry_post=True` ставят ТОЛЬКО вызовы, безопасные к повтору: `push` (сервер
        делает upsert по ключу), `login`/`refresh` (повтор выдаёт новый токен, лишних
        сущностей не создаёт). Всё остальное, что создаёт записи, повторять нельзя —
        см. комментарий в `_build_session`."""
        return self._sess(retry_post).request(method, f"{self.base_url}{path}",
                                              headers=self._headers(), timeout=timeout,
                                              verify=self._verify, **kwargs)

    def health(self) -> bool:
        """True, если сервер отвечает. Не кидает исключений.

        ВАЖНО: health БЕЗ авто-ретраев (обычный requests, не self._session) — он должен
        падать БЫСТРО. Его зовут UI-блокирующие пути: вход (_online_bootstrap ставит
        WaitCursor) и закрытие приложения (flush_now). С ретраями (3× connect) оффлайн-
        вход/закрытие висли бы ~18 c. Ретраи нужны фоновому pull/push, а не этой пробе."""
        try:
            r = requests.get(f"{self.base_url}/health", headers=self._headers(),
                             timeout=HEALTH_TIMEOUT, verify=self._verify)
            return r.status_code == 200
        except Exception:
            return False

    def login(self, login: str, password: str) -> dict:
        """Возвращает {access_token, refresh_token, role, name} и запоминает оба токена."""
        r = self._req("POST", "/auth/login", retry_post=True,
                      json={"login": login, "password": password})
        r.raise_for_status()
        data = r.json()
        #Код 200 без токена — дефект контракта сервера. Молча остаться без авторизации
        #нельзя: дальше все запросы пошли бы анонимными и получали 401 без объяснения.
        if not data.get("access_token"):
            raise ValueError("сервер ответил успехом, но не выдал access_token")
        self.token = data["access_token"]
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
        #Код 200 без токена — дефект контракта сервера. Молча остаться без авторизации
        #нельзя: дальше все запросы пошли бы анонимными и получали 401 без объяснения.
        if not data.get("access_token"):
            raise ValueError("сервер ответил успехом, но не выдал access_token")
        self.token = data["access_token"]
        self.refresh_token = data.get("refresh_token", "") or self.refresh_token
        return data

    def refresh(self, refresh_token: str | None = None) -> dict:
        """Тихо обновляет access по refresh-токену (/auth/refresh). Обновляет self.token
        и возвращает данные {access_token, refresh_token, role, name}. Бросает HTTPError,
        если refresh недействителен/отозван — тогда вызывающий делает полный re-login."""
        rt = (refresh_token or self.refresh_token or "").strip()
        if not rt:
            raise ValueError("нет refresh-токена для обновления")
        r = self._req("POST", "/auth/refresh", json={"refresh_token": rt}, retry_post=True)
        r.raise_for_status()
        data = r.json()
        self.token = data.get("access_token") or self.token
        self.refresh_token = data.get("refresh_token", "") or self.refresh_token
        return data

    def pull(self, since: str = "") -> dict:
        """Изменения позже метки since. Возвращает {server_time, changes}.
        Долгий read-таймаут: первый полный pull может быть большим на медленном канале."""
        r = self._req("GET", "/sync/pull", params={"since": since}, timeout=SYNC_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def pull_page(self, cursor: int = 0, limit: int = 2000, scope: str = "",
                  epoch: str = "") -> dict:
        """Страница изменений по НОМЕРУ (боевой сервер 4.1+, `/sync/pull?cursor=`).

        Ответ — {cursor, more, head, scope, epoch, changes, removed} или {reset: причина}.
        Сервер до 4.1 параметр `cursor` не знает и отвечает прежним {server_time,
        changes}: по отсутствию `cursor` в ответе зеркало и узнаёт, что говорит со старым
        боем, и идёт прежним путём (`desktop/local_mirror.py`)."""
        params: dict[str, object] = {"cursor": int(cursor or 0), "limit": int(limit or 2000)}
        if scope:
            params["scope"] = scope
        if epoch:
            params["epoch"] = epoch
        r = self._req("GET", "/sync/pull", params=params, timeout=SYNC_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def head(self, after: int = -1, wait: int = 0) -> dict:
        """Номер головы потока боя; с `wait` — долгий опрос до правки (W-20).

        Таймаут чтения — ожидание плюс запас: иначе клиент сам обрывал бы ответ, который
        сервер честно держит до `wait` секунд."""
        r = self._req("GET", "/sync/head", params={"after": int(after), "wait": int(wait)},
                      timeout=(8, int(wait or 0) + 15))
        r.raise_for_status()
        return r.json()

    def digest(self) -> dict:
        """Отпечаток того, что копия обязана содержать (`/sync/digest`, «Сверщик»)."""
        r = self._req("GET", "/sync/digest", timeout=SYNC_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def push(self, changes: dict) -> dict:
        """Отправляет изменения. changes = {users:[...], grades:[...], ...}.
        Долгий read-таймаут: первый пуш накопленного офлайн бывает объёмным."""
        r = self._req("POST", "/sync/push", json={"changes": changes},
                      timeout=SYNC_TIMEOUT, retry_post=True)
        r.raise_for_status()
        return r.json()

    def voice(self, facts_text: str, role: str = "student", question: str = "") -> str:
        """Озвучка готовых фактов LLM на СЕРВЕРЕ (токен провайдера ИИ живёт только там,
        не раздаётся на клиентские ПК — 152-ФЗ). Шлём уже посчитанный обезличенный текст,
        получаем переформулированный. Заголовки (в т.ч. X-Device-Id) ставит _req."""
        r = self._req("POST", "/vector/voice",
                      json={"facts": facts_text, "role": role, "question": question},
                      timeout=30)
        r.raise_for_status()
        return (r.json().get("text") or facts_text).strip()

    def set_my_prefs(self, prefs: dict) -> dict:
        """Сохранить личные настройки текущего пользователя (self-scope /me/prefs).
        Меняет ТОЛЬКО свою строку — личность берётся из JWT на сервере."""
        r = self._req("POST", "/me/prefs", json={"prefs": prefs}, timeout=5)
        r.raise_for_status()
        return r.json()


