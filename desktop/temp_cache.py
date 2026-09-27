"""
temp_cache.py — кэш ВОССТАНОВИМЫХ данных программы в %TEMP% для быстрого запуска.

Просьба Ярослава (25.09.2026): «кэшировать часть данных в %TEMP% для быстрого запуска».
Что кэшировать, решил ЗАМЕР холодного старта (27.09.2026, из исходников, до страницы
входа ~2.2–2.6 с):

| шаг                                          | цена            | чем лечится                 |
|----------------------------------------------|-----------------|-----------------------------|
| импорт серверного пакета, fastapi, sqlalchemy| ~1.7 с          | НЕ кэшем: байткод и так     |
|                                              |                 | кэшируется рядом с кодом    |
| первый `mimetypes.guess_type` (реестр Windows)| 0.42–0.59 с    | НЕ кэшем: типы задаём сами, |
|                                              |                 | `local_api._fast_mimetypes` |
| `init_db` (из них опрос видеокарты 0.08 с)   | ~0.15 с         | не трогали — мало           |
| полный снимок расписания колледжа с портала  | **149 с** сети, | ЭТОТ кэш                    |
|                                              | 89 запросов     |                             |

Последняя строка и есть то, что человек видит: после КАЖДОГО запуска программы
расписание преподавателя две с половиной минуты отвечало «собирается», а портал получал
сотни запросов с каждого ПК колледжа. Снимок публичный и меняется редко — его место
в кэше, а не в сети.

Правила кэша:
- ТОЛЬКО ВОССТАНОВИМОЕ. %TEMP% чистят «Очистка диска» и антивирусы; пропажа файла =
  пересборка, а не потеря работы. Правки человека сюда не попадают НИКОГДА — их дом
  локальная копия и очередь `desk_outbox`.
- ПОД КЛЮЧОМ УСТРОЙСТВА. В снимке расписания ФИО преподавателей: на портале они
  публичны, но открытым текстом в каталог, общий для всех программ пользователя, мы
  их не кладём (правило проекта для ПДн). Ключ — производный от ключа данных программы
  (DPAPI), со своим назначением: утечка кэша не даёт ничего для расшифровки базы.
- С ПРОВЕРКОЙ ПОДЛИННОСТИ. Fernet подписывает содержимое: подложенный или испорченный
  файл не расшифруется и будет МОЛЧА пропущен (как отсутствующий). Иначе подмена файла в
  %TEMP% меняла бы расписание, которое видит преподаватель.
- Имя файла — по белому списку символов, запись — через временный файл и `os.replace`:
  оборванная запись не оставляет полуфайл, который пришлось бы отличать от целого.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import zlib

import log

_LOG = log.get("temp_cache")

_NAME_OK = re.compile(r"^[a-z0-9_.-]{1,64}$")
#Номер формата файла. Поменял раскладку — подними: старый файл станет «чужим» и
#будет пропущен, а не разобран по новым правилам.
_FORMAT = b"gbtc1"


def cache_dir() -> str:
    """%TEMP%\\GradeBookAI\\cache (на других ОС — системный временный каталог)."""
    return os.path.join(tempfile.gettempdir(), "GradeBookAI", "cache")


def _path(name: str) -> str:
    if not _NAME_OK.match(name or ""):
        raise ValueError(f"недопустимое имя кэша: {name!r}")
    return os.path.join(cache_dir(), name + ".bin")


def _key() -> bytes:
    """Ключ кэша: производный от ключа данных программы, со своим назначением."""
    from data import security
    return hmac.new(security.get_data_key(), b"gradebook-temp-cache:v1",
                    hashlib.sha256).digest()


def save(name: str, obj) -> bool:
    """Сжать, зашифровать и положить. False — не вышло (кэш не обязан работать)."""
    try:
        from data import security
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        #Сжимаем ДО шифрования: шифротекст не сжимается по построению (замер на снимке
        #колледжа: 1966 КБ JSON → 110 КБ).
        blob = _FORMAT + security._encrypt_bytes(zlib.compress(raw, 6), _key())
        path = _path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)
        return True
    except Exception as e:      # noqa: BLE001 — кэш не имеет права ронять программу
        _LOG.info(f"[temp-cache] {name}: не сохранён ({type(e).__name__}: {e})")
        return False


def load(name: str):
    """Прочитать. None — нет файла, чужой ключ, подделка, старый формат, мусор."""
    try:
        path = _path(name)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            blob = f.read()
        if not blob.startswith(_FORMAT):
            return None
        from data import security
        plain = security._decrypt_bytes(blob[len(_FORMAT):], _key())
        if not plain:
            #Не наш ключ или файл тронули: считаем, что кэша нет. Шум в журнале не нужен —
            #после переустановки программы (новый ключ) это штатная ситуация.
            return None
        return json.loads(zlib.decompress(plain).decode("utf-8"))
    except Exception as e:      # noqa: BLE001
        _LOG.info(f"[temp-cache] {name}: не прочитан ({type(e).__name__})")
        return None


def drop(name: str) -> None:
    try:
        os.remove(_path(name))
    except FileNotFoundError:
        pass
    except Exception as e:      # noqa: BLE001
        _LOG.info(f"[temp-cache] {name}: не удалён ({type(e).__name__})")
