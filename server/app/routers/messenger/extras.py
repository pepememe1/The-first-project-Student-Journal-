"""
extras.py — Перевод сообщений и GIF-пикер — две внешние службы, которые к самой переписке
отношения не имеют и живут отдельно.

Часть пакета `routers/messenger` (разрез 3.7.7). Общий роутер, проверки прав и
сборка ответов — в `_common.py`; порядок регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — роутеры, модели, хелперы


# ── Перевод ──────────────────────────────────────────────────────────────────────────
@router.post("/translate")
def translate_text(payload: dict = Body(...), user: User = Depends(get_current_user)):
    """Перевести произвольный текст на выбранный язык.

    Эндпоинт НЕ привязан к сообщению намеренно: им пользуется и кнопка «перевести» на
    чужой реплике, и предпросмотр своего текста до отправки. Привязка к id сообщения
    добавила бы проверку участия там, где переводится собственный черновик.

    Своего лимита частоты нет: перевод идёт по нажатию человека, а результат кэшируется
    (одну реплику в групповом чате открывают несколько человек). Автоперевод исходящих
    ограничен тем же анти-флудом, что и сама отправка. ⚠️ Переводчик — Google Translate
    (3.5.5, см. translate_service.py), от БД больше не зависит вовсе."""
    from ... import translate_service
    text = (payload.get("text") or "").strip()
    dst = (payload.get("to") or "").strip().lower()
    src = (payload.get("from") or translate_service.AUTO).strip().lower()
    if not text:
        raise HTTPException(status_code=400, detail="Нужен текст")
    return translate_service.translate(text, dst, src)


@router.get("/translate/languages")
def translate_languages(_user: User = Depends(get_current_user)):
    """Список языков одним источником: клиент не держит свою копию, иначе однажды
    покажет язык, которого сервер не знает."""
    from ... import translate_service
    return {"languages": [{"code": c, "name": n}
                          for c, n in translate_service.LANGUAGES.items()],
            "auto": translate_service.AUTO}


# ── GIF-пикер (Klipy) ────────────────────────────────────────────────────────────────
@router.get("/gifs/categories")
def gif_categories(_user: User = Depends(get_current_user)):
    from ... import gif_service
    return {"categories": gif_service.categories()}


@router.get("/gifs/trending")
def gif_trending(page: int = Query(1, ge=1), _user: User = Depends(get_current_user)):
    from ... import gif_service
    return gif_service.trending(page=page)


@router.get("/gifs/search")
def gif_search(q: str = Query(...), page: int = Query(1, ge=1),
              _user: User = Depends(get_current_user)):
    from ... import gif_service
    return gif_service.search(q, page=page)
