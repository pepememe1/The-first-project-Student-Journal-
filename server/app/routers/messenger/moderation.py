"""
moderation.py — Модерация (`mod_router`, префикс /web/admin/messenger): жалобы, обращения,
просмотр переписки по тикету, ответ, удаление сообщения, глобальный мьют.

Часть пакета `routers/messenger` (разрез 3.7.7). Общий роутер, проверки прав и
сборка ответов — в `_common.py`; порядок регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — роутеры, модели, хелперы


# ── Чат с модерацией (сторона пользователя, кнопка ⚙) ────────────────────────────────
@router.get("/moderation")
def moderation_chat(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Личная беседа пользователя с командой модерации (создаётся при первом обращении).
    Пользователь пишет как обычно (он участник); отвечает модерация через админ-эндпоинт."""
    #Админ САМ и есть модерация — обращаться ему некуда (отвечает через /web/admin/messenger).
    #Иначе появлялся бы бессмысленный чат «админ пишет сам себе в поддержку».
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Администратор отвечает на обращения, а не пишет в них")
    conv_id = f"mod:{user.id}"
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv is None:
        now = _now()
        conv = Conversation(id=conv_id, kind="moderation", title="Модерация", created_at=now)
        db.add(conv)
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                       role="member", joined_at=now))
        db.commit()
    return {"conversation_id": conv_id, "kind": "moderation"}


