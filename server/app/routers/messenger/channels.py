"""
channels.py — Системные каналы (практика, объявления, отчёты куратора) и сами отчёты
куратора для родителей (§5.5).

Часть пакета `routers/messenger` (разрез 3.7.7). Общий роутер, проверки прав и
сборка ответов — в `_common.py`; порядок регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — роутеры, модели, хелперы


@router.post("/channels/practice/{group_name}")
def ensure_practice_channel(group_name: str, user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """§D12(5): «Практика · Группа» — канал производственной практики.

    В отличие от остальных системных каналов он НЕ автоматический: данных о практике в
    журнале нет, и выдумывать их нельзя. Это канал, который ведёт руками учебная часть
    (админ) или куратор группы — направления, договоры, сроки сдачи дневника. От обычного
    канала отличается тем, что появляется у студентов сам и его нельзя покинуть."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Доступно преподавателям и администрации")
    group_name = group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="Нужна группа")
    #Куратор ведёт практику только своих групп; администрация — любых.
    if user.role == "teacher" and group_name not in (user.curated_groups or []):
        raise HTTPException(status_code=403, detail="Эта группа вами не курируется")
    students = [u.id for u in db.query(User).filter(
        User.role == "student", User.group_name == group_name,
        User.deleted == False).all()]  # noqa: E712
    writers = [user.id]
    if user.role != "admin":
        writers += [a.id for a in db.query(User).filter(
            User.role == "admin", User.deleted == False).all()]  # noqa: E712
    conv_id = f"sys:practice:{_gtoken(group_name)}"
    _ensure_system_channel(db, conv_id, f"Практика · {group_name}",
                           "Производственная практика: направления, сроки, документы.",
                           reader_ids=students, writer_ids=writers)
    return {"ok": True, "conversation_id": conv_id}


