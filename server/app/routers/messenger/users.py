"""
users.py — Собеседники: каталог, чужой профиль, общие беседы, личные заметки, свой
статус и шаблоны быстрых ответов преподавателя.

Часть пакета `routers/messenger` (разрез 3.7.7). Общий роутер, проверки прав и
сборка ответов — в `_common.py`; порядок регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — роутеры, модели, хелперы


@router.get("/users")
def directory(role: str = Query("student"), q: str = Query(""), page: int = Query(0),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Каталог/поиск для выбора собеседника. Вкладки — по роли (student|teacher), поиск по
    ФИО, сортировка по алфавиту, постранично. Отдаём ТОЛЬКО безопасные поля (§9).

    Поиск и сортировку делаем в Python (не SQL ilike): SQLite без ICU не умеет
    регистронезависимый LIKE для кириллицы, а датасет колледжа умещается в память.
    Себя из списка исключаем.

    ⚠️ Роли отбираются по БЕЛОМУ списку. Благодаря этому роль `parent` невидима по
    построению: чтобы кого-то скрыть, ничего делать не нужно — нужно явно РАЗРЕШИТЬ.
    Вкладка «Родители» открыта только куратору и администратору, причём куратору видны
    лишь родители его групп."""
    allowed = ("student", "teacher")
    if user.role == "admin" or (user.role == "teacher" and (user.curated_groups or [])):
        allowed += ("parent",)
    #Сам родитель ищет только других родителей — списка студентов и преподавателей у него нет.
    if user.role == "parent":
        allowed = ("parent",)
    role = role if role in allowed else allowed[0]
    rows = (db.query(User)
            .filter(User.role == role, User.deleted == False, User.id != user.id).all())  # noqa: E712
    if role == "parent":
        #Показываем только тех, с кем переписка реально разрешена — иначе каталог обещал
        #бы собеседника, а открытие чата отвечало бы 403.
        rows = [u for u in rows if _may_list_parent(db, user, u)]
    ql = (q or "").strip().lower()
    if ql:
        rows = [u for u in rows if ql in (u.full_name or u.name or "").lower()]
    rows.sort(key=lambda u: (u.full_name or u.name or u.login or "").lower())
    total = len(rows)
    page = max(0, int(page or 0))
    chunk = rows[page * _PAGE_USERS:(page + 1) * _PAGE_USERS]
    onl = _online_logins()
    sm = _status_map(db, [u.id for u in chunk])
    out = [_safe_user(u, onl, status=sm.get(u.id)) for u in chunk]
    if role == "parent":
        #§12: подпись «род. <группа>» в каталоге — куратор видит родителя, но не всегда
        #знает, чей он, пока не откроет карточку. Только АКТИВНЫЕ/подтверждённые дети
        #(та же логика, что определяет саму видимость родителя, см. _may_list_parent).
        groups_by_id = {u.id: sorted(_parent_group_names(db, u)) for u in chunk}
        for d in out:
            d["groups"] = groups_by_id.get(d["id"], [])
    return {"users": out, "total": total, "page": page, "page_size": _PAGE_USERS}


