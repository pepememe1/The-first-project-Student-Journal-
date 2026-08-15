"""
security.py — Криптографический слой GradeBookAI.

Что здесь живёт:
  • hash_password / verify_password — PBKDF2-HMAC-SHA256 для паролей пользователей
    (хранится только хеш, никогда не открытый пароль).
  • encrypt_value / decrypt_value — симметричное шифрование ПДн «на диске»
    (ФИО, журналы) через Fernet (AES-128-CBC + HMAC).
  • get_data_key — 32-байтный ключ шифрования. На диске он НЕ лежит открытым:
    защищён Windows DPAPI (CryptProtectData) и привязан к учётной записи Windows.
  • os_protect / os_unprotect — обёртки DPAPI для защиты секретов «на диске»
    (например, ключа шифрования данных).

⚠️ 152-ФЗ / приказ ФСТЭК России №21:
  Для боевой эксплуатации пакет `cryptography` ОБЯЗАТЕЛЕН. Раньше при его
  отсутствии модуль молча откатывался на самописный XOR-«шифр» — это давало
  ложное ощущение защиты, а по факту ПДн лежали почти открыто. Теперь так нельзя:
  если `cryptography` не установлен, операции шифрования намеренно падают с
  понятной ошибкой (см. _require_crypto). Приложение проверяет это на старте
  и предупреждает администратора (main.py).
"""

import os
import log
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


#Защита секретов на диске через Windows DPAPI
#DPAPI шифрует данные ключом, производным от учётной записи Windows. Файл,
#скопированный на другой ПК или другому пользователю, расшифровать нельзя —
#именно это свойство и нужно для ключа шифрования данных.
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
    #сигнатура: (pDataIn, szDescr, pEntropy, reserved, pPrompt, flags, pDataOut)
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
    #На не-Windows DPAPI нет. Целевая ОС проекта — Windows; на прочих платформах
    #полагаемся на права доступа к файлу (см. _data_key_path). Это компромисс,
    #задокументированный осознанно, а не молчаливое ослабление.
    return data


def os_unprotect(blob: bytes) -> bytes:
    """Снимает защиту os_protect. Возвращает b'' при неудаче."""
    if sys.platform == "win32":
        try:
            return _dpapi(blob, unprotect=True)
        except Exception:
            return b""
    return blob


#Симметричное шифрование значений (Fernet)
def _encrypt_bytes(plaintext: bytes, key32: bytes) -> bytes:
    _require_crypto()
    return Fernet(base64.urlsafe_b64encode(key32)).encrypt(plaintext)


def _decrypt_bytes(ciphertext: bytes, key32: bytes) -> bytes:
    _require_crypto()
    try:
        return Fernet(base64.urlsafe_b64encode(key32)).decrypt(ciphertext)
    except InvalidToken:
        #Чужой ключ, повреждение или данные старого формата (XOR) — не наши.
        return b""


#Ключ шифрования данных «на диске»
#Ключ хранится рядом с базой (см. app_paths) и защищён DPAPI — у каждого ПК
#он свой. ПДн в локальном SQLite шифруются этим ключом; обмен с общей базой
#колледжа идёт через API-сервер по TLS (см. data_store, sync_client).
_ENC_PREFIX = "enc:"
_DATA_KEY_CACHE = None


def _data_key_path() -> str:
    #Ключ держим там же, где базу (см. app_paths): рядом с .exe (портативно) или
    #в профиле (dev). Раньше ключ уезжал в %APPDATA% (Roaming), а база — в
    #%LOCALAPPDATA% (Local): данные растекались по двум каталогам. Теперь — вместе.
    import app_paths
    return app_paths.data_file("data.key")


