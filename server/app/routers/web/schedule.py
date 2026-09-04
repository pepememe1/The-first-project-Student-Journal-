"""
schedule.py — Расписание портала ВСГУТУ, редактор правок админа и сверка накладок.

Часть пакета `routers/web` (разрезан в 3.6: один файл на 4288 строк правили
62 коммита за полгода — он и был главным источником конфликтов при
одновременной работе). Общий роутер и хелперы — в `_common.py`; порядок
регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — общий router, модели, хелперы


# РАСПИСАНИЕ ──────────────────────────────────────────────────────────────────────
# Снимок тянется с portal.esstu.ru серверным парсером (schedule_web, TTL-кэш). Данные
# публичные, ПДн не участвуют. Оффлайн/ошибка → пустой снимок (200), SPA покажет заглушку.
@router.get("/schedule/categories")
def schedule_categories():
    """Реестр категорий расписания портала (см. schedule/parser.py::CATEGORIES) —
    один источник правды для кнопок-категорий на фронте, список меток не
    дублируется в JS."""
    return {"categories": schedule_web.categories(),
           "default": schedule_web.default_category()}


@router.get("/schedule/groups")
def schedule_groups(category: str = Query(""), user: User = Depends(get_current_user)):
    """groups — плоский список (как раньше, ничей код не ломаем); by_course —
    {курс: [группы]} для кнопок «Курс» (3.5.5) — курс разведан по столбцу
    таблицы индекса портала, НЕ фиксирован на 4 (см. schedule_web.groups_by_course)."""
    return {"groups": schedule_web.list_groups(category),
            "by_course": schedule_web.groups_by_course(category)}


@router.get("/schedule/teacher")
def schedule_teacher(name: str = Query(""), category: str = Query(""),
                     user: User = Depends(get_current_user)):
    """Расписание ПРЕПОДАВАТЕЛЯ (пункт 2). Без name — пробуем сматчить ФИО текущего
    пользователя со спарсенными преподавателями (фамилия+инициалы). Полный снимок
    строится лениво в фоне: пока он готовится — {building: true}, клиент подождёт.
    category — по умолчанию колледж (единственная категория с реальными аккаунтами
    преподавателей); остальные категории тоже можно просмотреть (кто ведёт), просто
    там некому «самому себе» сматчиться."""
    snap, building = schedule_web.full_state(category)
    if snap is None:
        return {"available": False, "building": building, "teacher": "", "teachers": [],
                "week": schedule_web.current_week_parity(), "schedule": None,
                "matched_self": False}
    names = snap.teachers()
    matched = (name or "").strip() or schedule_web.match_teacher(W.display_name(user), names)
    weeks = schedule_web.teacher_weeks(snap, matched) if matched else None
    return {
        "available": weeks is not None,
        "building": building,
        "teacher": matched if weeks is not None else "",
        "teachers": names,
        "week": schedule_web.current_week_parity(),
        "schedule": {"weeks": weeks} if weeks is not None else None,
        "matched_self": (not name) and weeks is not None,   #авто-совпадение по ФИО
    }


_OV_DAYS = ["Пнд", "Втр", "Срд", "Чтв", "Птн", "Сбт"]


def _apply_overrides(db: Session, group: str, data) -> dict:
    """Накладывает админ-правки (ScheduleOverride) ПОВЕРХ портального расписания группы.
    action=set — задать/заменить пару в ячейке (неделя,день,№); remove — скрыть пару.
    Портала нет (data=None) → строим расписание ТОЛЬКО из правок (колледж без портала)."""
    ovs = db.query(ScheduleOverride).filter(
        ScheduleOverride.group_name == group,
        ScheduleOverride.deleted == False).all()  # noqa: E712
    if data is None and not ovs:
        return None
    base = dict(data) if data else {"name": group, "href": "", "weeks": {}}
    # глубокая копия недель, чтобы не мутировать TTL-кэш парсера
    weeks = {wk: {d: [dict(x) for x in ls] for d, ls in dd.items()}
             for wk, dd in (base.get("weeks") or {}).items()}
    for ov in ovs:
        wk, day = str(ov.week), ov.day
        sub = int(ov.subgroup or 0)
        daylist = weeks.setdefault(wk, {}).setdefault(day, [])
        # 🔥 Вытесняем ТОЛЬКО свою подгруппу, а не весь номер пары. Раньше здесь стояло
        # «убрать всё с этим pair_no», и вторая пара в том же слоте стирала первую — то
        # есть у разных подгрупп физически не могло быть разных предметов в первой паре,
        # хотя у преподавателя и студента такое расписание уже показывалось.
        # ⚠️ Пара «Совместно» (0) вытесняет ВСЁ в слоте, и это правильно: она объявлена
        # для всей группы, и оставить под ней чью-то половинную пару значило бы показать
        # человеку два занятия в одно время.
        if sub:
            daylist[:] = [x for x in daylist
                          if x.get("pair_no") != ov.pair_no or int(x.get("subgroup") or 0) not in (0, sub)]
        else:
            daylist[:] = [x for x in daylist if x.get("pair_no") != ov.pair_no]
        if ov.action == "set":
            daylist.append({"pair_no": ov.pair_no, "time": ov.time, "kind": ov.kind,
                            "subject": ov.subject, "teacher": ov.teacher, "room": ov.room,
                            "subgroup": sub,
                            "raw": ov.subject, "extra": "", "_override": True})
        # Внутри одного номера пары порядок задаёт подгруппа — иначе две половины
        # прыгали бы местами между загрузками, и это читалось бы как «расписание меняется».
        daylist.sort(key=lambda x: (x.get("pair_no") or 0, int(x.get("subgroup") or 0)))
    base["weeks"] = weeks
    return base


def _group_schedule(db: Session, group: str, category: str = ""):
    """Расписание группы категории — единый источник для студента, Вектора и
    админ-редактора. Админ-правки (ScheduleOverride) накладываются ТОЛЬКО для
    колледжа — оверлеи существуют для боевого журнала, у остальных категорий
    (просмотр без журнала) им взяться неоткуда и незачем."""
    data = schedule_web.get_group(group, category) if group else None
    category = category or schedule_web.default_category()
    if category != schedule_web.default_category():
        return data
    return _apply_overrides(db, group, data)


@router.get("/schedule")
def schedule_get(group: str = Query(""), category: str = Query(""),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Расписание группы. Без `group` — СВОЯ группа (студент), без `category` — категория
    ЭТОЙ группы из базы.

    ⚠️ 3.6: раньше пустая категория всегда резолвилась в колледж (см. `_group_schedule`),
    поэтому студент небюджетной группы (бакалавриат/заочное) открывал вкладку и получал
    «расписание недоступно»: его группу искали в чужом индексе портала. Ровно эта же
    ошибка уже была починена в админском эндпоинте (§3.5.5) — здесь её просто не
    заметили, потому что у колледжа всё сходилось само.

    Категорию ВОЗВРАЩАЕМ клиенту: страница по ней подсвечивает нужную кнопку категории,
    иначе человек видит своё расписание, а отмеченной стоит чужая категория."""
    g = (group or user.group_name or "").strip()
    cat = (category or "").strip()
    if not cat and g:
        grp = db.query(Group).filter(Group.name == g, Group.deleted == False).first()  # noqa: E712
        cat = (grp.category if grp else "") or ""
    data = _group_schedule(db, g, cat) if g else None
    return {
        "group": g,
        "category": cat or schedule_web.default_category(),
        "week": schedule_web.current_week_parity(),
        "schedule": data,           # dict GroupSchedule.to_dict() (+ правки) или null
        "available": bool(data and data.get("weeks")),
    }


