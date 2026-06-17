"""
keyvault.py — Общий ключ шифрования организации (DEK) для мульти-ПК.

Зачем:
  Данные в kv_store (пароль администратора, студенты, преподаватели, ключи API)
  шифруются симметричным ключом. Чтобы ВСЕ ПК колледжа, работающие с общей базой
  PostgreSQL, могли читать одни и те же данные, ключ шифрования (DEK) должен быть
  ОБЩИМ. Раньше ключ был у каждого ПК свой — поэтому ПК не мог расшифровать данные,
  записанные другим ПК.

Как устроено:
  • DEK (32 байта) генерируется один раз на установку.
  • В PostgreSQL хранится DEK, ЗАВЁРНУТЫЙ в «пароль установки» (org-passphrase):
        wrapped = Fernet(PBKDF2(passphrase, salt)).encrypt(DEK)
    Сам пароль установки в базе не хранится — только соль и зашифрованный DEK.
  • На каждом ПК пароль установки вводится ОДИН раз; затем DEK кэшируется локально
    через Windows DPAPI (привязка к учётной записи) и больше не запрашивается.
  • Первый ПК создаёт DEK и пароль установки; остальные — вводят пароль установки
    один раз и забирают DEK из PG.

Локальный режим (PostgreSQL не настроен): общий ключ не нужен — используется
локальный ключ (security.get_data_key). Пароль установки не спрашивается.

⚠️ Затрагивает шифрование и синхронизацию — менять осторожно.
"""

import os
import sys
import base64
import hashlib
import secrets

from security import os_protect, os_unprotect, _require_crypto

_KEK_ITERS = 200_000


# ── Пути локального кэша ─────────────────────────────────────────
def _local_cache_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~")
    d = os.path.join(base, "GradeBookAI")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "org.key")


# ── Заворачивание/разворачивание DEK паролем установки ───────────
def wrap_dek(dek: bytes, passphrase: str) -> str:
    """DEK → base64(salt + Fernet(PBKDF2(passphrase)).encrypt(DEK))."""
    _require_crypto()
    from cryptography.fernet import Fernet
    salt = secrets.token_bytes(16)
    kek = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, _KEK_ITERS, dklen=32)
    token = Fernet(base64.urlsafe_b64encode(kek)).encrypt(dek)
    return base64.b64encode(salt + token).decode("ascii")


def unwrap_dek(blob: str, passphrase: str) -> bytes:
    """Обратная операция. Возвращает b'' при неверном пароле/повреждении."""
    _require_crypto()
    from cryptography.fernet import Fernet, InvalidToken
    try:
        raw = base64.b64decode(blob.encode("ascii"))
        salt, token = raw[:16], raw[16:]
        kek = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, _KEK_ITERS, dklen=32)
        return Fernet(base64.urlsafe_b64encode(kek)).decrypt(token)
    except (InvalidToken, Exception):
        return b""


# ── Локальный DPAPI-кэш DEK ──────────────────────────────────────
def load_local_dek() -> bytes:
    """Читает DEK из локального DPAPI-кэша. b'' если нет/не вышло."""
    path = _local_cache_path()
    if not os.path.exists(path):
        return b""
    try:
        with open(path, "rb") as f:
            raw = f.read()
        dek = os_unprotect(raw)
        return dek if len(dek) == 32 else b""
    except Exception:
        return b""


def save_local_dek(dek: bytes):
    """Сохраняет DEK в локальный DPAPI-кэш."""
    path = _local_cache_path()
    try:
        with open(path, "wb") as f:
            f.write(os_protect(dek))
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception as e:
        print(f"[keyvault] не удалось сохранить локальный кэш ключа: {e}")


# ── Хранение завёрнутого DEK в PostgreSQL ────────────────────────
def _pg_conn():
    """Соединение с PG или None, если недоступно/не настроено."""
    try:
        from db_config import is_pg_configured, get_pg_connection
        if not is_pg_configured():
            return None
        return get_pg_connection()
    except Exception:
        return None


def pg_get_wrapped() -> str:
    """Читает завёрнутый DEK из PG. '' если нет, None если PG недоступен."""
    conn = _pg_conn()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS app_secrets "
                    "(name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit()
        cur.execute("SELECT value FROM app_secrets WHERE name='org_dek'")
        row = cur.fetchone()
        conn.close()
        return row[0] if row else ""
    except Exception as e:
        print(f"[keyvault] чтение ключа из PG: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return None


def pg_put_wrapped(blob: str) -> bool:
    """Сохраняет завёрнутый DEK в PG."""
    conn = _pg_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS app_secrets "
                    "(name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        cur.execute("INSERT INTO app_secrets (name, value) VALUES ('org_dek', %s) "
                    "ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value", (blob,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[keyvault] запись ключа в PG: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return False


# ── Главная точка: получить DEK ──────────────────────────────────
def ensure_dek(prompt_create=None, prompt_enter=None) -> tuple:
    """
    Возвращает (dek_bytes, mode):
      mode == "org"   — общий ключ организации (нужно вызвать security.set_data_key)
      mode == "local" — PostgreSQL не настроен, используем локальный ключ (dek = None)
      mode == "error" — PG настроен, но ключ получить не удалось (нет связи / отмена /
                        неверный пароль). Приложение должно предупредить и не работать
                        с общей базой во избежание рассинхронизации.

    prompt_create() -> str|None : запросить НОВЫЙ пароль установки (первый ПК)
    prompt_enter()  -> str|None : запросить существующий пароль установки (прочие ПК)
    """
    # 1. Локальный кэш (после первой настройки — самый быстрый путь, без сети).
    dek = load_local_dek()
    if dek:
        return dek, "org"

    # 2. Определяем, настроен ли PostgreSQL.
    try:
        from db_config import is_pg_configured
        pg_configured = is_pg_configured()
    except Exception:
        pg_configured = False

    if not pg_configured:
        return None, "local"   # одиночный ПК — общий ключ не нужен

    # 3. PostgreSQL настроен — берём/создаём общий ключ.
    wrapped = pg_get_wrapped()
    if wrapped is None:
        return None, "error"   # PG настроен, но недоступен — без ключа работать нельзя

    if wrapped:
        # Ключ уже есть в PG — нужен пароль установки, чтобы его развернуть.
        if prompt_enter is None:
            return None, "error"
        for _ in range(3):     # три попытки на неверный пароль
            passphrase = prompt_enter()
            if not passphrase:
                return None, "error"
            dek = unwrap_dek(wrapped, passphrase)
            if dek and len(dek) == 32:
                save_local_dek(dek)
                return dek, "org"
        return None, "error"

    # 4. Ключа в PG ещё нет — это первый ПК. Создаём DEK и пароль установки.
    if prompt_create is None:
        return None, "error"
    passphrase = prompt_create()
    if not passphrase:
        return None, "error"
    dek = secrets.token_bytes(32)
    blob = wrap_dek(dek, passphrase)
    if not pg_put_wrapped(blob):
        return None, "error"
    save_local_dek(dek)
    return dek, "org"
