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
  "password": "пароль",
  "install_key": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
"""
import os
import sys
import json
import uuid
import hashlib

CONFIG_FILE = "pg_config.json"
KEY_FILE    = "install_key.txt"   # хранится в APPDATA для единого ключа на ПК

#  Определение папок
def _get_app_dir() -> str:
    """Папка рядом с .exe / main.py — для pg_config.json."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def _get_data_dir() -> str:
    """Папка данных пользователя (APPDATA\\GradeBookAI) — для install_key.txt."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~")
    app_dir = os.path.join(base, "GradeBookAI")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

_APP_DIR = _get_app_dir()
_CONFIG_PATH = os.path.join(_APP_DIR, CONFIG_FILE)
_KEY_PATH    = os.path.join(_get_data_dir(), KEY_FILE)  # APPDATA\GradeBookAI\install_key.txt


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


def get_key_hash(key: str) -> str:
    """SHA-256 хэш ключа для хранения в БД (не сам ключ)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


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
    """Загружает конфигурацию из pg_config.json."""
    if not os.path.exists(_CONFIG_PATH):
        return dict(_DEFAULT_CONFIG)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Гарантируем наличие install_key
        if not cfg.get("install_key"):
            cfg["install_key"] = get_install_key()
        return cfg
    except Exception:
        return dict(_DEFAULT_CONFIG)


def save_pg_config(cfg: dict) -> bool:
    """Сохраняет конфигурацию в pg_config.json."""
    try:
        if not cfg.get("install_key"):
            cfg["install_key"] = get_install_key()
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
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
    conn = psycopg2.connect(
        host=cfg.get("host", "localhost"),
        port=int(cfg.get("port", 5432)),
        database=cfg.get("database", "vsgutu_grades"),
        user=cfg.get("user", ""),
        password=cfg.get("password", ""),
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


#  Проверка активации ключа
def is_key_activated(cfg: dict = None) -> bool:
    """Проверяет, активирован ли ключ этого ПК в PostgreSQL."""
    try:
        conn = get_pg_connection(cfg)
        cur = conn.cursor()
        key = get_install_key()
        key_hash = get_key_hash(key)
        cur.execute(
            "SELECT active FROM install_keys WHERE key_hash = %s",
            (key_hash,)
        )
        row = cur.fetchone()
        conn.close()
        return bool(row and row[0])
    except Exception:
        return False
