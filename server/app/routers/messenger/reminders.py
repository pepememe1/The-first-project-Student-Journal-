"""
reminders.py — Напоминания о сообщении (§D19): разбор даты без LLM, создание, список, снятие.

Часть пакета `routers/messenger` (разрез 3.7.7). Общий роутер, проверки прав и
сборка ответов — в `_common.py`; порядок регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — роутеры, модели, хелперы

import college_clock


@router.get("/messages/{mid}/reminder-suggest")
def reminder_suggest(mid: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Что предложить напомнить по этому сообщению. `when` пустой — даты не нашли.

    Функция намеренно консервативна: не уверена — не предлагает. Ложная подсказка
    раздражает сильнее, чем её отсутствие."""
    m = db.query(Message).filter(Message.id == mid).first()
    if m is None or m.deleted_at:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _require_participant(db, m.conversation_id, user)
    import reminder_parse
    found = reminder_parse.parse_reminder(m.body or "", college_clock.now())
    if not found:
        return {"when": "", "matched": ""}
    return {"when": found["when"].isoformat(), "matched": found["matched"]}


@router.post("/messages/{mid}/reminder")
def reminder_create(mid: int, payload: dict = Body(default={}),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Поставить напоминание по сообщению. `when` (ISO) — явно выбранное время; без него
    берём разобранное из текста."""
    from ...models import Reminder
    m = db.query(Message).filter(Message.id == mid).first()
    if m is None or m.deleted_at:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _require_participant(db, m.conversation_id, user)

    when = (payload.get("when") or "").strip()
    if not when:
        import reminder_parse
        found = reminder_parse.parse_reminder(m.body or "", college_clock.now())
        if not found:
            raise HTTPException(status_code=400,
                                detail="В сообщении нет даты — укажите время вручную.")
        when = found["when"].isoformat()
    try:
        parsed = datetime.fromisoformat(when)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат времени") from None
    if parsed.tzinfo is None:
        #Время без зоны — это время на часах КОЛЛЕДЖА: так его видит человек в окне
        #напоминания. До 15.10.2026 оно считалось UTC и уезжало на восемь часов.
        parsed = parsed.replace(tzinfo=college_clock.TZ)
    #🔒 Хранить — СТРОГО в UTC: `_fire_due_reminders` сравнивает `remind_at` со «сейчас»
    #СТРОКАМИ ISO. Метка с «+08:00» сравнилась бы неверно, и напоминание сработало бы не
    #вовремя — тихо и только у тех, чей клиент прислал время со смещением.
    parsed = parsed.astimezone(timezone.utc)

    #Текст храним СНИМКОМ: автор может отредактировать или удалить сообщение, а напоминание
    #должно остаться тем, на что человек рассчитывал. Изображение — подписью: его тело —
    #data:URL, и в уведомлении стоял бы base64 (`_body_snapshot`).
    row = Reminder(login=user.login or "", conversation_id=m.conversation_id,
                   message_id=m.id, text=_body_snapshot(m)[:1000],
                   remind_at=parsed.isoformat(), created_at=_now(), fired_at="")
    db.add(row)
    db.commit()
    return {"ok": True, "reminder": _reminder_out(row)}


@router.get("/reminders")
def reminders_list(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Мои ещё не сработавшие напоминания (ближайшие сверху)."""
    from ...models import Reminder
    rows = (db.query(Reminder)
            .filter(Reminder.login == (user.login or ""), Reminder.fired_at == "")
            .order_by(Reminder.remind_at.asc()).limit(100).all())
    return {"reminders": [_reminder_out(r) for r in rows]}


@router.delete("/reminders/{rid}")
def reminder_delete(rid: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Отменить напоминание. Чужое не трогаем — 404 одинаков для «нет» и «не твоё»."""
    from ...models import Reminder
    row = db.get(Reminder, rid)
    if row is None or row.login != (user.login or ""):
        raise HTTPException(status_code=404, detail="Напоминание не найдено")
    db.delete(row)
    db.commit()
    return {"ok": True}
