"""
media_cache.py — кэш картинок мессенджера в %TEMP%: гифки, баннеры, аватарки (17.10.2026).

Просьба Ярослава: «кэширование в temp как у Discord — гифки, которые ты видел в пикере
или которые кто-то прислал снова, уже лежат у тебя какой-то срок; так же аватарки и
баннеры; посмотри, что кэшируют Discord и Telegram».

Почему кэш понадобился вообще. Окно программы — WebView2 в ПРИВАТНОМ режиме
(`webview2_app.py`, 152-ФЗ: на общем компьютере аудитории профиль браузера не должен
переживать сеанс). Значит его собственный HTTP-кэш живёт до закрытия окна, и после
КАЖДОГО запуска все гифки и баннеры качались с CDN заново.

Что делают другие (сверено 17.10.2026):
| Discord   | кэш Chromium на диске: аватарки, эмодзи, вложения, превью, гифки; открытым видом; |
|           | срок — по заголовкам CDN, объём — сам Chromium                                    |
| Telegram  | фото, гифки, стикеры, аватарки, документы; ЗАШИФРОВАНО ключом приложения; общий  |
|           | потолок (по умолчанию 2 ГБ) и «хранить медиа N дней» с последнего обращения       |
| мы        | гифки и баннеры Klipy, аватарки людей и бесед; зашифровано ключом устройства;     |
|           | срок с последнего показа: гифки 14 дней, аватарки 30; потолок 300 МБ              |

Сообщения, список чатов и файлы-вложения сюда НЕ попадают намеренно: мессенджер — онлайн
по решению §5.4 (тексты переписки на диске не лежат), а вложения — документы людей, и
на бою они сейчас выключены. Картинки же восстановимы: пропал файл — скачаем заново.

Правила (те же, что у `temp_cache.py`):
- ПОД КЛЮЧОМ УСТРОЙСТВА. Аватарка — фотография человека, то есть ПДн; открытым видом в
  каталоге, общем для всех программ пользователя, ей не место. AES-GCM, а не Fernet:
  гифка весит мегабайты, а Fernet раздувает содержимое base64 на треть.
- ИМЯ ФАЙЛА — HMAC адреса. По имени нельзя ни узнать адрес, ни проверить догадку «эту
  гифку он смотрел» без ключа. Связанные данные AES-GCM — само имя: файл, переложенный
  под другое имя, не расшифруется (подмена одной картинки другой не пройдёт).
- СРОК — С ПОСЛЕДНЕГО ПОКАЗА (время изменения файла обновляется при попадании), как
  «хранить медиа» у Telegram; сверх потолка уходят самые давно не нужные.
- СМЕНА ЧЕЛОВЕКА ЗА КОМПЬЮТЕРОМ = КЭШ ПРЕЖНЕГО УХОДИТ (`purge`, зовёт
  `local_api._purge_previous_user` вместе со сменой владельца локальной базы).
- Кэш не обязан работать: любой сбой диска или шифра — это промах, а не ошибка для
  человека. Сеть сюда не ходит: загрузчик передаёт вызывающий (`local_api`).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import tempfile
import threading
import time

import log

_LOG = log.get("media_cache")

#Номер формата файла: поменял раскладку — подними, старые файлы станут «чужими».
_FORMAT = b"gbmc1"
_NONCE = 12

#Сколько дней хранить картинку после последнего показа.
TTL_DAYS = {"gif": 14, "avatar": 30}
#Предел одной картинки: гифка с CDN — до 8 МБ, обрезанная аватарка 256×256 — меньше 1 МБ.
MAX_ITEM_BYTES = {"gif": 8 * 1024 * 1024, "avatar": 1024 * 1024}
#Общий потолок. Telegram по умолчанию держит 2 ГБ, но у нас кэш на общем компьютере
#аудитории, а не на своём телефоне, — берём скромнее.
MAX_TOTAL_BYTES = 300 * 1024 * 1024
#Убираем лишнее каждые столько записей — плюс один раз на старте программы.
_SWEEP_EVERY = 64

ALLOWED_MIME = frozenset({"image/gif", "image/webp", "image/png", "image/jpeg", "image/avif"})

_FILE_RE = re.compile(r"^(gif|avatar)-[0-9a-f]{40}\.bin$")

_key_cache: bytes | None = None
_key_lock = threading.Lock()
_writes = 0
_inflight: dict[str, threading.Lock] = {}
_inflight_lock = threading.Lock()


def cache_dir() -> str:
    """%TEMP%\\GradeBookAI\\media (на других ОС — системный временный каталог)."""
    return os.path.join(tempfile.gettempdir(), "GradeBookAI", "media")


def _key() -> bytes:
    """Ключ кэша: производный от ключа данных программы, со своим назначением. Считаем
    один раз: ключ устройства за жизнь процесса не меняется, а снимать DPAPI на каждую
    картинку значило бы платить за это в каждой строке списка чатов."""
    global _key_cache
    if _key_cache is None:
        with _key_lock:
            if _key_cache is None:
                from data import security
                _key_cache = hmac.new(security.get_data_key(), b"gradebook-media-cache:v1",
                                      hashlib.sha256).digest()
    return _key_cache


def _name(kind: str, url: str) -> str:
    if kind not in TTL_DAYS:
        raise ValueError(f"неизвестный вид картинки: {kind!r}")
    digest = hmac.new(_key(), f"{kind}\n{url}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{kind}-{digest[:40]}.bin"


def _aes():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(_key())


def _encrypt(name: str, mime: str, body: bytes) -> bytes:
    nonce = os.urandom(_NONCE)
    plain = mime.encode("ascii") + b"\n" + body
    return _FORMAT + nonce + _aes().encrypt(nonce, plain, name.encode("ascii"))


def _decrypt(name: str, blob: bytes):
    if not blob.startswith(_FORMAT):
        return None
    rest = blob[len(_FORMAT):]
    nonce, sealed = rest[:_NONCE], rest[_NONCE:]
    try:
        plain = _aes().decrypt(nonce, sealed, name.encode("ascii"))
    except Exception:      # noqa: BLE001 — чужой ключ, подмена, обрыв: просто промах
        return None
    mime, _, body = plain.partition(b"\n")
    mime_s = mime.decode("ascii", "replace")
    if mime_s not in ALLOWED_MIME or not body:
        return None
    return mime_s, body


def get(kind: str, url: str):
    """(mime, байты) из кэша или None. Попадание продлевает срок (как у Telegram)."""
    try:
        name = _name(kind, url)
        path = os.path.join(cache_dir(), name)
        with open(path, "rb") as f:
            blob = f.read()
    except FileNotFoundError:
        return None
    except Exception as e:      # noqa: BLE001 — кэш не имеет права ронять программу
        _LOG.info(f"[media-cache] не прочитан ({type(e).__name__})")
        return None
    got = _decrypt(name, blob)
    if got is None:
        #Не наш ключ (переустановка), испорченный или подложенный файл: убираем, чтобы
        #следующий показ записал целый.
        _remove(path)
        return None
    try:
        os.utime(path, None)
    except OSError:
        pass
    return got


def put(kind: str, url: str, mime: str, body: bytes) -> bool:
    """Положить картинку. False — не положили (не тот тип, слишком большая, сбой диска)."""
    global _writes
    if mime not in ALLOWED_MIME or not body or len(body) > MAX_ITEM_BYTES.get(kind, 0):
        return False
    try:
        name = _name(kind, url)
        folder = cache_dir()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "wb") as f:
            f.write(_encrypt(name, mime, body))
        os.replace(tmp, path)
    except Exception as e:      # noqa: BLE001
        _LOG.info(f"[media-cache] не сохранён ({type(e).__name__}: {e})")
        return False
    _writes += 1
    if _writes % _SWEEP_EVERY == 0:
        sweep()
    return True


def fetch_through(kind: str, url: str, fetcher):
    """Отдать из кэша, а при промахе — загрузить `fetcher()` и положить.

    `fetcher` возвращает (mime, байты) или бросает исключение — его и получит
    вызывающий: отличать «картинки нет» от «сети нет» обязан он, а не кэш. Одну и ту
    же картинку одновременно грузит один поток: список чатов просит десяток одинаковых
    аватарок разом, и каждая промах-загрузка повторялась бы десять раз."""
    hit = get(kind, url)
    if hit is not None:
        return hit
    with _inflight_lock:
        lock = _inflight.setdefault(f"{kind}\n{url}", threading.Lock())
    with lock:
        try:
            hit = get(kind, url)
            if hit is not None:
                return hit
            mime, body = fetcher()
            put(kind, url, mime, body)
            return mime, body
        finally:
            with _inflight_lock:
                _inflight.pop(f"{kind}\n{url}", None)


def _remove(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except Exception as e:      # noqa: BLE001
        _LOG.info(f"[media-cache] не удалён ({type(e).__name__})")
        return False


def sweep(now: float | None = None) -> dict:
    """Убрать просроченное, чужое и всё сверх потолка (сначала самое давнее)."""
    now = time.time() if now is None else now
    removed = 0
    alive = []
    try:
        entries = list(os.scandir(cache_dir()))
    except FileNotFoundError:
        return {"removed": 0, "bytes": 0, "files": 0}
    except Exception as e:      # noqa: BLE001
        _LOG.info(f"[media-cache] уборка не выполнена ({type(e).__name__})")
        return {"removed": 0, "bytes": 0, "files": 0}
    for entry in entries:
        try:
            if not entry.is_file():
                continue
            st = entry.stat()
        except OSError:
            continue
        m = _FILE_RE.match(entry.name)
        if m is None:
            #Оборванная запись (.tmp) старше часа или файл чужого формата.
            if not entry.name.endswith(".tmp") or now - st.st_mtime > 3600:
                removed += _remove(entry.path)
            continue
        if now - st.st_mtime > TTL_DAYS[m.group(1)] * 86400:
            removed += _remove(entry.path)
            continue
        alive.append((st.st_mtime, st.st_size, entry.path))
    total = sum(size for _, size, _ in alive)
    left = len(alive)
    if total > MAX_TOTAL_BYTES:
        #Не до самого потолка, а с запасом: иначе уборка шла бы на каждой записи.
        target = int(MAX_TOTAL_BYTES * 0.9)
        for _, size, path in sorted(alive):
            if total <= target:
                break
            if _remove(path):
                removed += 1
                left -= 1
                total -= size
    return {"removed": removed, "bytes": total, "files": left}


def purge() -> int:
    """Убрать ВСЁ (смена человека за компьютером, кнопка «Очистить кэш»)."""
    n = 0
    try:
        entries = list(os.scandir(cache_dir()))
    except FileNotFoundError:
        return 0
    except Exception as e:      # noqa: BLE001
        _LOG.warning(f"[media-cache] очистка не выполнена ({type(e).__name__})")
        return 0
    for entry in entries:
        if entry.is_file():
            n += _remove(entry.path)
    return n


def stats() -> dict:
    """Сколько занято — для блока «Кэш картинок» в настройках программы."""
    used = 0
    files = 0
    by_kind = {k: 0 for k in TTL_DAYS}
    try:
        for entry in os.scandir(cache_dir()):
            m = _FILE_RE.match(entry.name)
            if m is None:
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            used += size
            files += 1
            by_kind[m.group(1)] += size
    except FileNotFoundError:
        pass
    except Exception as e:      # noqa: BLE001
        _LOG.info(f"[media-cache] размер не посчитан ({type(e).__name__})")
    return {"bytes": used, "files": files, "by_kind": by_kind,
            "max_bytes": MAX_TOTAL_BYTES, "ttl_days": dict(TTL_DAYS)}
