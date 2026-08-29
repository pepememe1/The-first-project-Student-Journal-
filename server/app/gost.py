"""
gost.py — Криптографический слой на ГОСТ для защиты ПДн при хранении (152-ФЗ).

ЗАЧЕМ. 152-ФЗ/ФСТЭК/ФСБ требуют не «шифрование вообще», а СЕРТИФИЦИРОВАННОЕ СКЗИ с
алгоритмами ГОСТ (34.12-2018 «Кузнечик»/«Магма», Стрибог 34.11-2018). Этот модуль —
единая точка шифрования/хеширования, спроектированная «под СКЗИ»: на боевом Linux-ПК
ВСГУТУ с установленным ViPNet CSP / OpenSSL GOST-engine он АВТОМАТИЧЕСКИ использует
сертифицированный движок; на dev — чистый Python-`gostcrypto` (тот же алгоритм ГОСТ,
но НЕ сертифицированный — помечаем это в backend_info).

ЧТО ДАёт:
  • encrypt/decrypt — блочный шифр «Кузнечик» (ГОСТ 34.12-2018), режим CTR + имитовставка
    HMAC-Стрибог (encrypt-then-MAC) → конфиденциальность + целостность;
  • blind_index — HMAC-Стрибог(ключ_индекса, значение): детерминированный «слепой индекс»
    для поиска по зашифрованному полю (напр. логин=email) БЕЗ хранения открытого значения;
  • backend_info — какой движок используется и СЕРТИФИЦИРОВАН ли он (для журнала/аудита).

КЛЮЧИ (в .env, НЕ в git, НЕ в БД; на бою — в хранилище СКЗИ/на токене Рутокен/JaCarta):
  GRADEBOOK_DATA_KEY   — 64 hex-символа (32 байта) для «Кузнечик»;
  GRADEBOOK_INDEX_KEY  — ключ для слепого индекса (HMAC-Стрибог).
Нет ключей → шифрование выключено (encrypt возвращает значение как есть с пометкой),
чтобы прод не падал; включается заданием ключей при развёртывании с СКЗИ.
"""
import os
import base64
import hmac
import hashlib

_TAG = "gost1"          #версия формата шифртекста (на будущее — смена схемы без потери данных)


def _openssl_gost() -> bool:
    """Доступен ли ГОСТ через OpenSSL-движок (его ставит ViPNet/gost-engine на бою)."""
    try:
        avail = hashlib.algorithms_available
        return any(n in avail for n in ("streebog512", "md_gost12_512", "gost2012_512"))
    except Exception:
        return False


def backend_info() -> dict:
    """Что за крипто-движок и СЕРТИФИЦИРОВАН ли он. Для аудита/журнала учёта СКЗИ."""
    vipnet = bool(os.environ.get("GRADEBOOK_VIPNET"))      #флаг «крутимся с ViPNet CSP»
    if vipnet or _openssl_gost():
        return {"backend": "vipnet/openssl-gost" if vipnet else "openssl-gost",
                "algorithm": "ГОСТ 34.12-2018 (Кузнечик) + Стрибог",
                "certified": bool(vipnet)}                 #сертифицирован только явный ViPNet-контур
    return {"backend": "gostcrypto (pure-python)",
            "algorithm": "ГОСТ 34.12-2018 (Кузнечик) + Стрибог",
            "certified": False}


def _data_key() -> bytes | None:
    from . import secrets_source
    k = secrets_source.get("GRADEBOOK_DATA_KEY")
    if len(k) == 64:
        try:
            return bytes.fromhex(k)
        except ValueError:
            return None
    return None


def _index_key() -> bytes:
    from . import secrets_source
    k = secrets_source.get("GRADEBOOK_INDEX_KEY")
    return bytes.fromhex(k) if len(k) in (32, 64) and _is_hex(k) else (k.encode() or b"gb-index")


def _is_hex(s: str) -> bool:
    try:
        bytes.fromhex(s)
        return True
    except ValueError:
        return False


