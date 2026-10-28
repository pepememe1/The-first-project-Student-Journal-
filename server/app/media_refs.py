"""
media_refs.py — аватарка ССЫЛКОЙ, а не картинкой внутри JSON (17.10.2026).

Просьба Ярослава: кэшировать аватарки, гифки и баннеры «как у Discord». Гифки и баннеры —
ссылки на CDN Klipy, их кэширует тот, кто рисует. А своя аватарка (обрезанная картинка
256×256) лежала data:URL'ом в `prefs` и уезжала ЦЕЛИКОМ внутри каждого ответа, где есть
человек: список чатов, «О беседе» со всеми участниками, каталог, трекер. Эти ответы
перечитываются на каждом тике опроса и на каждом сигнале сокета — в живой группе на
30 человек это до мегабайта за тик на каждого участника, и закэшировать такое нельзя:
картинка неотделима от JSON, который меняется каждую секунду.

Discord решает это так: в ответе ссылка с хешем содержимого, сама картинка — отдельным
адресом, неизменным, пока не сменили аватарку, и кэшируется один раз. Здесь то же:
`avatar_out` подставляет вместо data:URL адрес `/media/avatar?k=…&i=…&v=…&s=…`.

🔒 ССЫЛКА ПОДПИСАНА, ВХОДА ОНА НЕ ТРЕБУЕТ. `<img>` не умеет слать заголовок
`Authorization`, а сессия у нас в нём, не в куках. Поэтому доступ даёт подпись: ссылку
выдаёт только ответ, который зритель и так вправе видеть, а подобрать её нельзя
(HMAC от секрета сервера). Сменил человек аватарку или убрал её — меняется хеш `v`, и
старая ссылка отвечает 404: снятая картинка перестаёт открываться сразу, а не живёт в
чужих закладках. Маска модератора срабатывает раньше: в его карточке аватарки нет
вовсе, ссылку взять неоткуда.

⚠️ ВКЛЮЧАЕТ КЛИЕНТ, А НЕ СЕРВЕР. Ссылку получает только тот, кто прислал заголовок
`X-Gb-Features: avatar-refs`. Старые сборки — программа 4.1.2 со своей копией сайта
внутри .exe, приложение до обновления по воздуху — о `/media/avatar` не знают и
нарисовали бы вместо аватарки пустой кружок. Им по-прежнему уходит data:URL.

⚠️ ЛОКАЛЬНЫЙ СЕРВЕР ПРОГРАММЫ ССЫЛОК НЕ ВЫДАЁТ (`ENABLED = False` ставит
`desktop/local_api.py`). Его ответы идут по петле и ничего не стоят, а `/media/avatar` в
программе перехватывает кэш картинок (`desktop/media_cache.py`) и берёт картинку с БОЯ:
локальная ссылка, подписанная локальным секретом, там не нашлась бы.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from contextvars import ContextVar
from urllib.parse import urlencode

from . import config

FEATURE_HEADER = "x-gb-features"
FEATURE = "avatar-refs"
PATH = "/media/avatar"

#Выдаёт ли этот процесс ссылки вообще. Снимает только локальный сервер программы — см.
#докстринг модуля.
ENABLED = True

#Тот же список, что принимает сохранение аватарки (`routers/me._AVATAR_DATA_PREFIXES`):
#только растр. SVG здесь нет и быть не может — это документ, а не картинка.
_MIME_BY_PREFIX = {
    "data:image/jpeg;": "image/jpeg", "data:image/jpg;": "image/jpeg",
    "data:image/png;": "image/png", "data:image/webp;": "image/webp",
    "data:image/gif;": "image/gif",
}

#u — аватарка человека, c — картинка группы или канала, m — сообщение-изображение
#(27.10.2026: «поделиться» аватаркой беседы в чат). У сообщения тело — data:URL, и в
#ленте и списке чатов его заменяет эта же ссылка: иначе картинка на сотню килобайт
#ездила бы в каждом ответе ленты.
#d — то же изображение, но для МОДЕРАЦИИ (28.10.2026): «m» у удалённого у всех отвечает
#404, а модератор удалённое видеть обязан. Ссылку «d» выдаёт только
#`mod_conversation_messages` (модерация, со следом в журнале); она гаснет вместе с телом,
#когда уборка (`retention.blank_deleted_bodies`) его сотрёт — хеш `v` перестаёт сходиться.
KINDS = ("u", "c", "m", "d")

#Подпись картинки там, где текст читают одной строкой: снимок жалобы, напоминание, его
#уведомление, превью очереди модерации (проверка конфликтов 28.10.2026). Одна на всех —
#и на запись нового снимка, и на чтение строк, записанных до правки.
IMAGE_LABEL = "[изображение]"

_WANTS: ContextVar[bool] = ContextVar("gb_avatar_refs", default=False)


def begin(header_value: str):
    """Запомнить на время запроса, просил ли клиент ссылки. Вернуть метку для `end`."""
    asked = {x.strip().lower() for x in (header_value or "").split(",")}
    return _WANTS.set(bool(ENABLED) and FEATURE in asked)


def end(token) -> None:
    _WANTS.reset(token)


def wanted() -> bool:
    return _WANTS.get()


def _key() -> bytes:
    """Ключ подписи: производный от секрета токенов, со своим назначением — подпись
    ссылки на картинку ничем не поможет подделать токен входа, и наоборот."""
    return hmac.new(config.JWT_SECRET.encode("utf-8"), b"gradebook-media-ref:v1",
                    hashlib.sha256).digest()


def version_of(value: str) -> str:
    """Хеш содержимого: меняется вместе с картинкой, поэтому адрес неизменен, пока
    неизменна она, — ровно это и позволяет кэшировать его надолго."""
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def _sign(kind: str, owner_id: str, ver: str) -> str:
    mac = hmac.new(_key(), f"{kind}|{owner_id}|{ver}".encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:16]).decode("ascii").rstrip("=")


def is_data_avatar(value) -> bool:
    return isinstance(value, str) and value.startswith(tuple(_MIME_BY_PREFIX))


def text_or_label(value) -> str:
    """Текст для показа одной строкой: data:URL картинки — подписью, остальное как есть.

    Нужен на ЧТЕНИИ, а не только на записи: жалобы и напоминания, сохранённые кодом 4.1.6 до
    правки, держат data:URL в тексте (нашёл Полковник 28.10.2026)."""
    return IMAGE_LABEL if is_data_avatar(value) else (value or "")


def ref_url(kind: str, owner_id: str, value: str) -> str:
    ver = version_of(value)
    query = urlencode({"k": kind, "i": owner_id, "v": ver, "s": _sign(kind, owner_id, ver)})
    return f"{PATH}?{query}"


def verify(kind: str, owner_id: str, ver: str, sig: str) -> bool:
    if kind not in KINDS or not owner_id or not ver or not sig:
        return False
    return hmac.compare_digest(_sign(kind, owner_id, ver), sig)


def avatar_out(value, kind: str, owner_id: str) -> str:
    """Что положить в поле `avatar` ответа: ссылку, если клиент её просил и в поле своя
    картинка, иначе — значение как есть (пусто, гифка Klipy, data:URL для старых)."""
    value = value if isinstance(value, str) else ""
    if not value or not owner_id or not _WANTS.get() or not is_data_avatar(value):
        return value
    return ref_url(kind, owner_id, value)


def decode(value: str):
    """(mime, байты) из data:URL или None — чужой тип, не base64, пустота."""
    for prefix, mime in _MIME_BY_PREFIX.items():
        if value.startswith(prefix):
            rest = value[len(prefix):]
            if not rest.startswith("base64,"):
                return None
            try:
                data = base64.b64decode(rest[len("base64,"):], validate=True)
            except (binascii.Error, ValueError):
                return None
            return (mime, data) if data else None
    return None