def _legacy_data_key_path() -> str:
    """Старое расположение ключа: %APPDATA% (Roaming)/GradeBookAI/data.key.
    Нужно для бесшовной миграции — ключ переехал в общую папку данных (app_paths).
    Без переноса существующая база, зашифрованная старым ключом, стала бы нечитаемой."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~")
    return os.path.join(base, "GradeBookAI", "data.key")


def get_data_key() -> bytes:
    """32-байтный ключ шифрования. Читается из защищённого файла или создаётся."""
    global _DATA_KEY_CACHE
    if _DATA_KEY_CACHE is not None:
        return _DATA_KEY_CACHE

    _log = log.get("security")
    path = _data_key_path()
    #🔥 Существовал ли файл ключа. Отличать «ключа не было» (первый запуск, штатно) от
    #«ключ был, но прочитать не вышло» ОБЯЗАТЕЛЬНО: во втором случае ниже создаётся НОВЫЙ
    #ключ, и все ранее зашифрованные ПДн превращаются в нечитаемый мусор НАВСЕГДА.
    #Раньше обе ветки молчали одинаково (`except Exception: pass`), и человек видел лишь
    #«программа открылась, а данных нет» — без единой строки в логе, по которой это можно
    #было бы понять. Ключ мы всё равно создаём (отказаться запускаться из-за битого файла
    #у того, кто ещё ничего не шифровал, — хуже), но след теперь остаётся.
    had_key_file = False
    if os.path.exists(path):
        had_key_file = True
        try:
            with open(path, "rb") as f:
                raw = f.read().strip()
            #Основной путь — ключ под DPAPI.
            key = os_unprotect(raw)
            if len(key) == 32:
                _DATA_KEY_CACHE = key
                return key
            #Миграция: старый ключ лежал base64 открытым текстом. Читаем его и
            #тут же перешифровываем под DPAPI, чтобы открытого ключа не осталось.
            try:
                legacy = base64.urlsafe_b64decode(raw)
            except Exception as e:                  # noqa: BLE001
                _log.warning("[Security] ключ %s не разбирается как base64 (%s) — "
                             "проверю запасное расположение", path, e)
                legacy = b""
            if len(legacy) == 32:
                _save_data_key(legacy, path)
                _DATA_KEY_CACHE = legacy
                return legacy
        except Exception as e:                      # noqa: BLE001
            _log.error("[Security] файл ключа %s не прочитался: %s", path, e)

    #Миграция со старого расположения (ключ переехал из Roaming в общую папку).
    #Переносим один раз; старый файл не трогаем — на случай отката.
    old = _legacy_data_key_path()
    if old != path and os.path.exists(old):
        had_key_file = True
        try:
            with open(old, "rb") as f:
                raw = f.read().strip()
            key = os_unprotect(raw)
            if len(key) != 32:
                try:
                    key = base64.urlsafe_b64decode(raw)
                except Exception as e:              # noqa: BLE001
                    _log.warning("[Security] прежний ключ %s не разбирается: %s", old, e)
                    key = b""
            if len(key) == 32:
                _save_data_key(key, path)
                _DATA_KEY_CACHE = key
                return key
        except Exception as e:                      # noqa: BLE001
            _log.error("[Security] прежний файл ключа %s не прочитался: %s", old, e)

    if had_key_file:
        #Самое дорогое сообщение в этом файле. Ключ БЫЛ, но не подошёл — значит либо файл
        #повреждён, либо DPAPI отказал (типично: профиль перенесли на другую машину или
        #под другого пользователя Windows — DPAPI привязан к учётной записи). Данные,
        #зашифрованные прежним ключом, этим запуском уже не расшифруются.
        _log.error("[Security] файл ключа найден, но НЕ ПОДОШЁЛ — создаю новый. "
                   "Ранее зашифрованные данные этим ключом больше не прочитаются. "
                   "Обычная причина: копию программы перенесли на другую машину или под "
                   "другого пользователя Windows (защита DPAPI привязана к учётной записи). "
                   "Если данные важны — восстановите их из резервной копии вместе со "
                   "старым файлом ключа: %s", path)
    else:
        _log.info("[Security] файла ключа нет — первый запуск, создаю новый: %s", path)

    key = secrets.token_bytes(32)
    _save_data_key(key, path)
    _DATA_KEY_CACHE = key
    return key


def _save_data_key(key: bytes, path: str):
    try:
        with open(path, "wb") as f:
            f.write(os_protect(key))
        #Сужаем права доступа к файлу ключа (особенно важно вне Windows/DPAPI).
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception as e:
        log.get("security").warning(f"[Security] не удалось сохранить ключ: {e}")


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
        log.get("security").warning(f"[Security] ошибка расшифровки: {e}")
        return ""


#Хеширование паролей — ДВУХЭТАПНЫЙ «гибрид» (152-ФЗ + практичная стойкость)
#
#Формат: hybrid_sha512_gost512$<sha_iters>-<gost_iters>$<salt_hex>$<hash_hex>
#
#Согласованная схема:
#  ЭТАП 1 — PBKDF2-HMAC-SHA512 (быстрый, общепринятый): несёт ОСНОВНУЮ стойкость.
#  ЭТАП 2 — итог обязательно проходит через российский ГОСТ Р 34.11-2012 «Стрибог-512»
#           (PBKDF2 по Р 50.1.111-2016): даёт «отечественный сертифицированный
#           прогон». На бою ГОСТ считает сертифицированное СКЗИ (ViPNet CSP /
#           OpenSSL GOST-engine) — только тогда это юридически значимо.
#
#ГОСТ-бэкенд выбирается АВТОматически (без ручного флага):
#  • бой (Linux + OpenSSL GOST-engine/ViPNet): hashlib.pbkdf2_hmac('streebog512') — C-скорость;
#  • dev (Windows): gostcrypto (pure-Python, Р 50.1.111-2016) — медленно (~2.7 мс/итер),
#    поэтому итераций ГОСТ берём МАЛО. Это не ослабляет защиту: стойкость несёт ЭТАП 1,
#    а ГОСТ-слой — нормативная обёртка, а не источник work-factor.
#⚠️ Совместимость dev↔бой держится на том, что ОБА бэкенда дают СТАНДАРТНЫЙ
#   PBKDF2-HMAC-Стрибог512 — закреплено тестом на контрольном векторе Р 50.1.111-2016
#   (tests/test_password_hash.py). Перед боем проверить на реальном GOST-engine сервера.
#
#Обратная совместимость: старые одноэтапные `pbkdf2_sha256$...` (200k/600k) ещё
#проверяются (verify диспетчеризует по тегу) — апгрейд без сброса паролей.
_SHA_ITERS = 200_000
_HYBRID_TAG = "hybrid_sha512_gost512"
#Имена Стрибог-512 в OpenSSL через GOST-engine (бой). На разных сборках различаются.
_OPENSSL_GOST_NAMES = ("streebog512", "gost2012_512", "md_gost12_512")
_LEGACY_SUPPORTED = ("sha256", "sha512")   #старые одноэтапные хеши, которые ещё проверяем


def _openssl_gost_name():
    """Имя доступного ГОСТ-дайджеста в OpenSSL (движок/провайдер) или None.

    ВАЖНО: проверяем через hashlib.new(), а НЕ по algorithms_available. На OpenSSL 3.0
    дайджесты gost-провайдера доступны для new()/pbkdf2_hmac, но в algorithms_available
    НЕ попадают (там только дефолт-провайдер) — иначе gost-engine «не виден» и хеш идёт
    медленным pure-Python'ом. Результат кэшируем (бэкенд не меняется в процессе)."""
    global _gost_name_cache
    if _gost_name_cache is not False:
        return _gost_name_cache
    _gost_name_cache = None
    for n in _OPENSSL_GOST_NAMES:
        try:
            hashlib.new(n)
            _gost_name_cache = n
            break
        except Exception:
            continue
    return _gost_name_cache