@mod_router.get("/reports")
def mod_reports(status: str = Query("open"), admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    """Очередь жалоб (тикетов). status='' — все, иначе фильтр по статусу."""
    q = db.query(MessageReport)
    if status:
        q = q.filter(MessageReport.status == status)
    rows = q.order_by(MessageReport.id.desc()).limit(300).all()
    return {"reports": [_report_out(db, r) for r in rows]}


@mod_router.post("/reports/{rid}/resolve")
def mod_resolve(rid: int, payload: dict = Body(...), request: Request = None,
                admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Обработать тикет: сменить статус + заметка. Пишется в аудит."""
    r = db.query(MessageReport).filter(MessageReport.id == rid).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Тикет не найден")
    status = payload.get("status")
    if status not in _REPORT_STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус")
    r.status = status
    r.handled_by = admin.login
    r.handled_at = _now()
    r.resolution_note = (payload.get("resolution_note") or "")[:1000]
    db.commit()
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.report.resolve", target=str(rid), detail=status)
    return {"ok": True}


@mod_router.get("/conversations")
def mod_conversations(q: str = Query(""), kind: str = Query(""),
                      admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Список бесед для модерации (поиск по участникам, фильтр по типу)."""
    query = db.query(Conversation)
    if kind:
        query = query.filter(Conversation.kind == kind)
    convs = query.order_by(Conversation.created_at.desc()).limit(300).all()
    ql = (q or "").strip().lower()
    onl = _online_logins()
    out = []
    for c in convs:
        parts = (db.query(ConversationParticipant)
                 .filter(ConversationParticipant.conversation_id == c.id).all())
        names, people = [], []
        mset = _muted_set(db, [p.user_id for p in parts])
        for p in parts:
            u = db.query(User).filter(User.id == p.user_id).first()
            if u:
                names.append(u.full_name or u.login)
                #карточка: аватар, ФИО, роль, группа/предметы + состояние глобального мьюта
                people.append(_safe_user(u, onl, u.id in mset))
        if ql and not any(ql in n.lower() for n in names):
            continue
        out.append({"conversation_id": c.id, "kind": c.kind,
                    "title": c.title or " · ".join(names), "participants": names,
                    "people": people})
    return {"conversations": out}


@mod_router.get("/conversations/{conv_id}/messages")
def mod_conversation_messages(conv_id: str, report_id: int = Query(0), request: Request = None,
                              admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Прочитать ЛЮБУЮ беседу (модерация). Каждый вызов пишется в аудит (152-ФЗ).

    §правка: `report_id` — необязательный, передаёт фронт ТОЛЬКО во вкладке «Жалобы»
    (просмотр из тикета, см. AdminMessenger.vue::openConversation); вкладка «Обращения»
    его не знает и продолжает работать как раньше. Если тикет уже закрыт (resolved/
    dismissed/expired) — доступ к переписке ПО ЭТОМУ ТИКЕТУ закрывается: свободный
    просмотр чужой переписки без активного расследования — риск сам по себе (живой
    отзыв). Проверка СЕРВЕРНАЯ, а не только дизейбл кнопки во фронте — иначе прямой
    запрос к этому же URL с браузерным дебагом обходил бы «закрытую» кнопку."""
    _conversation(db, conv_id)
    if report_id:
        rep = db.query(MessageReport).filter(MessageReport.id == report_id).first()
        if rep is None or rep.conversation_id != conv_id:
            raise HTTPException(status_code=404, detail="Тикет не найден")
        if rep.status not in ("open", "in_review"):
            raise HTTPException(status_code=403, detail="Тикет закрыт — переписка больше не открывается")
    rows = (db.query(Message).filter(Message.conversation_id == conv_id)
            .order_by(Message.id.asc()).all())
    #ФИО автора — иначе в переписке с 2+ участниками (жалоба, групповой чат) не видно,
    #кто что написал (тот же _names_for, что уже используют обычные списки сообщений).
    names = _names_for(db, [m.sender_id for m in rows])
    #§правка: модерация должна видеть ПОЛНУЮ картину — текст удалённых сообщений и всю
    #цепочку правок. Обычный _msg_out() их НАМЕРЕННО прячет (для всех остальных
    #читателей это правильно), здесь — противоположный, осознанный контракт: доступ и
    #так журналируется аудитом ниже, а подотчётность важнее приватности при активной
    #проверке жалобы (см. комментарий у edit_message: «модерация должна видеть оригинал»).
    ids = [m.id for m in rows]
    edits_by_msg: dict[int, list] = {}
    if ids:
        for e in (db.query(MessageEdit).filter(MessageEdit.message_id.in_(ids))
                  .order_by(MessageEdit.id.asc()).all()):
            edits_by_msg.setdefault(e.message_id, []).append({"body": e.body_before, "at": e.edited_at})
    out = []
    for m in rows:
        d = _msg_out(m, sender_name=names.get(m.sender_id, ""))
        if m.deleted_at:
            d["body"] = m.body or ""
        versions = edits_by_msg.get(m.id)
        if versions:
            d["edit_versions"] = versions + [{"body": m.body or "", "at": m.edited_at or m.created_at}]
        out.append(d)
    _attach_rich_meta(db, out, admin.id)               #админ читает ту же ленту, что и участники
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.moderation.view", target=conv_id)
    return {"messages": out}


@mod_router.post("/conversations/{conv_id}/reply")
def mod_reply(conv_id: str, payload: dict = Body(...), request: Request = None,
              admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Ответ модерации в ЧАТ ОБРАЩЕНИЙ пользователя (kind='moderation'). Отправитель — админ;
    проверка участия НЕ применяется (это и есть право модерации). Пишется в аудит.

    ⚠️ Ограничено kind='moderation': раньше эндпоинт позволял админу вписать сообщение в
    ЛЮБУЮ беседу, включая приватный 1-на-1 чужих людей, от своего имени — это выходит за
    рамки «ответа модерации». Модерация читает любую переписку (mod_conversation_messages,
    с аудитом), но писать может только в официальный чат обращений."""
    conv = _conversation(db, conv_id)
    if conv.kind != "moderation":
        raise HTTPException(
            status_code=403,
            detail="Ответ модерации доступен только в чате обращений пользователя.")
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    import profanity_filter
    body = profanity_filter.censor(body, mask=profanity_filter.MESSENGER_SAFE_MASK)
    m = Message(conversation_id=conv_id, sender_id=admin.id, body=body[:_MAX_MSG_CHARS],
                created_at=_now())
    db.add(m)
    db.commit()
    db.refresh(m)
    _broadcast(db, conv_id)
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.moderation.reply", target=conv_id)
    return _msg_out(m, admin.id)


@mod_router.delete("/messages/{mid}")
def mod_delete_message(mid: int, request: Request = None,
                       admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Удалить ЛЮБОЕ сообщение у всех (модерация). Обычный DELETE /messages/{id} требует
    участия в беседе и авторства — админ в чужой переписке не участник, поэтому для
    модерации отдельный эндпоинт. Сообщение становится тумбстоуном (текст стирается,
    факт остаётся), закрепление снимается. Пишется в аудит (152-ФЗ, подотчётность)."""
    m = _message_in_conv(db, mid)
    if not m.deleted_at:
        m.deleted_at = _now()
        m.pinned = False
        db.commit()
        _broadcast(db, m.conversation_id)
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.moderation.delete", target=str(mid), detail=m.conversation_id)
    return {"ok": True, "id": mid, "deleted": True}


@mod_router.post("/users/{uid}/mute")
def mod_mute_user(uid: str, payload: dict = Body(default={}), request: Request = None,
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Глобальный мьют/размьют пользователя модерацией: замьюченный не может отправлять
    сообщения и создавать беседы (см. _guard_can_write/_guard_can_create). Пишется в аудит.
    Другого админа мьютить нельзя (модераторы не глушат друг друга)."""
    target = db.query(User).filter(User.id == uid, User.deleted == False).first()  # noqa: E712
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if target.role == "admin":
        raise HTTPException(status_code=400, detail="Нельзя замьютить администратора")
    muted = bool(payload.get("muted", True))
    row = db.query(MutedUser).filter(MutedUser.user_id == uid).first()
    if muted and row is None:
        db.add(MutedUser(user_id=uid, muted_by=admin.login, muted_at=_now()))
    elif not muted and row is not None:
        db.delete(row)
    db.commit()
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.moderation.mute" if muted else "msg.moderation.unmute", target=uid)
    return {"ok": True, "user_id": uid, "muted": muted}
