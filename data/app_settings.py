"""
app_settings.py — Локальные настройки ПК (НЕ синхронизируются).

Главное здесь — адрес сервера синхронизации (API). Его нельзя тянуть из самой
синхронизации (новый ПК не узнал бы, куда подключаться), поэтому он задаётся
локально на КАЖДОМ ПК.

Где он хранится. Раньше адрес лежал в файле api_config.json рядом с программой —
его правили руками (Блокнотом), и это был костыль. Теперь адрес живёт «в самой
программе»: в локальном ключе её БД (data_store.local_get/local_set), не уезжает
на сервер и задаётся через интерфейс (окно при запуске / вкладка «Сервер»).
Старый api_config.json, если он остался от прежней версии, один раз подхватывается
и удаляется (см. _migrate_legacy_json).

Порядок определения адреса (по приоритету):
  1. локальная настройка в БД (то, что ввели в программе);
  2. переменная окружения GRADEBOOK_API_URL (удобно для разработки);
  3. зашитый в сборку DEFAULT_API_URL (для боевой поставки — заполнить).

Пустой адрес = офлайн-режим без сервера: прога работает только локально (это
штатный режим, не ошибка).
"""
import os
import log
import json
from urllib.parse import urlparse

import app_paths

#Боевая сборка: адрес сервера ВСГУТУ, вшитый в .exe. Для боевой работы — https://
#(ПДн по сети только в шифрованном канале, 152-ФЗ). Его можно переопределить в
#программе (вкладка «Сервер и сайт» → «Адрес сайта и онлайн-базы»).
DEFAULT_API_URL = "https://esstu-gradebook.ru"

#Телефон поддержки — показывается в окне подключения («за ссылкой и подробностями
#обратитесь в поддержку»). Меняется здесь, в коде.
SUPPORT_PHONE = "+7 (000) 000-00-00"

#Адрес сайта журнала (тот же сервер, что и БД — в перспективе). Кнопка «Войти через
#сайт» открывает его в браузере. Меняется здесь, в коде. Пусто — кнопку прячем.
SITE_URL = ""

#Ключ локальной настройки с адресом сервера (в data_store, префикс "_local:").
_API_URL_KEY = "api_url"

#Старый файл-костыль. БОЛЬШЕ НЕ СОЗДАЁМ — оставлен только для разовой миграции
#адреса со старых установок и последующего удаления файла.
_LEGACY_API_CONFIG_FILE = "api_config.json"
_migrated = False