_gost_name_cache = False   #False = ещё не определяли; None/строка — результат детекции


def _gost_pbkdf2(password: bytes, salt: bytes, iters: int) -> bytes:
    """PBKDF2-HMAC-Стрибог512 (Р 50.1.111-2016), 64 байта. Бэкенд авто:
    OpenSSL GOST-engine (быстро, бой) → gostcrypto (pure-Python, dev)."""
    name = _openssl_gost_name()
    if name:
        return hashlib.pbkdf2_hmac(name, password, salt, iters, dklen=64)
    try:
        from gostcrypto import gostpbkdf
    except ImportError as e:
        raise RuntimeError(
            "Нет ГОСТ-бэкенда для хеша пароля: на бою нужен OpenSSL GOST-engine "
            "(ViPNet/gost-engine), на dev — пакет gostcrypto (pip install gostcrypto).") from e
    return gostpbkdf.new(password, salt=salt, counter=iters).derive(64)


def _gost_iters() -> int:
    """Число итераций ГОСТ при СОЗДАНИИ хеша. Переопределяется переменной
    GRADEBOOK_GOST_ITERS (тесты/нагрузка). По умолчанию: 2000 на быстром OpenSSL-
    бэкенде (бой), мало на медленном pure-Python (dev) — чтобы вход не висел."""
    env = os.environ.get("GRADEBOOK_GOST_ITERS", "").strip()
    if env.isdigit():
        return max(1, int(env))
    return 2000 if _openssl_gost_name() else 2


def hash_password(password: str) -> str:
    """Двухэтапный хеш: PBKDF2-SHA512 (стойкость) → PBKDF2-Стрибог512 (ГОСТ)."""
    if password is None:
        password = ""
    salt = secrets.token_bytes(16)
    gi = _gost_iters()
    inter = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, _SHA_ITERS)
    final = _gost_pbkdf2(inter, salt, gi)
    return f"{_HYBRID_TAG}${_SHA_ITERS}-{gi}${salt.hex()}${final.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Проверка пароля: гибрид (новый) или старые pbkdf2_sha256/sha512. Параметры
    (итерации, соль) берутся ИЗ хеша, поэтому хеш самодостаточен. Timing-safe."""
    if not stored or "$" not in stored:
        return False
    try:
        tag, iters_field, salt_hex, hash_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        pw = (password or "").encode("utf-8")
        if tag == _HYBRID_TAG:
            sha_iters, gost_iters = (int(x) for x in iters_field.split("-"))
            inter = hashlib.pbkdf2_hmac("sha512", pw, salt, sha_iters)
            dk = _gost_pbkdf2(inter, salt, gost_iters)
        elif tag.startswith("pbkdf2_"):
            hash_name = tag.split("_", 1)[1]
            if hash_name not in _LEGACY_SUPPORTED:
                return False
            dk = hashlib.pbkdf2_hmac(hash_name, pw, salt, int(iters_field))
        else:
            return False
        return _hmac.compare_digest(dk, expected)
    except Exception:
        return False
