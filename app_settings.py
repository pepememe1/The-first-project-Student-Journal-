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
import json
from urllib.parse import urlparse

import app_paths

#Боевая сборка: сюда впишем адрес сервера ВСГУТУ. Для боевой работы — https://
#(ПДн по сети только в шифрованном канале, 152-ФЗ). Пример: "https://journal.vsgutu.ru".
DEFAULT_API_URL = ""

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
        print(f"[app_settings] миграция api_config.json пропущена: {e}")


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
        print(f"[app_settings] чтение адреса сервера из БД пропущено: {e}")
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
        print(f"[app_settings] не удалось сохранить адрес сервера: {e}")
        return False


def has_api_url() -> bool:
    """Задан ли адрес сервера. Нужно для стартовой проверки: если нет — программа
    предлагает ввести адрес запущенного сервера для синхронизации."""
    return bool(get_api_url())


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


def dev_tunnel_enabled() -> bool:
    """Историческая «ручка»: показывать ли serveo как dev/demo-инструмент.

    С версии 2.5.1 serveo вынесен в обычный выбор типа сервера в админке (с явным
    предупреждением про 152-ФЗ), поэтому отдельный флаг больше не прячет UI. Функция
    оставлена для совместимости и для dev-сценариев, где он ещё может опрашиваться.
    Включается переменной окружения GRADEBOOK_ENABLE_TUNNEL=1."""
    val = os.environ.get("GRADEBOOK_ENABLE_TUNNEL", "").strip().lower()
    return val in ("1", "true", "yes", "on")