@router.get("/my-groups")
def my_groups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Группы, которые сотрудник может адресовать в мессенджере (объявления, отчёты).

    Нужен для ВЫПАДАЮЩЕГО СПИСКА вместо ручного ввода: имена групп колледжа вида «К75/1»
    набирали с ошибкой (лишний пробел, латинская «K»), канал не находился, и со стороны
    это выглядело как «не работает». Флаг `curated` отличает курируемые группы —
    отчёты для родителей доступны только по ним."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Доступно преподавателям и администрации")
    curated = set(user.curated_groups or [])
    known = [g.name for g in db.query(Group)
             .filter(Group.deleted == False).order_by(Group.name).all()]  # noqa: E712
    if user.role == "admin":
        names = known
    else:
        #Преподаватель: НАЗНАЧЕННЫЕ ему группы (не любые с совпавшим предметом) + курируемые.
        from ... import webdata as W
        ty, ts = W.current_term(W.load_config(db))
        names = sorted(set(W.teacher_group_names(db, user.id, ty, ts)) | curated)
    #Одна и та же группа могла записаться по-разному («К74/1» в занятиях и «к74/1» в
    #кураторстве) — в списке она двоилась. Схлопываем по регистру и пробелам, показывая
    #написание из СПРАВОЧНИКА групп: журнал ключуется именно им.
    canon = {n.strip().lower(): n for n in known}
    out, seen = [], set()
    for n in names:
        key = (n or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        name = canon.get(key, n)
        out.append({"name": name, "curated": key in {c.strip().lower() for c in curated}})
    return {"groups": out}


@router.post("/channels/announcements")
def ensure_announcements_channel_q(group: str = Query(...),
                                   user: User = Depends(get_current_user),
                                   db: Session = Depends(get_db)):
    """То же, что ниже, но имя группы — в QUERY, а не в пути.

    Причина ровно та же, что у /web/curator/subjects: имена групп содержат слэш («К75/1»),
    в пути он приезжает как %2F, Starlette декодирует его обратно в «/», и роут с одним
    сегментом перестаёт совпадать — эндпоинт молча 404-ил."""
    return ensure_announcements_channel(group, user, db)


@router.post("/channels/announcements/{group_name}")
def ensure_announcements_channel(group_name: str, user: User = Depends(get_current_user),
                                 db: Session = Depends(get_db)):
    """§D12(2): «Объявления · Группа» — teacher/admin открывают/создают канал (студенты
    группы — читатели, преподаватели этой группы — авторы) и дальше публикуют ОБЫЧНЫМ
    send_message (это простой kind='channel', отдельного эндпоинта «отправить объявление»
    не требуется — переиспользуем всю уже готовую инфраструктуру постинга в канал)."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Доступно преподавателям и администрации")
    group_name = group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="Нужна группа")
    students = [u.id for u in db.query(User).filter(
        User.role == "student", User.group_name == group_name, User.deleted == False).all()]  # noqa: E712
    #Авторы канала — преподаватели, которым НАЗНАЧЕНА эта группа (не «есть занятие с
    #совпавшим названием предмета где-то ещё»), см. §ролей teacher_assignments.
    from ... import webdata as W
    ty, ts = W.current_term(W.load_config(db))
    teacher_ids_here = {r.teacher_id for r in db.query(SubjectHours).filter(
        SubjectHours.group_name == group_name, SubjectHours.year == ty,
        SubjectHours.semester == ts, SubjectHours.teacher_id != "",
        SubjectHours.deleted == False).all()}  # noqa: E712
    teachers = [t.id for t in db.query(User).filter(
        User.role == "teacher", User.deleted == False).all()  # noqa: E712
        if t.id in teacher_ids_here]
    if user.role == "teacher" and user.id not in teachers:
        teachers.append(user.id)     #админ мог создать канал раньше, чем завёл занятия
    conv_id = f"sys:announce:{_gtoken(group_name)}"
    conv = _ensure_system_channel(db, conv_id, f"Объявления · {group_name}",
                                  "Объявления от преподавателей и администрации.",
                                  reader_ids=students, writer_ids=teachers)
    #Уже существующий канал: если пользователь — преподаватель этой группы и ещё не писатель,
    #добавляем (группа могла завести предметы уже ПОСЛЕ создания канала).
    if user.role == "teacher" and _participant(db, conv_id, user.id) is None:
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                       role="writer", joined_at=_now()))
        db.commit()
    return {"conversation_id": conv.id, "kind": "channel", "title": conv.title}


@router.post("/channels/curator-reports")
def ensure_curator_reports_channel_q(group: str = Query(...),
                                     user: User = Depends(get_current_user),
                                     db: Session = Depends(get_db)):
    """Имя группы в QUERY — см. пояснение у ensure_announcements_channel_q (слэш в «К75/1»)."""
    return ensure_curator_reports_channel(group, user, db)


@router.post("/channels/curator-reports/{group_name}")
def ensure_curator_reports_channel(group_name: str, user: User = Depends(get_current_user),
                                   db: Session = Depends(get_db)):
    """§12: канал «Отчёты · Группа» — куратор публикует туда `/отчет`, читают студенты
    группы И её активные родители. ТОЛЬКО куратор ЭТОЙ группы (curated_groups) и ТОЛЬКО
    если у группы есть хоть один активный родитель — без родителей отчёт для родителей
    не имеет смысла заводить."""
    group_name = group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="Нужна группа")
    if user.role != "teacher" or group_name not in (user.curated_groups or []):
        raise HTTPException(status_code=403, detail="Доступно только куратору этой группы")
    parent_ids = _active_parent_ids_for_group(db, group_name)
    if not parent_ids:
        raise HTTPException(status_code=400, detail="У группы нет ни одной активной связи с родителем")
    students = [u.id for u in db.query(User).filter(
        User.role == "student", User.group_name == group_name,
        User.deleted == False).all()]  # noqa: E712
    conv_id = f"sys:curator_reports:{_gtoken(group_name)}"
    conv = _ensure_system_channel(db, conv_id, f"Отчёты · {group_name}",
                                  "Отчёты об успеваемости группы для родителей.",
                                  reader_ids=students + parent_ids, writer_ids=[user.id])
    return {"conversation_id": conv.id, "kind": "channel", "title": conv.title}


@router.post("/curator-reports")
def create_curator_report(payload: dict = Body(...), user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Создать отчёт по группе и отправить его СООБЩЕНИЕМ — в личные чаты родителей
    (`to_user_ids`), в конкретные беседы (`to_conversation_ids`) или, если не указано
    ничего, себе в «Избранное», откуда его можно переслать кому угодно.

    Кнопку отчёта можно пересылать: доступ даёт участие в ЛЮБОЙ беседе, где она лежит
    (см. _require_report_access), а не только в исходной."""
    group_name = (payload.get("group") or "").strip()
    allowed = _report_groups_for(db, user)
    if not allowed:
        raise HTTPException(status_code=403,
                            detail="Отчёт по группе выпускает её куратор или администрация")
    if group_name not in allowed:
        raise HTTPException(status_code=403, detail="Эта группа вами не курируется")
    _guard_can_write(db, user)                       #мьют/анти-флуд — как у обычной отправки

    conv_ids = []
    for uid in [str(x) for x in (payload.get("to_user_ids") or [])]:
        peer = db.query(User).filter(User.id == uid, User.deleted == False).first()  # noqa: E712
        if peer is None or peer.id == user.id:
            continue
        _guard_direct_allowed(db, user, peer)        #те же границы, что у обычной переписки
        conv_ids.append(_ensure_direct(db, user, peer))
    for cid in [str(x) for x in (payload.get("to_conversation_ids") or [])]:
        part = _participant(db, cid, user.id)
        if part is None:
            continue                                 #в чужую беседу отчёт не положишь
        conv = _conversation(db, cid)
        if conv.kind == "channel" and part.role not in _WRITER_ROLES:
            continue
        conv_ids.append(cid)
    if not conv_ids:
        #Ничего не выбрано — кладём себе в «Избранное»: отчёт создан, дальше его пересылают.
        conv_ids = [_ensure_saved(db, user)]

    seen, targets = set(), []
    for cid in conv_ids:
        if cid not in seen:
            seen.add(cid)
            targets.append(cid)
    m = _create_report(db, group_name, user, targets)
    return {"ok": True, "report_id": m.body, "message_id": m.id,
            "conversation_id": targets[0], "conversation_ids": targets}


@router.get("/report-recipients")
def report_recipients(group: str = Query(...), user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Кому предложить отчёт по группе: родители с ПОДТВЕРЖДЁННОЙ связью (личные чаты) и
    уже существующие беседы группы (канал отчётов, чат родителей). Список — подсказка для
    диалога отправки; права всё равно проверяются при создании отчёта."""
    group = group.strip()
    allowed = _report_groups_for(db, user)
    if group not in allowed:
        raise HTTPException(status_code=403, detail="Эта группа вами не курируется")
    parent_ids = _active_parent_ids_for_group(db, group)
    onl = _online_logins()
    parents = [_safe_user(p, onl) for p in db.query(User)
               .filter(User.id.in_(parent_ids)).order_by(User.surname, User.name).all()] \
        if parent_ids else []
    #Беседы, которые уместно предложить: системные каналы этой группы + групповые чаты,
    #где куратор состоит (чат родителей он заводит сам обычной «Новой группой»).
    convs = []
    for p in db.query(ConversationParticipant).filter(
            ConversationParticipant.user_id == user.id).all():
        conv = db.query(Conversation).filter(Conversation.id == p.conversation_id).first()
        if conv is None or conv.kind not in ("group", "channel"):
            continue
        if conv.kind == "channel" and p.role not in _WRITER_ROLES:
            continue
        if conv.is_system and not conv.id.endswith(f":{_gtoken(group)}"):
            continue                                 #чужой группы системный канал не предлагаем
        convs.append({"conversation_id": conv.id, "title": conv.title or "",
                      "kind": conv.kind, "system": bool(conv.is_system)})
    convs.sort(key=lambda c: (not c["system"], c["title"]))
    return {"parents": parents, "conversations": convs}


@router.get("/reports/{report_id}")
def report_overview(report_id: str, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """§12: данные для оверлея отчёта — круговая (категории успеваемости) + плоские
    (проценты по предметам) диаграммы. Живой пересчёт (curator_report.collect_group),
    ограниченный ГРАНИЦЕЙ отчёта (термин + дата создания включительно) — числа могут
    чуть измениться, если позже поправят оценку ВНУТРИ этой границы, но сама граница
    «вечна» и не сдвигается новыми занятиями (см. CuratorReport в models.py)."""
    rep = db.query(CuratorReport).filter(CuratorReport.id == report_id).first()
    if rep is None:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    _require_report_access(db, rep, user)   #участник ЛЮБОЙ беседы, где лежит эта кнопка
    from ... import webdata as W
    from ... import curator_report as CR
    cfg = W.load_config(db)
    data = CR.collect_group(db, rep.group_name, rep.year, rep.semester, cfg,
                           cutoff_date=rep.cutoff_date)
    categories = CR.categorize(data["rows"])
    subjects = [{"subject": s, "avg": data["subject_group_avg"].get(s) or 0,
                "percent": round(((data["subject_group_avg"].get(s) or 0) / 5) * 100)}
               for s in data["subjects"]]
    return {"id": rep.id, "seq": rep.seq, "group": rep.group_name,
            "year": rep.year, "semester": rep.semester, "cutoff_date": rep.cutoff_date,
            "archived": _report_archived(rep, db), "students": data["students"],
            "group_avg": data["group_avg"], "categories": categories, "subjects": subjects}


@router.get("/reports/{report_id}/subject")
def report_subject_journal(report_id: str, subject: str = Query(...),
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """§12: дрилл-даун по предмету — журнал студентов группы (оценки построчно), справа
    средний балл и пропуски: часов пропущено и (в скобках) количество пропусков в
    единицах — т.е. сколько раз стояло «Н» (неявка), без учёта «Б» (болезнь).
    «О» (опоздание, 3.7.6) в пропуски не входит вовсе — студент был на занятии."""
    rep = db.query(CuratorReport).filter(CuratorReport.id == report_id).first()
    if rep is None:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    _require_report_access(db, rep, user)
    from ... import webdata as W
    from ... import curator_report as CR
    cfg = W.load_config(db)
    students = W.students_in_group(db, rep.group_name)
    lessons = W.group_lessons(db, rep.group_name, subject=subject,
                             year=rep.year, semester=rep.semester)
    cutoff = CR.parse_ddmmyyyy(rep.cutoff_date) if rep.cutoff_date else None
    if cutoff:
        lessons = [l for l in lessons
                  if (CR.parse_ddmmyyyy(l.date) or cutoff) <= cutoff]
    lessons.sort(key=lambda l: (l.number, l.hour))
    scale_map = W.lesson_scale_map(db, lessons)
    rows = []
    for s in students:
        recs = W.student_records(db, s.surname, s.name, rep.group_name)
        grades = [{"lesson_id": l.id, "type": l.type, "number": l.number,
                  "topic": l.topic, "date": l.date, "value": recs.get(l.id, "")}
                 for l in lessons]
        absc = W.absences(lessons, recs)
        rows.append({
            "student": f"{s.surname} {s.name}".strip(),
            "grades": grades,
            "average": W.average(lessons, recs, cfg, scale=scale_map),
            "missed_hours": absc["всего"], "missed_count": absc["Н"],
        })
    return {"group": rep.group_name, "subject": subject,
            "lessons": [{"id": l.id, "type": l.type, "number": l.number,
                        "topic": l.topic, "date": l.date} for l in lessons],
            "rows": rows}
