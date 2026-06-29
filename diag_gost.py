"""
diag_gost.py — Диагностика ГОСТ-бэкенда хеширования паролей.

Запуск (из корня репозитория):  python diag_gost.py

Зачем. Хеш пароля у нас двухэтапный (PBKDF2-SHA512 → PBKDF2-Стрибог512). ГОСТ-этап
считается одним из двух бэкендов, и ВАЖНО знать, какой активен на конкретной машине:
  • OpenSSL GOST-engine (на бою: Linux + gost-engine/ViPNet-интеграция в OpenSSL) —
    C-скорость, и ГОСТ-итерации можно поднимать до нормативных (2000) без потери темпа;
  • gostcrypto (pure-Python, fallback для dev) — медленный (~2.7 мс/итер), поэтому
    ГОСТ-итераций берём мало (стойкость несёт SHA-512-этап).

⚠️ Частое заблуждение: «поставил ViPNet CSP → Python считает ГОСТ быстро». НЕТ:
ViPNet CSP встраивается в Windows CryptoAPI, а hashlib Python использует СВОЙ
OpenSSL. Чтобы hashlib увидел Стрибог, нужен именно OpenSSL GOST-engine
(на Linux — пакет gost-engine + строки engine в openssl.cnf). Этот скрипт честно
показывает, что доступно.
"""
import sys
import time
import hashlib

import _bootstrap  # noqa: F401  (раскладка путей ui/sync/data — до ленивого import security)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    print("=== Диагностика ГОСТ-бэкенда (хеш пароля) ===\n")

    import ssl
    print(f"OpenSSL у Python:        {ssl.OPENSSL_VERSION}")
    gost_algos = [a for a in sorted(hashlib.algorithms_available)
                  if any(k in a.lower() for k in ("gost", "streebog", "3411"))]
    print(f"ГОСТ в hashlib:          {gost_algos or 'НЕТ (OpenSSL без gost-engine)'}")

    try:
        import security
    except Exception as e:
        print(f"\n[!] Не удалось импортировать security.py: {e}")
        return 1

    name = security._openssl_gost_name()
    if name:
        backend = f"OpenSSL '{name}' (C-скорость, бой)"
    else:
        try:
            import gostcrypto  # noqa: F401
            backend = "gostcrypto (pure-Python, dev/fallback)"
        except ImportError:
            print("\n[✗] ГОСТ-бэкенда НЕТ: ни OpenSSL gost-engine, ни gostcrypto.")
            print("    Поставь gostcrypto (pip install gostcrypto) или OpenSSL gost-engine.")
            return 2
    print(f"Активный ГОСТ-бэкенд:     {backend}")
    print(f"ГОСТ-итераций по умолч.:  {security._gost_iters()}  "
          f"(переопределяется GRADEBOOK_GOST_ITERS)")

    # Контрольный вектор Р 50.1.111-2016 (c=1) — стандартность ГОСТ-этапа
    kat = security._gost_pbkdf2(b"password", b"salt", 1).hex()
    kat_ok = kat == ("64770af7f748c3b1c9ac831dbcfd85c26111b30a8a657ddc3056b80ca73e040d"
                     "2854fd36811f6d825cc4ab66ec0a68a490a9e5cf5156b3a2b7eecddbf9a16b47")
    print(f"\nКонтрольный вектор Р 50.1.111-2016 (c=1): {'СОВПАЛ ✅' if kat_ok else 'НЕ совпал ❌'}")
    if not kat_ok:
        print("    ⚠️ Бэкенд даёт НЕстандартный ГОСТ — хеши не будут совместимы между dev/бой!")

    # Хеш + проверка + скорость
    pw = "Stud_Vsgutu_2026_Secure"
    t = time.perf_counter()
    h = security.hash_password(pw)
    dt = (time.perf_counter() - t) * 1000
    ok = security.verify_password(pw, h) and not security.verify_password("wrong", h)
    print(f"\nhash_password:           {dt:.0f} мс   тег={h.split('$')[0]}  параметры={h.split('$')[1]}")
    print(f"verify_password:         {'OK ✅' if ok else 'ОШИБКА ❌'}")

    print("\n=== ИТОГ ===")
    if name:
        print("✅ Активен быстрый OpenSSL GOST-engine — на бою можно поднимать "
              "GRADEBOOK_GOST_ITERS до нормативных 2000 без потери скорости.")
    else:
        print("ℹ️  Активен gostcrypto (pure-Python). Это норм для dev. Для боевого "
              "сервера поставь OpenSSL gost-engine — бэкенд подхватит его сам, ГОСТ "
              "станет C-быстрым. ViPNet CSP сам по себе hashlib НЕ ускоряет (он для "
              "канала ГОСТ-TLS — см. server/DEPLOY.md).")
    return 0 if (kat_ok and ok) else 3


if __name__ == "__main__":
    sys.exit(main())