def is_secure_transport(url: str) -> bool:
    """Безопасен ли канал к серверу.

    Безопасным считаем https (шифрование в пути) и http к локальной петле
    (127.0.0.1/localhost — трафик не покидает машину, это dev-режим). http к
    УДАЛЁННОМУ хосту небезопасен: логины, пароли и оценки пойдут по сети открытым
    текстом. Пустой адрес = офлайн без сервера, течь нечему — тоже «безопасно».

    Нужно, чтобы предупредить администратора до того, как ПДн уедут незашифрованными
    (см. SyncClient), а не постфактум."""
    url = (url or "").strip()
    if not url:
        return True
    p = urlparse(url)
    if p.scheme == "https":
        return True
    host = (p.hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def _migrate_legacy_json():
    """Однократно переносит адрес из старого api_config.json в БД и удаляет файл.

    Раньше адрес сервера лежал в json рядом с программой; теперь он хранится в
    самой программе. Чтобы апгрейд со старой версии не потерял настройку — один раз
    подбираем адрес из файла (если локально ещё пусто) и убираем сам файл, чтобы он
    не сбивал с толку и не «воскрешал» устаревший адрес при следующих запусках."""
    global _migrated
    if _migrated:
        return
    _migrated = True
    try:
        p = app_paths.app_file(_LEGACY_API_CONFIG_FILE)
        if not os.path.exists(p):
            return
        with open(p, "r", encoding="utf-8") as f:
            url = ((json.load(f) or {}).get("api_url", "") or "").strip()
        if url:
            from data_store import local_get, local_set
            if not (local_get(_API_URL_KEY) or "").strip():
                local_set(_API_URL_KEY, url)
        os.remove(p)   #файл-костыль больше не нужен
    except Exception as e:
        log.get("app_settings").warning(f"[app_settings] миграция api_config.json пропущена: {e}")


def get_api_url() -> str:
    """Адрес сервера синхронизации или '' (тогда — офлайн без сервера).
    Порядок: настройка в БД → переменная окружения (dev) → зашитый дефолт."""
    _migrate_legacy_json()
    try:
        from data_store import local_get
        url = (local_get(_API_URL_KEY) or "").strip()
        if url:
            return url
    except Exception as e:
        #БД ещё не готова или недоступна — не падаем, пробуем запасные источники.
        log.get("app_settings").warning(f"[app_settings] чтение адреса сервера из БД пропущено: {e}")
    env = os.environ.get("GRADEBOOK_API_URL", "").strip()
    if env:
        return env
    return DEFAULT_API_URL.strip()


def set_api_url(url: str) -> bool:
    """Сохраняет адрес сервера В ПРОГРАММЕ (локальный ключ БД, не синхронизируется)."""
    url = (url or "").strip()
    try:
        from data_store import local_set
        ok = local_set(_API_URL_KEY, url)
        #Задали адрес — значит офлайн-режим больше не подразумевается, снимаем флаг,
        #чтобы стартовая проверка снова работала штатно, если адрес потом очистят.
        if ok and url:
            local_set(_OFFLINE_ACK_KEY, False)
        return ok
    except Exception as e:
        log.get("app_settings").warning(f"[app_settings] не удалось сохранить адрес сервера: {e}")
        return False


#Флаг «работать офлайн» — чтобы при сознательном выборе офлайн-режима не спрашивать
#адрес при каждом запуске. Сбрасывается, как только адрес задан.
_OFFLINE_ACK_KEY = "offline_ack"


def get_offline_ack() -> bool:
    try:
        from data_store import local_get
        return bool(local_get(_OFFLINE_ACK_KEY, False))
    except Exception:
        return False


def set_offline_ack(value: bool) -> bool:
    try:
        from data_store import local_set
        return local_set(_OFFLINE_ACK_KEY, bool(value))
    except Exception:
        return False


#Признак ПК-хоста (на нём администратор поднимает сервер). Нужен, чтобы стартовое
#окно «введите адрес сервера» НЕ доставало администратора: иначе вышел бы замкнутый
#круг — адрес появляется только ПОСЛЕ запуска сервера, а ввести его просили бы ДО
#входа. Флаг ставится при входе администратора и при запуске сервера из админки.
_HOST_FLAG_KEY = "is_host"


def is_host() -> bool:
    """True, если этот ПК уже выступал хостом (вход админа / запуск сервера)."""
    try:
        from data_store import local_get
        return bool(local_get(_HOST_FLAG_KEY, False))
    except Exception:
        return False


def mark_host(value: bool = True) -> bool:
    try:
        from data_store import local_set
        return local_set(_HOST_FLAG_KEY, bool(value))
    except Exception:
        return False


#Автозапуск сервера на ПК-хосте. Чтобы связь была ПОСТОЯННОЙ: хост поднимает свой
#сервер сам при каждом старте программы — без входа администратора и без ручной
#кнопки. Тогда админ может спокойно выйти из своего аккаунта (сервер живёт в
#фоновом потоке до закрытия программы), а после перезапуска сервер встаёт сам.
#Флаг ставится при удачном запуске сервера из админки и снимается при ручной
#остановке (явная остановка = «больше не поднимать автоматически»).
_HOST_AUTOSTART_KEY = "host_autostart"


def host_autostart_enabled() -> bool:
    """True, если этот ПК-хост должен сам поднимать свой сервер при старте программы."""
    try:
        from data_store import local_get
        return bool(local_get(_HOST_AUTOSTART_KEY, False))
    except Exception:
        return False


def set_host_autostart(value: bool = True) -> bool:
    try:
        from data_store import local_set
        return local_set(_HOST_AUTOSTART_KEY, bool(value))
    except Exception:
        return False


#Отложенная отправка личных настроек (темы оформления). Если в момент «Сохранить»
#сервер недоступен или ещё нет токена, отправка self-эндпоинта POST /me/prefs не
#удаётся. Раньше тему в этом случае просто теряли для БД (она оставалась только
#локально и не «роумилась» на другие ПК). Теперь складываем prefs сюда и до-
#отправляем при следующей удачной синхронизации. Привязано к логину: на общем ПК
#«хвост» одного пользователя не уедет от имени другого.
_PENDING_PREFS_KEY = "pending_prefs"


def get_pending_prefs(login: str):
    """Отложенные prefs именно для ЭТОГО логина (None — нет либо принадлежат другому)."""
    try:
        from data_store import local_get
        rec = local_get(_PENDING_PREFS_KEY, None) or {}
        if isinstance(rec, dict) and rec.get("login") == (login or ""):
            return rec.get("prefs") or None
    except Exception:
        pass
    return None


def set_pending_prefs(login: str, prefs: dict) -> bool:
    try:
        from data_store import local_set
        return local_set(_PENDING_PREFS_KEY, {"login": login or "", "prefs": prefs or {}})
    except Exception:
        return False


def clear_pending_prefs() -> bool:
    try:
        from data_store import local_set
        return local_set(_PENDING_PREFS_KEY, {})
    except Exception:
        return False


#Сохранённый токен доступа (JWT) для переиспользования между ЗАПУСКАМИ программы.
#Зачем: при каждом старте логиниться к API заново — значит гонять дорогой PBKDF2 на
#сервере; когда так делают сотни ПК в 9:00, это «герд» входов и упор в CPU. Сохранив
#валидный токен, при следующем старте мы пропускаем вход по паролю. Токен — bearer,
#поэтому лежит ЗАШИФРОВАННЫМ (как прочие локальные данные, DPAPI/Fernet) и привязан к
#логину; сервер всё равно проверяет его подпись и срок. Значение НЕ логируем.
_TOKEN_KEY = "api_token"


def get_saved_token(login: str) -> str:
    """Сохранённый JWT именно для ЭТОГО логина ('' — нет либо принадлежит другому)."""
    try:
        from data_store import local_get
        rec = local_get(_TOKEN_KEY, None) or {}
        if isinstance(rec, dict) and rec.get("login") == (login or ""):
            return rec.get("token", "") or ""
    except Exception:
        pass
    return ""


def set_saved_token(login: str, token: str) -> bool:
    try:
        from data_store import local_set
        return local_set(_TOKEN_KEY, {"login": login or "", "token": token or ""})
    except Exception:
        return False


def clear_saved_token() -> bool:
    try:
        from data_store import local_set
        return local_set(_TOKEN_KEY, {})
    except Exception:
        return False


#Refresh-токен: долгоживущий, им ТИХО обновляют короткий access, не выкидывая
#пользователя на логин (например, если access протух за время офлайна). Даёт доступ к
#API так же, как access, поэтому хранится ТОЧНО ТАК ЖЕ — зашифрованным (DPAPI/Fernet)
#и привязанным к логину; сервер проверяет его подпись, срок и чёрный список. НЕ логируем.
_REFRESH_TOKEN_KEY = "api_refresh_token"


def get_saved_refresh_token(login: str) -> str:
    """Сохранённый refresh-токен для ЭТОГО логина ('' — нет либо принадлежит другому)."""
    try:
        from data_store import local_get
        rec = local_get(_REFRESH_TOKEN_KEY, None) or {}
        if isinstance(rec, dict) and rec.get("login") == (login or ""):
            return rec.get("token", "") or ""
    except Exception:
        pass
    return ""


def set_saved_refresh_token(login: str, token: str) -> bool:
    try:
        from data_store import local_set
        return local_set(_REFRESH_TOKEN_KEY, {"login": login or "", "token": token or ""})
    except Exception:
        return False


def clear_saved_refresh_token() -> bool:
    try:
        from data_store import local_set
        return local_set(_REFRESH_TOKEN_KEY, {})
    except Exception:
        return False


#Сохранённая СЕССИЯ для персистентного входа: чтобы после закрытия программы при
#следующем старте сразу попасть в свой аккаунт, не вводя логин/пароль заново. Храним
#только логин и роль (НЕ пароль) в локальном ключе — доступ к серверу держит сохранённый
#токен (_TOKEN_KEY). Лежит под префиксом `_local:`, поэтому переживает сброс кэша данных
#(reset_synced_local_data чистит students/teachers/grades, но не локальные настройки).
_SESSION_KEY = "session"


def get_saved_session() -> dict:
    """{'login':..., 'role':...} последнего входа ({} — нет сохранённой сессии)."""
    try:
        from data_store import local_get
        rec = local_get(_SESSION_KEY, None) or {}
        return rec if isinstance(rec, dict) and rec.get("login") else {}
    except Exception:
        return {}


def set_saved_session(login: str, role: str) -> bool:
    try:
        from data_store import local_set
        return local_set(_SESSION_KEY, {"login": login or "", "role": role or ""})
    except Exception:
        return False


def clear_saved_session() -> bool:
    try:
        from data_store import local_set
        return local_set(_SESSION_KEY, {})
    except Exception:
        return False


#Идентификатор ЭТОГО устройства (ПК) для барьера подтверждения подключения. Сервер
#пускает к входу/синхронизации только одобренные администратором device_id (и сам
#хост). Генерится один раз и хранится локально (в БД ПК, не синхронизируется), чтобы
#переживать перезапуски: иначе после каждого запуска ПК выглядел бы «новым» и просил
#подтверждение заново.
_DEVICE_ID_KEY = "device_id"


def get_device_id() -> str:
    """Стабильный идентификатор этого ПК (создаётся при первом обращении)."""
    try:
        from data_store import local_get, local_set
        dev = (local_get(_DEVICE_ID_KEY, "") or "").strip()
        if not dev:
            import uuid
            dev = uuid.uuid4().hex
            local_set(_DEVICE_ID_KEY, dev)
        return dev
    except Exception as e:
        #БД ещё не готова — отдаём непустую заглушку, чтобы запрос не падал; на
        #следующем обращении (БД готова) сгенерируется и сохранится постоянный id.
        log.get("app_settings").warning(f"[app_settings] device_id временно недоступен: {e}")
        return ""


#Локальный признак «этот ПК уже прошёл барьер подтверждения» (UX-кэш, не безопасность —
#реально доступ решает сервер по таблице одобренных). Нужен, чтобы не дёргать окно
#подтверждения на уже подключённом ПК.
_DEVICE_CONNECTED_KEY = "device_connected"


def is_device_connected() -> bool:
    try:
        from data_store import local_get
        return bool(local_get(_DEVICE_CONNECTED_KEY, False))
    except Exception:
        return False


def set_device_connected(value: bool = True) -> bool:
    try:
        from data_store import local_set
        return local_set(_DEVICE_CONNECTED_KEY, bool(value))
    except Exception:
        return False


def dev_tunnel_enabled() -> bool:
    """Историческая «ручка»: показывать ли serveo как dev/demo-инструмент.

    Сейчас serveo вынесен в обычный выбор типа сервера в админке (с явным
    предупреждением про 152-ФЗ), поэтому отдельный флаг больше не прячет UI. Функция
    оставлена для совместимости и для dev-сценариев, где он ещё может опрашиваться.
    Включается переменной окружения GRADEBOOK_ENABLE_TUNNEL=1."""
    val = os.environ.get("GRADEBOOK_ENABLE_TUNNEL", "").strip().lower()
    return val in ("1", "true", "yes", "on")
