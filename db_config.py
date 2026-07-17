"""
db_config.py — Настройка подключения к PostgreSQL и система лицензионных ключей.

КАК РАБОТАЕТ СИНХРОНИЗАЦИЯ:
─────────────────────────────
1. Администратор один раз настраивает подключение к PostgreSQL-серверу.
2. Программа генерирует КЛЮЧ УСТАНОВКИ (UUID) — уникальный для каждого ПК.
3. Администратор вводит этот ключ в панели администратора, чтобы разрешить доступ.
4. После активации ВСЕ данные (оценки, студенты, занятия) хранятся в PostgreSQL.
5. Все ПК в сети работают с ОДНОЙ базой — синхронизация мгновенная.

ФАЙЛ pg_config.json лежит рядом с .exe и содержит:
{
  "host": "192.168.1.100",
  "port": 5432,
  "database": "vsgutu_grades",
  "user": "vsgutu_user",
  "password_enc": "<пароль БД, зашифрованный Windows DPAPI>",
  "install_key": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}

⚠️ Пароль БД НЕ хранится открытым текстом: поле password_enc защищено DPAPI и
привязано к учётной записи Windows (см. security.os_protect). Старые файлы с
открытым полем "password" по-прежнему читаются и при следующем сохранении
автоматически перешифровываются.

⚠️ 152-ФЗ ст. 18 ч. 5 (локализация): сервер PostgreSQL должен физически
находиться на территории РФ (сервер/ПК колледжа в локальной сети или российское
облако). Не размещайте боевую базу с ПДн на зарубежном хостинге.
"""
import os
import sys
import json
import uuid
import base64

CONFIG_FILE = "pg_config.json"
KEY_FILE    = "install_key.txt"   # служебный, в папке данных (см. app_paths)


# ── Защита пароля БД на диске (DPAPI) ───────────────────────────
def _encrypt_pw(plain: str) -> str:
    """Шифрует пароль БД для хранения в pg_config.json (DPAPI → base64)."""
    if not plain:
        return ""
    try:
        from security import os_protect
        return base64.b64encode(os_protect(plain.encode("utf-8"))).decode("ascii")
    except Exception as e:
        print(f"[db_config] не удалось зашифровать пароль БД: {e}")
        return ""


def _decrypt_pw(enc: str) -> str:
    """Расшифровывает password_enc. Возвращает '' при неудаче."""
    if not enc:
        return ""
    try:
        from security import os_unprotect
        raw = os_unprotect(base64.b64decode(enc.encode("ascii")))
        return raw.decode("utf-8") if raw else ""
    except Exception as e:
        print(f"[db_config] не удалось расшифровать пароль БД: {e}")
        return ""

#  Расположение файлов — через единый app_paths (рядом с .exe или в профиле).
import app_paths

_APP_DIR = app_paths.app_dir()
_CONFIG_PATH = app_paths.app_file(CONFIG_FILE)        # pg_config.json — правится руками
_KEY_PATH    = app_paths.data_file(KEY_FILE)          # install_key.txt — служебный


#  Ключ установки (уникален для каждого ПК)
def get_install_key() -> str:
    """
    Возвращает ключ этой установки.
    При первом запуске генерирует и сохраняет его в install_key.txt.
    Ключ выглядит как: VSGT-A1B2-C3D4-E5F6
    """
    if os.path.exists(_KEY_PATH):
        try:
            with open(_KEY_PATH, "r") as f:
                key = f.read().strip()
            if key:
                return key
        except Exception:
            pass
    # Генерируем новый ключ
    raw = uuid.uuid4().hex.upper()
    key = f"VSGT-{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"
    try:
        with open(_KEY_PATH, "w") as f:
            f.write(key)
    except Exception:
        pass
    return key


#  Конфигурация PostgreSQL
_DEFAULT_CONFIG = {
    "host": "",
    "port": 5432,
    "database": "vsgutu_grades",
    "user": "",
    "password": "",
    "install_key": get_install_key()
}


def load_pg_config() -> dict:
    """Загружает конфигурацию из pg_config.json.
    Пароль БД возвращается в открытом виде В ПАМЯТИ (поле password) — на диске он
    хранится зашифрованным (password_enc). Старый открытый password тоже читаем."""
    if not os.path.exists(_CONFIG_PATH):
        return dict(_DEFAULT_CONFIG)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Гарантируем наличие install_key
        if not cfg.get("install_key"):
            cfg["install_key"] = get_install_key()
        # Восстанавливаем пароль: приоритет у зашифрованного поля.
        if cfg.get("password_enc"):
            cfg["password"] = _decrypt_pw(cfg["password_enc"])
        # иначе остаётся старый открытый cfg["password"] (перешифруется при save)
        return cfg
    except Exception:
        return dict(_DEFAULT_CONFIG)


def save_pg_config(cfg: dict) -> bool:
    """Сохраняет конфигурацию в pg_config.json. Пароль шифруется через DPAPI,
    открытым текстом на диск не попадает."""
    try:
        out = dict(cfg)
        if not out.get("install_key"):
            out["install_key"] = get_install_key()
        # Пароль на диск — только зашифрованным.
        out["password_enc"] = _encrypt_pw(out.get("password", ""))
        out.pop("password", None)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def is_pg_configured() -> bool:
    """Возвращает True если PostgreSQL настроен (заполнены host и user)."""
    cfg = load_pg_config()
    return bool(cfg.get("host") and cfg.get("user"))


#  Подключение к PostgreSQL
def get_pg_connection(cfg: dict = None):
    """
    Возвращает соединение psycopg2 с PostgreSQL.
    Бросает исключение если не удалось подключиться.
    """
    try:
        import psycopg2
    except ImportError:
        raise RuntimeError(
            "Библиотека psycopg2 не установлена.\n"
            "Выполните: pip install psycopg2-binary"
        )
    if cfg is None:
        cfg = load_pg_config()
    # sslmode: шифрование канала к серверу (152-ФЗ — защита ПДн при передаче).
    # По умолчанию "prefer" (использует TLS, если сервер поддерживает; иначе обычное
    # соединение — не ломает локальные стенды). Для боевого сервера задайте "require"
    # в pg_config.json, чтобы соединение без TLS было запрещено.
    conn = psycopg2.connect(
        host=cfg.get("host", "localhost"),
        port=int(cfg.get("port", 5432)),
        database=cfg.get("database", "vsgutu_grades"),
        user=cfg.get("user", ""),
        password=cfg.get("password", ""),
        sslmode=cfg.get("sslmode", "prefer"),
        connect_timeout=5
    )
    return conn


def test_connection(cfg: dict = None) -> tuple:
    """
    Проверяет подключение к PostgreSQL.
    Возвращает (True, "версия сервера") или (False, "ошибка").
    """
    try:
        conn = get_pg_connection(cfg)
        cur = conn.cursor()
        cur.execute("SELECT version()")
        ver = cur.fetchone()[0]
        conn.close()
        return True, ver
    except Exception as e:
        return False, str(e)


