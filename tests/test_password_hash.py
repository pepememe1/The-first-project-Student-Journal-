"""
test_password_hash.py — Двухэтапный хеш пароля (PBKDF2-SHA512 → PBKDF2-Стрибог512).

Ключевое:
  • KAT (контрольный вектор Р 50.1.111-2016) — гарантирует, что ГОСТ-этап считает
    СТАНДАРТНЫЙ PBKDF2-HMAC-Стрибог512. Это и есть основа совместимости dev↔бой:
    хеш, созданный на dev (gostcrypto), проверится на бою (OpenSSL GOST-engine).
  • Гибридный формат создаётся и проверяется; старые pbkdf2_sha256 ещё проверяются.
"""
import os
import hashlib
import secrets

from data import security

#ГОСТ-итераций по умолчанию на dev и так мало (2), но зафиксируем для скорости/детерминизма.
os.environ.setdefault("GRADEBOOK_GOST_ITERS", "2")


def test_gost_pbkdf2_known_answer():
    """Контрольный вектор TC26 / Р 50.1.111-2016: P='password', S='salt', c=1, dkLen=64.
    Если он совпал — ГОСТ-этап стандартный, и бэкенды (gostcrypto/OpenSSL) взаимозаменяемы."""
    got = security._gost_pbkdf2(b"password", b"salt", 1).hex()
    assert got == ("64770af7f748c3b1c9ac831dbcfd85c26111b30a8a657ddc3056b80ca73e040d"
                   "2854fd36811f6d825cc4ab66ec0a68a490a9e5cf5156b3a2b7eecddbf9a16b47")


def test_new_hash_is_hybrid():
    h = security.hash_password("Pass12345")
    assert h.startswith("hybrid_sha512_gost512$200000-"), h
    assert security.verify_password("Pass12345", h)
    assert not security.verify_password("wrong", h)


def test_gost_iters_from_env_in_hash():
    """Число ГОСТ-итераций берётся из окружения и записывается в сам хеш."""
    os.environ["GRADEBOOK_GOST_ITERS"] = "3"
    try:
        h = security.hash_password("X")
        assert h.startswith("hybrid_sha512_gost512$200000-3$"), h
        assert security.verify_password("X", h)
    finally:
        os.environ["GRADEBOOK_GOST_ITERS"] = "2"


def test_legacy_sha256_still_verifies():
    """Старые одноэтапные pbkdf2_sha256 (и 200k, и 600k) обязаны проверяться —
    иначе апгрейд разлогинил бы существующих пользователей."""
    for iters in (200_000, 600_000):
        salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac("sha256", b"Pass12345", salt, iters)
        old = f"pbkdf2_sha256${iters}${salt.hex()}${dk.hex()}"
        assert security.verify_password("Pass12345", old), iters
        assert not security.verify_password("nope", old)


def test_malformed_or_unsupported_rejected():
    assert not security.verify_password("x", "")
    assert not security.verify_password("x", "garbage")
    assert not security.verify_password("x", "pbkdf2_md5$1$aa$bb")     # алгоритм не из белого списка
    assert not security.verify_password("x", "plain$1$aa$bb")          # неизвестный тег
