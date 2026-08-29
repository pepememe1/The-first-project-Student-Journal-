# -*- coding: utf-8 -*-
"""totp.py — второй фактор по одноразовому коду (TOTP, RFC 6238).

━━ ПОЧЕМУ КОД ИЗ ПРИЛОЖЕНИЯ, А НЕ PASSKEY ОСНОВНЫМ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Passkey (WebAuthn) у нас есть и он сильнее. Но основным он не годится по устройству
самого колледжа:
  • компьютеры в аудиториях ОБЩИЕ, а passkey привязан к устройству или к учётной
    записи браузера. Заводить его на общей машине — значит оставить там свой ключ;
  • passkey привязан к ДОМЕНУ. При переезде сервера на железо ВСГУТУ домен
    меняется, и все заведённые passkey перестают работать разом;
  • администратору иногда нужно войти с чужого компьютера, и «сначала заведите
    passkey здесь» в этот момент означает «не войдёте».
Код из приложения-аутентификатора работает где угодно, без интернета, без единого
внешнего сервиса и без передачи чего-либо третьей стороне (152-ФЗ — ни одного
нового получателя данных). Passkey остаётся как более сильный вариант для своей
машины; здесь он не заменяется, а дополняется.

━━ ПОЧЕМУ НЕ SMS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SMS — внешний оператор, деньги за каждое сообщение, номер телефона как новые ПДн
и перехват подменой SIM. Ни один из четырёх пунктов нам не нужен.

━━ СВОЯ РЕАЛИЗАЦИЯ ВМЕСТО БИБЛИОТЕКИ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Здесь около сорока строк на hmac и struct из стандартной библиотеки. Алгоритм
описан в RFC 6238 и не менялся с 2011 года; зависимость ради него означала бы
ещё один пакет в поставке, ещё одну строку в SBOM и ещё один повод для вопроса
«а что это за иностранная библиотека в реестре Минцифры».

⚠️ ОКНО ДОПУСКА. Часы на телефоне и на сервере расходятся всегда. Принимаем
соседние шаги (±1 шаг = ±30 с): без запаса половина людей не войдёт с исправным
приложением, с большим запасом окно перебора растёт линейно.

⚠️ ПОВТОР КОДА ЗАПРЕЩЁН. Код живёт 30 секунд, и за это время его можно подсмотреть
через плечо или выдернуть из лога прокси. Поэтому наверху хранится номер
последнего использованного шага, и код, который уже принимали, второй раз не
принимается НИКОГДА — см. `verify_and_consume` в routers/mfa.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
import urllib.parse

#Шаг 30 секунд и шесть цифр — то, что умеют все аутентификаторы без настройки.
#Менять нельзя: несовпадение параметров выглядит как «приложение врёт», и человек
#будет думать, что у него сломан телефон.
STEP_SECONDS = 30
DIGITS = 6
#Сколько соседних шагов принимаем в каждую сторону.
DRIFT_STEPS = 1


def new_secret() -> str:
    """Новый секрет в base32 без набивки — как ждут аутентификаторы.

    20 байт (160 бит) — размер, рекомендованный RFC 4226 для HMAC-SHA1.
    """
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code_for_step(secret_b32: str, step: int) -> str:
    #Набивку возвращаем: base64 её требует, а аутентификаторы её не показывают.
    padded = secret_b32 + "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(padded, casefold=True)
    #SHA-1 здесь — НЕ выбор, а требование RFC 6238 и всех аутентификаторов.
    #Стойкость обеспечивает не хеш, а короткая жизнь кода и ограничитель попыток.
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** DIGITS)).zfill(DIGITS)


def current_step(at: float | None = None) -> int:
    return int((at if at is not None else time.time()) // STEP_SECONDS)


def code(secret_b32: str, at: float | None = None) -> str:
    """Код на текущий момент — нужен тестам и диагностике, не продукту."""
    return _code_for_step(secret_b32, current_step(at))


def verify(secret_b32: str, entered: str, at: float | None = None,
           after_step: int = -1) -> int | None:
    """Проверить код. Возвращает НОМЕР ШАГА при успехе, иначе None.

    Номер шага возвращается не для красоты: вызывающий обязан его сохранить и
    отвергать всё, что не строго больше сохранённого. Без этого подсмотренный
    код действует все свои тридцать секунд у кого угодно.

    `after_step` — последний УЖЕ использованный шаг; шаги не больше него
    отвергаются, даже если код математически верен.
    """
    entered = (entered or "").strip().replace(" ", "").replace("-", "")
    if not entered.isdigit() or len(entered) != DIGITS:
        return None
    now = current_step(at)
    for delta in range(-DRIFT_STEPS, DRIFT_STEPS + 1):
        step = now + delta
        if step <= after_step:
            continue          # код этого шага уже принимали — второй раз нельзя
        #compare_digest: сравнение за постоянное время. Разница в наносекундах на
        #шести цифрах несущественна, но привычка сравнивать секреты обычным `==`
        #однажды переносится туда, где она стоит дорого.
        if hmac.compare_digest(_code_for_step(secret_b32, step), entered):
            return step
    return None


def provisioning_uri(secret_b32: str, login: str, issuer: str = "GradeBookAI") -> str:
    """Строка otpauth:// — её аутентификатор читает с QR-кода или принимает руками.

    ⚠️ `issuer` попадает в название записи на телефоне. Ставим продукт, а не домен:
    при переезде на сервер ВСГУТУ домен изменится, а заведённые записи — нет, и
    человек не должен гадать, к чему относится строка «esstu-gradebook.ru».
    """
    label = urllib.parse.quote(f"{issuer}:{login}", safe="")
    params = urllib.parse.urlencode({
        "secret": secret_b32,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": DIGITS,
        "period": STEP_SECONDS,
    })
    return f"otpauth://totp/{label}?{params}"


# ─────────────────────────────────────────────────────────────────────────────────
# КОДЫ ВОССТАНОВЛЕНИЯ
#
# Без них потерянный или сброшенный телефон означает, что администратор потерял
# доступ ко всему, и «починка» сводится к правке базы руками — то есть к тому,
# от чего мы и уходим. Коды выдаются ОДИН РАЗ при заведении и хранятся ТОЛЬКО
# хешами: база с их открытым текстом была бы вторым паролем в открытом виде.
# ─────────────────────────────────────────────────────────────────────────────────

RECOVERY_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"   # без 0/o/1/l — их путают


def new_recovery_codes(count: int = RECOVERY_COUNT) -> list[str]:
    out = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        out.append(f"{raw[:5]}-{raw[5:]}")     # дефис посередине — их переписывают руками
    return out


def hash_recovery(code_text: str, salt: bytes | None = None) -> str:
    """Хеш кода восстановления: соль + PBKDF2.

    ⚠️ Не «просто sha256»: код короткий, и его пространство перебирается. Итераций
    меньше, чем у пароля (120k против 200k), осознанно — код случайный и длинный,
    а проверять его приходится по всему списку из десяти на каждую попытку входа.
    """
    salt = salt or os.urandom(16)
    normalized = (code_text or "").strip().lower().replace(" ", "")
    dk = hashlib.pbkdf2_hmac("sha256", normalized.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256$120000${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def check_recovery(code_text: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        normalized = (code_text or "").strip().lower().replace(" ", "")
        dk = hashlib.pbkdf2_hmac("sha256", normalized.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(base64.b64encode(dk).decode(), dk_b64)
    except (ValueError, TypeError):
        return False
