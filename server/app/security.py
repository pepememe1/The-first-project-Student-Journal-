"""
security.py (бэкенд) — Хеширование паролей и JWT-токены.

Формат хеша СОВПАДАЕТ с десктопом (security.hash_password):
    pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>
Поэтому хеши, созданные в проге, проверяются на сервере и наоборот — это важно
для offline-first: пользователей заводит админ в десктопе, они синхронизируются
на сервер уже хешами, и вход через API/сайт работает с теми же паролями.
"""
import hashlib
import hmac
import secrets
import time

from jose import jwt, JWTError

from .config import JWT_SECRET, JWT_ALG, JWT_TTL_MIN

_PW_ITERS = 200_000


def hash_password(password: str) -> str:
    if password is None:
        password = ""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PW_ITERS)
    return f"pbkdf2_sha256${_PW_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
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
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def create_token(subject: str, role: str) -> str:
    """Подписанный JWT с логином (sub) и ролью; истекает через JWT_TTL_MIN минут."""
    now = int(time.time())
    payload = {"sub": subject, "role": role, "iat": now, "exp": now + JWT_TTL_MIN * 60}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    """Возвращает payload или None, если токен невалиден/просрочен."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError:
        return None