@router.get("/schedule/export")
def schedule_export(group: str = Query(""), fmt: str = Query("xlsx"), category: str = Query(""),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Расписание группы файлом: fmt=xlsx|docx.

    Права те же, что у просмотра (`/web/schedule`): расписание берётся с публичного
    портала и ПДн не содержит, поэтому отдельного сужения по ролям не вводим — иначе
    получилось бы, что смотреть можно, а сохранить те же самые данные нельзя.

    Источник — СЛИТОЕ расписание (портал + правки админа), тот же `_group_schedule`,
    что видит студент на сайте. Иначе выгруженный файл расходился бы с сайтом, и
    доверия к нему не было бы."""
    g = (group or user.group_name or "").strip()
    if not g:
        raise HTTPException(status_code=400, detail="Нужна группа")
    data = _group_schedule(db, g, category)
    if not (data and data.get("weeks")):
        raise HTTPException(status_code=404, detail="Расписание для группы недоступно")

    weeks = data.get("weeks") or {}
    pair_times = data.get("pair_times") or []
    if fmt == "docx":
        from ... import docx_export
        payload = docx_export.build_schedule_docx(g, weeks, pair_times)
    else:
        from ... import xlsx_export
        payload = xlsx_export.build_schedule_xlsx(g, weeks, pair_times)
    return _file_response(payload, f"Расписание_{g}", fmt)


# ── Редактор расписания в админке (правки ПОВЕРХ портала) ────────────────────────────
@router.get("/admin/schedule")
def admin_schedule_get(group: str = Query(...), category: str = Query(""),
                       user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Слитое расписание группы (портал + правки) + сырой список правок для редактора.

    ⚠️ §3.5.5: раньше НИКОГДА не принимал `category` и всегда искал группу в индексе
    колледжа (`_group_schedule`/`schedule_web.get_group` по умолчанию резолвят пустую
    категорию в college) — бакалавриат/заочные группы, даже корректно импортированные
    (`Group.category` уже верный, см. `admin_import_schedule_category`), молча не
    находились в чужом индексе портала и отдавали «расписание недоступно». Параметр не
    обязателен: если клиент его не прислал, берём сохранённую категорию ИЗ БАЗЫ — так
    старые вызовы (без category) для колледжа продолжают работать как раньше."""
    g = (group or "").strip()
    cat = (category or "").strip()
    if not cat:
        grp = db.query(Group).filter(Group.name == g, Group.deleted == False).first()  # noqa: E712
        cat = (grp.category if grp else "") or ""
    merged = _group_schedule(db, g, cat)
    ovs = db.query(ScheduleOverride).filter(
        ScheduleOverride.group_name == g,
        ScheduleOverride.deleted == False).order_by(  # noqa: E712
        ScheduleOverride.week, ScheduleOverride.day, ScheduleOverride.pair_no).all()
    return {
        "group": g,
        "week": schedule_web.current_week_parity(),
        "schedule": merged,
        "available": bool(merged and merged.get("weeks")),
        "days": _OV_DAYS,
        "overrides": [{"id": o.id, "week": o.week, "day": o.day, "pair_no": o.pair_no,
                       "action": o.action, "subject": o.subject, "time": o.time,
                       "room": o.room, "teacher": o.teacher, "kind": o.kind,
                       "subgroup": int(o.subgroup or 0)} for o in ovs],
    }


def _apply_override_row(db: Session, payload: dict) -> ScheduleOverride:
    """Валидация + upsert ОДНОЙ правки ячейки. Возвращает строку (без commit и аудита —
    их делает вызывающий, чтобы пачка черновика легла одной транзакцией и одной записью
    в аудит). Общая для одиночной правки и пачечного сохранения."""
    g = (payload.get("group") or "").strip()
    day = (payload.get("day") or "").strip()
    action = (payload.get("action") or "set").strip()
    try:
        week = int(payload.get("week") or 1)
        pair_no = int(payload.get("pair_no") or 0)
        subgroup = int(payload.get("subgroup") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "week, pair_no и subgroup должны быть числами")
    if not g or day not in _OV_DAYS or week not in (1, 2) or pair_no < 1:
        raise HTTPException(400, "Проверьте группу, неделю (1/2), день и номер пары")
    if subgroup not in (0, 1, 2):
        raise HTTPException(400, "subgroup: 0 (вся группа), 1 или 2")
    if action not in ("set", "remove"):
        raise HTTPException(400, "action: set | remove")
    #Детерминированный id ячейки — один и тот же на вебе и десктопе (ключ синка): повторная
    #правка ТОЙ ЖЕ ячейки И ТОЙ ЖЕ подгруппы заменяет прежнюю на обеих платформах.
    #⚠️ Подгруппа входит в ключ (см. `schedule_override_id`) — без неё вторая пара с тем
    #же номером затирала первую вместе с чужой работой.
    oid = schedule_override_id(g, week, day, pair_no, subgroup)
    row = db.get(ScheduleOverride, oid)
    #Снимок ДО правки. Нужен, чтобы НЕ двигать updated_at, когда ничего не изменилось:
    #админ часто открывает ячейку и сохраняет её не тронув, а лишний бамп метки отправил
    #бы строку в дельту синка на все ПК без единой реальной правки.
    #(Уведомления здесь ни при чём — они уходят одной пачкой по кнопке «Опубликовать».)
    before = None if row is None else (row.action, row.subject, row.time, row.room,
                                       row.teacher, row.kind, int(row.subgroup or 0),
                                       bool(row.deleted))
    if row is None:
        row = ScheduleOverride(id=oid, group_name=g, week=week, day=day, pair_no=pair_no,
                               subgroup=subgroup)
        db.add(row)
    row.subgroup = subgroup
    row.action = action
    row.subject = (payload.get("subject") or "").strip()
    row.time = (payload.get("time") or "").strip()
    row.room = (payload.get("room") or "").strip()
    row.teacher = (payload.get("teacher") or "").strip()
    row.kind = (payload.get("kind") or "").strip()
    row.deleted = False
    after = (row.action, row.subject, row.time, row.room, row.teacher, row.kind,
             subgroup, False)
    if before != after:
        row.updated_at = _now_iso()
    return row


@router.post("/admin/schedule/override")
def admin_schedule_override(payload: dict = Body(...), user: User = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Создать/обновить ОДНУ правку ячейки. action: set|remove."""
    row = _apply_override_row(db, payload)
    db.commit()
    audit.log(db, actor=user.login, role="admin", action="schedule.override",
              target=f"{row.group_name} {row.day} н{row.week} п{row.pair_no} "
                     f"[{row.action}] {row.subject}")
    _post_substitution(db, row)
    return {"ok": True, "id": row.id}


def _post_substitution(db: Session, row) -> None:
    """Опубликовать правку пары в канал «Замены · Группа» (§D12).

    Целиком в try/except: расписание УЖЕ сохранено, и сбой мессенджера не имеет права
    превращать успешную правку в ошибку — то же правило, что у остальных системных
    каналов и у рассылки ДЗ."""
    try:
        from ..messenger import notify_substitution
        where = f"{row.day}, {row.pair_no}-я пара (неделя {row.week})"
        if row.action == "remove":
            text = f"❌ **{where}** — пара отменена."
        else:
            parts = [p for p in (row.subject, row.room and f"ауд. {row.room}",
                                 row.teacher, row.time) if p]
            text = f"🔁 **{where}** — теперь {', '.join(parts) or 'изменено'}."
        notify_substitution(db, row.group_name, text)
    except Exception as e:      # noqa: BLE001
        print(f"[substitution] пост о замене не опубликован: {e}")


def _post_substitutions_batch(db: Session, rows) -> None:
    """Один пост на группу по пачке правок: перечисляем изменённые пары списком."""
    try:
        from ..messenger import notify_substitution
        by_group = {}
        for row in rows:
            by_group.setdefault(row.group_name, []).append(row)
        for group, items in by_group.items():
            lines = []
            for row in sorted(items, key=lambda r: (r.week, r.day, r.pair_no)):
                where = f"{row.day}, {row.pair_no}-я пара (неделя {row.week})"
                lines.append(f"• ❌ {where} — отменена" if row.action == "remove"
                             else f"• 🔁 {where} — {row.subject or 'изменено'}")
            notify_substitution(db, group,
                                "**Изменения в расписании:**\n" + "\n".join(lines))
    except Exception as e:      # noqa: BLE001
        print(f"[substitution] пост о заменах не опубликован: {e}")


@router.post("/admin/schedule/overrides")
def admin_schedule_overrides(payload: dict = Body(...), user: User = Depends(require_admin),
                             db: Session = Depends(get_db)):
    """Пачка правок из ЧЕРНОВИКА редактора — одной транзакцией.

    Редактор копит переносы/правки локально и шлёт их сюда по кнопке «Сохранить». Либо
    применяется всё, либо ничего: любая невалидная правка бросает 400 ДО commit, и сессия
    закрывается без записи — половинчатого сохранения расписания не бывает."""
    items = payload.get("overrides")
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "overrides: непустой список правок")
    if len(items) > 500:
        raise HTTPException(400, "слишком много правок за раз")
    ids, rows = [], []
    for it in items:
        if not isinstance(it, dict):
            raise HTTPException(400, "каждая правка должна быть объектом")
        row = _apply_override_row(db, it)
        ids.append(row.id)
        rows.append(row)
    db.commit()
    #В канал «Замены» из пачки уходит ОДИН пост на группу, а не по посту на ячейку:
    #админ правит расписание сразу на неделю, и поячеечная рассылка была бы спамом,
    #после которого канал просто замьютят — вместе с действительно важными заменами.
    _post_substitutions_batch(db, rows)
    groups = sorted({(it.get("group") or "").strip() for it in items if it.get("group")})
    audit.log(db, actor=user.login, role="admin", action="schedule.override",
              target=f"пачка {len(ids)} правок: {', '.join(groups)}")
    return {"ok": True, "count": len(ids), "ids": ids}


@router.post("/admin/schedule/refresh")
def admin_schedule_refresh(group: str = Query(""), all_: bool = Query(False, alias="all"),
                           user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """«Взять расписание с ВСГУТУ» — форс-обновление кэша портала (сервер держит его 3 ч).

    Обновляется ОСНОВА, поверх которой лежат правки; сами правки это не трогает (для их
    удаления есть /reset). all=1 — пересобрать полный снимок (нужен расписаниям
    преподавателей): помечаем кэш протухшим и запускаем сборку В ФОНЕ, ~68 GET блокировать
    запрос нельзя (одноядерный VPS)."""
    from ... import schedule_web
    if all_:
        schedule_web.invalidate_all()
        _snap, building = schedule_web.full_state()   #стартует фоновую пересборку
        audit.log(db, actor=user.login, role="admin", action="schedule.refresh",
                  target="ВСЕ группы")
        return {"ok": True, "all": True, "building": building}
    g = (group or "").strip()
    if not g:
        raise HTTPException(400, "Нужна group или all=1")
    data = schedule_web.get_group(g, force=True)
    audit.log(db, actor=user.login, role="admin", action="schedule.refresh", target=g)
    return {"ok": True, "group": g, "available": bool(data and data.get("weeks"))}


@router.post("/admin/schedule/reset")
def admin_schedule_reset(group: str = Query(""), all_: bool = Query(False, alias="all"),
                         user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Сброс правок: расписание снова берётся с портала как есть.

    ⚠️ ScheduleOverride СИНКУЕТСЯ, поэтому правки не удаляем физически, а помечаем
    надгробиями (deleted=True + свежий updated_at) — иначе на десктопе они воскреснут при
    следующем pull. all=1 РАЗРУШИТЕЛЕН: стирает ВСЕ ручные правки колледжа безвозвратно
    (UI обязан спросить подтверждение)."""
    q = db.query(ScheduleOverride).filter(ScheduleOverride.deleted == False)  # noqa: E712
    if not all_:
        g = (group or "").strip()
        if not g:
            raise HTTPException(400, "Нужна group или all=1")
        q = q.filter(ScheduleOverride.group_name == g)
    rows = q.all()
    now = _now_iso()
    for r in rows:
        r.deleted = True
        r.updated_at = now
    db.commit()
    audit.log(db, actor=user.login, role="admin", action="schedule.reset",
              target="ВСЕ группы" if all_ else (group or ""),
              detail=f"снято правок: {len(rows)}")
    return {"ok": True, "reset": len(rows), "all": all_}


@router.get("/admin/schedule/slot-conflicts")
def admin_slot_conflicts(group: str = Query(...), week: int = Query(...),
                         day: str = Query(...), pair_no: int = Query(...),
                         room: str = Query(""), teacher: str = Query(""),
                         subject: str = Query(""),
                         user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Накладки конкретного слота при переносе пары — для подсветки сразу после drag-drop.

    Проверяются ПРЕДЛОЖЕННЫЕ (ещё не сохранённые) аудитория/преподаватель против других
    групп. building=true → снимок портала ещё собирается, проверка неполна."""
    from ... import schedule_conflicts
    return schedule_conflicts.slot_conflicts(db, group, week, day, pair_no,
                                             room=room, teacher=teacher, subject=subject)


@router.delete("/admin/schedule/override/{ov_id:path}")
def admin_schedule_override_delete(ov_id: str, user: User = Depends(require_admin),
                                   db: Session = Depends(get_db)):
    """Убрать правку (ячейка вернётся к тому, что даёт портал)."""
    row = db.get(ScheduleOverride, ov_id)
    if row and not row.deleted:
        group = row.group_name
        day = row.day
        row.deleted = True
        row.updated_at = _now_iso()
        db.commit()
        audit.log(db, actor=user.login, role="admin", action="schedule.override",
                  target=f"удалена правка #{ov_id}")
    return {"ok": True}


# ── Сверка расписаний: накладки и совместные пары ────────────────────────────────────
@router.get("/admin/schedule/conflicts")
def admin_schedule_conflicts(user: User = Depends(require_admin),
                             db: Session = Depends(get_db)):
    """Накладки: один преподаватель (или аудитория) в одном слоте у разных групп.

    ⚠️ `building=true` означает «полный снимок портала ещё собирается», а НЕ «накладок
    нет». Клиент обязан показывать это разными состояниями: пустой список при
    незавершённой сборке — не повод сообщать составителю, что всё чисто."""
    from ... import schedule_conflicts
    return schedule_conflicts.find_conflicts(db)


@router.post("/admin/schedule/joint")
def admin_schedule_joint_set(payload: dict = Body(...), user: User = Depends(require_admin),
                             db: Session = Depends(get_db)):
    """Пометить слот как СОВМЕСТНУЮ пару — законное совпадение, а не ошибка.

    Ключ детерминированный, поэтому повторная пометка того же слота заменяет прежнюю и
    дублей не создаёт."""
    kind = (payload.get("kind") or "teacher").strip()
    if kind not in ("teacher", "room"):
        raise HTTPException(status_code=400, detail="kind: teacher или room")
    value = (payload.get("value") or "").strip()
    day = (payload.get("day") or "").strip()
    if not value or not day:
        raise HTTPException(status_code=400, detail="Нужны value и day")
    try:
        week = int(payload.get("week") or 0)
        pair_no = int(payload.get("pair_no") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="week и pair_no — числа") from None

    mid = joint_mark_id(kind, week, day, pair_no, value)
    row = db.get(ScheduleJointMark, mid)
    if row is None:
        row = ScheduleJointMark(id=mid, created_at=_now_iso(), created_by=user.login or "")
        db.add(row)
    row.kind, row.week, row.day, row.pair_no = kind, week, day, pair_no
    row.value = value
    row.note = (payload.get("note") or "").strip()[:500]
    db.commit()
    audit.log(db, actor=user.login, role="admin", action="schedule.joint",
              target=f"{kind} {value}", detail=f"неделя {week}, {day}, пара {pair_no}")
    return {"ok": True, "id": mid}


@router.delete("/admin/schedule/joint/{mark_id:path}")
def admin_schedule_joint_delete(mark_id: str, user: User = Depends(require_admin),
                                db: Session = Depends(get_db)):
    """Снять отметку «совместная пара» — слот снова начнёт считаться накладкой."""
    row = db.get(ScheduleJointMark, mark_id)
    if row is not None:
        db.delete(row)
        db.commit()
        audit.log(db, actor=user.login, role="admin", action="schedule.joint",
                  target=f"снята отметка #{mark_id}")
    return {"ok": True}


@router.post("/admin/schedule/publish")
def admin_schedule_publish(payload: dict = Body(...), user: User = Depends(require_admin),
                           db: Session = Depends(get_db)):
    """Разослать уведомление об изменении расписания ГРУППЫ.

    Почему отдельная кнопка, а не автоматическая рассылка на каждую правку ячейки:
    админ правит расписание десятками ячеек подряд, и «правка = уведомление» означало бы
    три десятка пушей студенту за минуту. После такого уведомления отключают, и мы
    теряем канал целиком — включая действительно важные сообщения об оценках.

    Адресаты (решение Влада): студенты ЭТОЙ группы и преподаватели, ведущие у неё. Всему
    колледжу об изменении одной группы знать незачем — это и шум, и лишние сведения о
    чужих группах."""
    group = (payload.get("group") or "").strip()
    if not group:
        raise HTTPException(status_code=400, detail="Нужна group")

    students = db.query(User).filter(
        User.role == "student", User.group_name == group,
        User.deleted == False).all()  # noqa: E712
    #Преподаватель считается ведущим у группы, если ему НАЗНАЧЕН предмет этой группы
    #(SubjectHours.teacher_id) — не «есть занятия по совпавшему названию предмета где-то».
    ty, ts = W.current_term(W.load_config(db))
    teacher_ids = {r.teacher_id for r in db.query(SubjectHours).filter(
        SubjectHours.group_name == group, SubjectHours.year == ty,
        SubjectHours.semester == ts, SubjectHours.teacher_id != "",
        SubjectHours.deleted == False).all()}  # noqa: E712
    teachers = [t for t in db.query(User).filter(
        User.role == "teacher", User.deleted == False).all()  # noqa: E712
        if t.login and t.id in teacher_ids]

    from ... import rustore_push
    sent = 0
    for person, role in ([(s, "student") for s in students]
                         + [(t, "teacher") for t in teachers]):
        if not person.login:
            continue        #без логина уведомлять некого (внешний ростер преподавателя)
        rustore_push.notify_schedule_changed(db, person.login, role=role, group=group)
        sent += 1
    #§D12: тот же факт — постом в канал «Расписание · Группа» (мессенджер). Изолировано
    #try/except: сбой мессенджера не должен мешать основной рассылке пушей выше.
    channel_id = ""
    try:
        from ..messenger import ensure_group_schedule_channel, _post_system_channel_message
        channel_id = ensure_group_schedule_channel(db, group, [s.id for s in students])
        _post_system_channel_message(
            db, channel_id, f"⚠️ Расписание группы **{group}** изменилось — проверьте актуальные пары.")
    except Exception:
        pass
    audit.log(db, actor=user.login, role="admin", action="schedule.publish",
              target=group, detail=f"уведомлено: {sent}")
    #conversation_id отдаём наружу, чтобы клиент мог перейти в канал, а тест — адресовать
    #беседу, не собирая id вручную (у групп со слэшем ручная сборка и прятала дефект).
    return {"ok": True, "notified": sent, "conversation_id": channel_id,
            "students": len(students), "teachers": len(teachers)}
