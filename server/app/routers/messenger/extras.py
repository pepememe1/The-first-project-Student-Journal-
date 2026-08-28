"""
extras.py — Перевод сообщений, GIF-пикер и личный вопрос Вектору: службы, которые к самой
переписке отношения не имеют и живут отдельно.

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


# ── Личный вопрос Вектору из ЛЮБОЙ беседы ────────────────────────────────────────────
@router.post("/chats/{conv_id}/vector")
def vector_in_chat(conv_id: str, payload: dict = Body(...),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """`/vector <вопрос>` в личном чате, группе или канале. Ответ виден ТОЛЬКО спросившему.

    🔒 ПОЧЕМУ ОТВЕТ НЕ СТАНОВИТСЯ СООБЩЕНИЕМ, А ВОЗВРАЩАЕТСЯ ПРЯМО ЗДЕСЬ. Раньше команда
    работала только в «Избранном», и ограничение было осознанным: Вектор скоупит данные по
    СПРОСИВШЕМУ, поэтому его реплика в общей беседе показала бы соседям выборку, к которой
    у них доступа нет (средние по группе, должники, состав — смотря кто спросил).

    Открыть команду везде и «просто пометить сообщение личным» было бы гораздо хуже, чем
    кажется: сообщения выбираются из БД в двух десятках мест (лента, дельта, поиск,
    последнее в списке чатов, счётчик непрочитанного, медиа, «Избранное», модерация), и
    флаг видимости пришлось бы не забыть в КАЖДОМ. Забыли бы в одном — и это не косметика,
    а показ чужих данных всей группе. Здесь забыть нечего по построению: в БД не пишется
    НИЧЕГО — ни вопрос, ни ответ.

    ⚠️ Цена решения названа честно: ответ живёт до перезагрузки страницы, его нельзя
    процитировать и он не ищется. Для личной подсказки в чужом чате это правильный размен;
    там, где история нужна, есть «Избранное» — оно и осталось прежним (там разговор с
    Вектором СОХРАНЯЕТСЯ обычными сообщениями, см. `_handle_vector_command`).

    ⚠️ Контекст переписки в модель НЕ УХОДИТ ВООБЩЕ. В «Избранном» контекст — это твои
    собственные заметки, и слать их можно; здесь это чужие сообщения, и отправлять их
    наружу ради удобства одного участника нельзя (то же правило, что у AI-сводки, где ФИО
    маскируются до отправки).

    ⚠️ Лимит — ТОТ ЖЕ анти-флуд, что у отправки (`msg_limit.check`). Ручка дороже обычного
    сообщения (поход в LLM), и оставить её без ограничителя значило бы сделать самый
    дешёвый способ нагрузить одноядерный боевой сервер.
    """
    _require_participant(db, conv_id, user)
    if _is_muted(db, user.id):
        raise HTTPException(status_code=403,
                            detail="Вы ограничены модерацией.")
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Нужен вопрос")

    from ... import msg_limit
    wait = msg_limit.check(user.id)
    if wait:
        raise HTTPException(status_code=429,
                            detail=f"Слишком часто. Подождите {wait} с.")

    from ..web import answer_vector_question, user_ui_locale
    answer = answer_vector_question(question, user, db, locale=user_ui_locale(user))
    return {"text": (answer.get("text") or "").strip(), "intent": answer.get("intent") or ""}
