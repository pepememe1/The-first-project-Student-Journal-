"""
media.py — раздача аватарки по подписанной ссылке (`media_refs`, 17.10.2026).

Входа ручка не требует намеренно: `<img>` не шлёт заголовок `Authorization`. Доступ даёт
подпись, а выдаёт её только ответ, который зритель и так вправе видеть (см. докстринг
`app/media_refs.py`). Неверная подпись, удалённый человек, сменённая или снятая
картинка — честный 404 без похода по базе там, где подпись не сошлась.

⚠️ Обычный `def`, а не `async def`: чтение из SQLite блокирующее, а цикл событий один
на весь сервер (§4.42).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import klipy_media, media_refs, throttle
from ..db import get_db
from ..models import Conversation, Message, User

router = APIRouter(tags=["media"])

#Сутки, а не год, хотя адрес и неизменен: картинку, которую человек снял, браузер общего
#компьютера аудитории не должен держать у себя месяцами. После суток — проверка по ETag,
#то есть короткий ответ 304 без самой картинки.
_CACHE = "private, max-age=86400"


def _gone() -> Response:
    return Response(status_code=404, headers={"Cache-Control": "no-store"})


@router.get(media_refs.PATH)
def avatar(request: Request, k: str = "", i: str = "", v: str = "", s: str = "",
           db: Session = Depends(get_db)):
    if not media_refs.verify(k, i, v, s):
        return _gone()
    if k == "u":
        u = db.get(User, i)
        if u is None or u.deleted:
            return _gone()
        prefs = u.prefs if isinstance(u.prefs, dict) else {}
        value = prefs.get("avatar") or ""
    elif k in ("m", "d"):
        #Сообщение-изображение. «m» — для участников: удалённое у всех — 404, «удалил»
        #обязано убирать и картинку, а не только строку в ленте. «d» — для модерации: её
        #ссылку выдаёт только окно модератора, и удалённое она показывает (см. `KINDS`).
        msg = db.get(Message, int(i)) if i.isdigit() else None
        if msg is None or (msg.kind or "") != "image" or (k == "m" and msg.deleted_at):
            return _gone()
        value = msg.body or ""
    else:
        conv = db.get(Conversation, i)
        if conv is None:
            return _gone()
        value = conv.avatar or ""
    if not media_refs.is_data_avatar(value) or media_refs.version_of(value) != v:
        return _gone()
    decoded = media_refs.decode(value)
    if decoded is None:
        return _gone()
    mime, data = decoded
    etag = f'"{v}"'
    headers = {"Cache-Control": _CACHE, "ETag": etag, "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=mime, headers=headers)


#Гифка Klipy с CDN неизменна по адресу (в пути — идентификатор файла), поэтому год и
#immutable: браузер не переспрашивает её вовсе. Личного в ней нет — `public`.
_KLIPY_CACHE = "public, max-age=31536000, immutable"


@router.get(klipy_media.PREFIX + "{path:path}")
def klipy(path: str, request: Request):
    """Гифка Klipy с нашего домена (27.10.2026): без VPN CDN Klipy открывается не у всех.

    На бою закэшированный файл отдаёт Caddy сам (`@klipy_cached` в Caddyfile), сюда
    доходят только промахи — и тогда сервер один раз скачивает файл с CDN. Входа не
    требует: `<img>` не шлёт `Authorization`, а в файле нет ничего личного. Устройство и
    ограничения — `app/klipy_media.py`.
    ⚠️ Обычный `def`: поход на CDN и запись на диск блокирующие (§4.42)."""
    if not klipy_media.path_ok(path):
        return _gone()
    f = klipy_media.cached(path)
    if f is None:
        if not klipy_media.miss_allowed(throttle.client_ip(request)):
            return Response(status_code=429,
                            headers={"Cache-Control": "no-store", "Retry-After": "60"})
        f = klipy_media.fetch(path)
        if f is None:
            return _gone()
        if klipy_media.sweep_due():
            _sweep_klipy_cache()
    return FileResponse(f, media_type=klipy_media.mime_of(path),
                        headers={"Cache-Control": _KLIPY_CACHE,
                                 "X-Content-Type-Options": "nosniff"})


def _sweep_klipy_cache() -> None:
    """Удержать кэш гифок в пределе, не трогая аватарки и баннеры. Сбой уборки не
    должен ронять показ гифки — файл уже получен."""
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        klipy_media.sweep(klipy_media.protected_paths(db))
    except Exception as e:      # noqa: BLE001
        from .. import events
        events.record("warn", "klipy_sweep_failed", f"уборка кэша гифок: {e}"[:300], "", "")
    finally:
        db.close()
