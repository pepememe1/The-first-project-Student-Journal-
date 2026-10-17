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
from sqlalchemy.orm import Session

from .. import media_refs
from ..db import get_db
from ..models import Conversation, User

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
