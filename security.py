"""
security.py — Криптографический слой GradeBookAI.

Что здесь живёт:
  • hash_password / verify_password — PBKDF2-HMAC-SHA256 для паролей пользователей
    (хранится только хеш, никогда не открытый пароль).
  • encrypt_value / decrypt_value — симметричное шифрование ПДн «на диске»
    (ФИО, журналы, ключи API) через Fernet (AES-128-CBC + HMAC).
  • get_data_key — 32-байтный ключ шифрования. На диске он НЕ лежит открытым:
    защищён Windows DPAPI (CryptProtectData) и привязан к учётной записи Windows.
  • os_protect / os_unprotect — обёртки DPAPI. Используются и здесь, и в db_config
    для защиты пароля PostgreSQL.

⚠️ 152-ФЗ / приказ ФСТЭК России №21:
  Для боевой эксплуатации пакет `cryptography` ОБЯЗАТЕЛЕН. Раньше при его
  отсутствии модуль молча откатывался на самописный XOR-«шифр» — это давало
  ложное ощущение защиты, а по факту ПДн лежали почти открыто. Теперь так нельзя:
  если `cryptography` не установлен, операции шифрования намеренно падают с
  понятной ошибкой (см. _require_crypto). Приложение проверяет это на старте
  и предупреждает администратора (main.py).
"""

import os
import sys
import base64
import hashlib
import hmac as _hmac
import secrets

try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


def _require_crypto():
    """Падаем громко, если нет cryptography. Никаких слабых фолбэков для ПДн."""
    if not CRYPTO_AVAILABLE:
        raise RuntimeError(
            "Пакет 'cryptography' не установлен — шифрование персональных данных "
            "недоступно. Установите его: pip install cryptography"
        )


# ─────────────────────────────────────────────────────────────
#  Защита секретов на диске через Windows DPAPI
#  DPAPI шифрует данные ключом, производным от учётной записи Windows. Файл,
#  скопированный на другой ПК или другому пользователю, расшифровать нельзя —
#  именно это свойство и нужно для ключа шифрования и пароля БД.
# ─────────────────────────────────────────────────────────────
def _dpapi(data: bytes, unprotect: bool) -> bytes:
    """Вызов CryptProtectData/CryptUnprotectData через ctypes (только Windows)."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    in_blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    func = (ctypes.windll.crypt32.CryptUnprotectData if unprotect
            else ctypes.windll.crypt32.CryptProtectData)
    # сигнатура: (pDataIn, szDescr, pEntropy, reserved, pPrompt, flags, pDataOut)
    ok = func(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def os_protect(data: bytes) -> bytes:
    """Защищает байты для хранения на диске. На Windows — DPAPI, иначе — как есть."""
    if sys.platform == "win32":
        return _dpapi(data, unprotect=False)
    # На не-Windows DPAPI нет. Целевая ОС проекта — Windows; на прочих платформах
    # полагаемся на права доступа к файлу (см. _data_key_path). Это компромисс,
    # задокументированный осознанно, а не молчаливое ослабление.
    return data


def os_unprotect(blob: bytes) -> bytes:
    """Снимает защиту os_protect. Возвращает b'' при неудаче."""
    if sys.platform == "win32":
        try:
            return _dpapi(blob, unprotect=True)
        except Exception:
            return b""
    return blob


# ─────────────────────────────────────────────────────────────
#  Симметричное шифрование значений (Fernet)
# ─────────────────────────────────────────────────────────────
def _encrypt_bytes(plaintext: bytes, key32: bytes) -> bytes:
    _require_crypto()
    return Fernet(base64.urlsafe_b64encode(key32)).encrypt(plaintext)


def _decrypt_bytes(ciphertext: bytes, key32: bytes) -> bytes:
    _require_crypto()
    try:
        return Fernet(base64.urlsafe_b64encode(key32)).decrypt(ciphertext)
    except InvalidToken:
        # Чужой ключ, повреждение или данные старого формата (XOR) — не наши.
        return b""


# ─────────────────────────────────────────────────────────────
#  Ключ шифрования данных «на диске»
#  Ключ хранится в профиле пользователя и защищён DPAPI. При работе нескольких
#  ПК с общим PostgreSQL источником правды является PG (значения kv_store уже
#  зашифрованы), а ключ у каждого ПК свой — поэтому ПДн в общей базе шифруются
#  единообразно: см. примечание в data_store о хранении.
# ─────────────────────────────────────────────────────────────
_ENC_PREFIX = "enc:"
_DATA_KEY_CACHE = None


def _data_key_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~")
    d = os.path.join(base, "GradeBookAI")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "data.key")


def get_data_key() -> bytes:
    """32-байтный ключ шифрования. Читается из защищённого файла или создаётся."""
    global _DATA_KEY_CACHE
    if _DATA_KEY_CACHE is not None:
        return _DATA_KEY_CACHE

    path = _data_key_path()
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                raw = f.read().strip()
            # Основной путь — ключ под DPAPI.
            key = os_unprotect(raw)
            if len(key) == 32:
                _DATA_KEY_CACHE = key
                return key
            # Миграция: старый ключ лежал base64 открытым текстом. Читаем его и
            # тут же перешифровываем под DPAPI, чтобы открытого ключа не осталось.
            try:
                legacy = base64.urlsafe_b64decode(raw)
            except Exception:
                legacy = b""
            if len(legacy) == 32:
                _save_data_key(legacy, path)
                _DATA_KEY_CACHE = legacy
                return legacy
        except Exception:
            pass

    key = secrets.token_bytes(32)
    _save_data_key(key, path)
    _DATA_KEY_CACHE = key
    return key


def _save_data_key(key: bytes, path: str):
    try:
        with open(path, "wb") as f:
            f.write(os_protect(key))
        # Сужаем права доступа к файлу ключа (особенно важно вне Windows/DPAPI).
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception as e:
        print(f"[Security] не удалось сохранить ключ: {e}")


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)


def encrypt_value(plaintext: str) -> str:
    """Шифрует строку. Возвращает 'enc:<base64>'."""
    if plaintext is None:
        plaintext = ""
    ct = _encrypt_bytes(plaintext.encode("utf-8"), get_data_key())
    return _ENC_PREFIX + base64.urlsafe_b64encode(ct).decode("ascii")


def decrypt_value(value: str) -> str:
    """Расшифровывает 'enc:...'. Обычный текст (старые данные) возвращает как есть."""
    if not is_encrypted(value):
        return value
    try:
        ct = base64.urlsafe_b64decode(value[len(_ENC_PREFIX):].encode("ascii"))
        pt = _decrypt_bytes(ct, get_data_key())
        return pt.decode("utf-8")
    except Exception as e:
        print(f"[Security] ошибка расшифровки: {e}")
        return ""


# ─────────────────────────────────────────────────────────────
#  Хеширование паролей пользователей (PBKDF2-HMAC-SHA256)
#  Формат строки: pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>
# ─────────────────────────────────────────────────────────────
_PW_ITERS = 200_000


def hash_password(password: str) -> str:
    """Возвращает безопасный хеш пароля для хранения в БД."""
    if password is None:
        password = ""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PW_ITERS)
    return f"pbkdf2_sha256${_PW_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Проверяет пароль против сохранённого хеша. Защита от timing-атак."""
    if not stored or "$" not in stored:
        return False
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iters)
        return _hmac.compare_digest(dk, expected)
    except Exception:
        return False