@router.get("/users/{user_id}/profile")
def user_profile(user_id: str, _user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Публичная карточка (портфолио) — только безопасные поля."""
    u = db.query(User).filter(User.id == user_id, User.deleted == False).first()  # noqa: E712
    if u is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    #Родитель невидим и здесь. Иначе скрытие в каталоге обходилось бы прямым запросом по
    #id: карточка отдаёт ФИО и «О себе», то есть ровно то, что мы прячем.
    if u.role == "parent" and u.id != _user.id and not _may_list_parent(db, _user, u):
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    sm = _status_map(db, [user_id])
    #⚠️ Отдаём ТОЛЬКО витрину — то, что человек сам отметил галочкой, — а не весь его
    #список. Полный список показывает, чего у него НЕТ, а это уже про его поведение в
    #продукте: сколько он ищет, что нашёл, чего не нашёл. Наружу это не наше дело.
    from ... import easter_eggs
    return {"profile": _safe_user(u, _online_logins(), status=sm.get(user_id)),
            "achievements": easter_eggs.showcase_ids(u.id, db)}


@router.get("/users/{user_id}/shared")
def user_shared(user_id: str, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """«Общие группы»/«Общие каналы» на карточке чужого профиля (Discord-style).

    Пересечение бесед, где участвуем ОБА — безопасно по построению: раскрываем только
    те группы/каналы, в которых вызывающий и так уже состоит, ничего нового о чужом
    членстве не утекает. `saved`/личные ЛС/модерация в пересечение не входят намеренно —
    «общее» здесь означает ровно то, что показывает Discord (сервера), а не любую беседу."""
    mine = {r[0] for r in db.query(ConversationParticipant.conversation_id)
            .filter(ConversationParticipant.user_id == user.id).all()}
    theirs = {r[0] for r in db.query(ConversationParticipant.conversation_id)
              .filter(ConversationParticipant.user_id == user_id).all()}
    shared_ids = mine & theirs
    if not shared_ids:
        return {"groups": [], "channels": []}
    convs = (db.query(Conversation)
             .filter(Conversation.id.in_(shared_ids), Conversation.kind.in_(("group", "channel")))
             .order_by(Conversation.title).all())
    groups = [{"id": c.id, "title": c.title} for c in convs if c.kind == "group"]
    channels = [{"id": c.id, "title": c.title} for c in convs if c.kind == "channel"]
    return {"groups": groups, "channels": channels}


@router.get("/users/{user_id}/note")
def get_user_note(user_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Личная заметка ВЫЗЫВАЮЩЕГО о человеке (Discord-style «Notes») — видна только ему.

    Разрешена и про САМОГО СЕБЯ (author_id == about_user_id == user_id): «памятка себе»
    на своей же карточке профиля — так просил заказчик, отдельного запрета не заводим.
    404-проверку существования цели не делаем: заметка — это данные автора, не цели, и
    её можно писать даже про кого-то, кого только что удалили (текст останется историей)."""
    row = (db.query(UserNote)
           .filter(UserNote.author_id == user.id, UserNote.about_user_id == user_id)
           .first())
    return {"text": row.text if row else ""}


@router.post("/users/{user_id}/note")
def set_user_note(user_id: str, payload: dict = Body(...),
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Сохраняет/стирает заметку. Пустой текст после обрезки — УДАЛЯЕТ строку, а не
    оставляет пустую: иначе таблица копила бы мёртвые записи на каждое «написал и стёр»."""
    text = str(payload.get("text") or "").strip()[:_MAX_NOTE_CHARS]
    row = (db.query(UserNote)
           .filter(UserNote.author_id == user.id, UserNote.about_user_id == user_id)
           .first())
    if not text:
        if row is not None:
            db.delete(row)
            db.commit()
        return {"ok": True, "text": ""}
    if row is None:
        row = UserNote(author_id=user.id, about_user_id=user_id)
        db.add(row)
    row.text = text
    row.updated_at = _now()
    db.commit()
    return {"ok": True, "text": text}


# ── Статус пользователя (§D7) ─────────────────────────────────────────────────────────
@router.get("/status")
def get_my_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Мой текущий статус (для инициализации переключателя в UI)."""
    row = db.query(UserStatus).filter(UserStatus.user_id == user.id).first()
    return {"kind": row.kind if row else "", "custom_text": row.custom_text if row else ""}


@router.post("/status")
def set_my_status(payload: dict = Body(...), user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Установить свой статус (dnd/studying/away, '' — сбросить). custom_text — только у
    преподавателя (см. MESSENGER-PLAN §D7); у прочих ролей молча игнорируем текст."""
    kind = payload.get("kind") or ""
    if kind not in _STATUS_KINDS:
        raise HTTPException(status_code=400, detail="Некорректный статус")
    text = (payload.get("custom_text") or "").strip()[:80] if user.role == "teacher" else ""
    row = db.query(UserStatus).filter(UserStatus.user_id == user.id).first()
    if row is None:
        row = UserStatus(user_id=user.id)
        db.add(row)
    row.kind = kind
    row.custom_text = text
    row.updated_at = _now()
    db.commit()
    return {"ok": True, "kind": row.kind, "custom_text": row.custom_text}


@router.get("/templates")
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(MessageTemplate).filter(MessageTemplate.user_id == user.id)
            .order_by(MessageTemplate.position.asc(), MessageTemplate.id.asc()).all())
    return {"templates": [{"id": t.id, "body": t.body} for t in rows]}


@router.post("/templates")
def create_template(payload: dict = Body(...), user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Шаблоны доступны преподавателям и администрации")
    body = (payload.get("body") or "").strip()[:500]
    if not body:
        raise HTTPException(status_code=400, detail="Пустой шаблон")
    count = db.query(MessageTemplate).filter(MessageTemplate.user_id == user.id).count()
    if count >= _MAX_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Не больше {_MAX_TEMPLATES} шаблонов")
    t = MessageTemplate(user_id=user.id, body=body, position=count, created_at=_now())
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "body": t.body}


@router.delete("/templates/{tid}")
def delete_template(tid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = (db.query(MessageTemplate)
         .filter(MessageTemplate.id == tid, MessageTemplate.user_id == user.id).first())
    if t is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    db.delete(t)
    db.commit()
    return {"ok": True}