def enabled() -> bool:
    """Включено ли шифрование ПДн (задан ли ключ данных)."""
    return _data_key() is not None


def _streebog256(data: bytes) -> bytes:
    """Хеш Стрибог-256: сертифицированный OpenSSL-движок (ViPNet) → gostcrypto (dev)."""
    if "streebog256" in hashlib.algorithms_available:
        h = hashlib.new("streebog256")
        h.update(data)
        return h.digest()
    from gostcrypto import gosthash
    h = gosthash.new("streebog256")
    h.update(data)
    return h.digest()


def blind_index(value: str) -> str:
    """Детерминированный «слепой индекс» значения (для поиска по зашифрованному полю).
    HMAC-Стрибог(index_key, value). Открытое значение по индексу не восстановить."""
    v = (value or "").strip().lower().encode("utf-8")
    key = _index_key()
    #HMAC поверх Стрибог-256 (совместимо и с OpenSSL-движком, и с gostcrypto).
    return hmac.new(key, v, lambda: _StreebogHasher()).hexdigest()


class _StreebogHasher:
    """Обёртка Стрибог-256 под интерфейс hashlib для hmac.new (update/digest/copy)."""
    def __init__(self, data: bytes = b""):
        self._buf = bytearray(data)
    def update(self, d: bytes):
        self._buf += d
    def digest(self) -> bytes:
        return _streebog256(bytes(self._buf))
    def hexdigest(self) -> str:
        return self.digest().hex()
    def copy(self):
        return _StreebogHasher(bytes(self._buf))
    digest_size = 32
    block_size = 64


def _kuznechik_ctr(key: bytes, iv: bytes, data: bytes) -> bytes:
    """«Кузнечик» (ГОСТ 34.12-2018) в режиме гаммирования (CTR). gostcrypto — чистый
    Python; на бою тот же алгоритм исполняет сертифицированный движок ViPNet."""
    from gostcrypto import gostcipher
    cipher = gostcipher.new("kuznechik", bytearray(key), gostcipher.MODE_CTR,
                            init_vect=bytearray(iv))
    return bytes(cipher.encrypt(bytearray(data)))


def encrypt(plaintext: str) -> str:
    """Шифрует строку: «Кузнечик»-CTR + имитовставка HMAC-Стрибог (encrypt-then-MAC).
    Формат: gost1$<base64(iv||ct||mac)>. Нет ключа → возвращает исходную строку (шифр
    выключен) — чтобы прод не падал до развёртывания СКЗИ; см. enabled()."""
    if plaintext is None:
        plaintext = ""
    key = _data_key()
    if key is None:
        return plaintext
    pt = plaintext.encode("utf-8")
    iv = os.urandom(8)                                     #CTR init для «Кузнечик» — 8 байт
    ct = _kuznechik_ctr(key, iv, pt)
    mac = hmac.new(_index_key(), iv + ct, lambda: _StreebogHasher()).digest()[:16]
    blob = base64.b64encode(iv + ct + mac).decode("ascii")
    return f"{_TAG}${blob}"


def decrypt(token: str) -> str:
    """Расшифровывает то, что зашифровал encrypt. Если строка не в нашем формате
    (старые открытые значения) — возвращает как есть (плавная миграция)."""
    if not token or not token.startswith(_TAG + "$"):
        return token or ""
    key = _data_key()
    if key is None:
        return token
    try:
        raw = base64.b64decode(token[len(_TAG) + 1:])
        iv, rest = raw[:8], raw[8:]
        ct, mac = rest[:-16], rest[-16:]
        exp = hmac.new(_index_key(), iv + ct, lambda: _StreebogHasher()).digest()[:16]
        if not hmac.compare_digest(mac, exp):
            raise ValueError("имитовставка не совпала (данные повреждены/подменены)")
        return bytes(_kuznechik_ctr(key, iv, ct)).decode("utf-8")
    except Exception as e:
        print(f"[gost] расшифровка не удалась: {e}")
        return ""
