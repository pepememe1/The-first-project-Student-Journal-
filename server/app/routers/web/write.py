"""
write.py — ЗАПИСЬ (Phase B): оценки и занятия преподавателя, CRUD администратора.

Часть пакета `routers/web` (разрезан в 3.6: один файл на 4288 строк правили
62 коммита за полгода — он и был главным источником конфликтов при
одновременной работе). Общий роутер и хелперы — в `_common.py`; порядок
регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — общий router, модели, хелперы
#Риск отчисления пересчитывается хвостом простановки оценки. Импорт односторонний
#(curator НЕ импортирует write), поэтому цикла нет.
from .curator import _maybe_notify_dropout_risk      # noqa: F401


# ЗАПИСЬ (Phase B) ─────────────────────────────────────────────────────────────────
# Веб теперь не только читает. Пишем в ТЕ ЖЕ таблицы (grades/users/groups) и в ТОМ ЖЕ
# формате id, что и синк десктопа (sync_engine), поэтому десктоп подхватывает правки
# обычным pull. Метку времени для LWW ставит СЕРВЕР (инвариант §3), а не часы клиента.


@router.post("/teacher/grade")
def teacher_set_grade(payload: dict = Body(...),
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Преподаватель выставляет/меняет/снимает оценку. id грейда = «f|n|lesson_id»
    (как в sync_engine) → десктоп получит её через pull. Пустой grade = снять оценку
    (надгробие). Пишем только по СВОЕМУ предмету и студенту своей группы (row-level)."""
    _require("teacher", user)
    surname = (payload.get("surname") or "").strip()
    name = (payload.get("name") or "").strip()
    lesson_id = (payload.get("lesson_id") or "").strip()
    value = (payload.get("grade") or "").strip()
    if not (surname and name and lesson_id):
        raise HTTPException(status_code=400, detail="Нужны surname, name и lesson_id")
    #Пересдачи экзаменов пишутся с суффиксом (<id>_retake[_N]) — как в десктопе. Права
    #и группу проверяем по БАЗОВОМУ занятию, ключ оценки сохраняем полным.
    base_id = re.sub(r"_retake(_\d+)?$", "", lesson_id)
    lesson = db.query(Lesson).filter(
        Lesson.id == base_id, Lesson.deleted == False).first()  # noqa: E712
    if not lesson:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    _teacher_check_assignment(db, user, lesson.group_name, lesson.subject,
                              lesson.year, lesson.semester)   #только своё назначение
    _ensure_current_term(W.load_config(db), lesson)   #архив прошлых семестров — read-only
    stud = db.query(User).filter(
        User.role == "student", User.surname == surname, User.name == name,
        User.group_name == lesson.group_name, User.deleted == False).first()  # noqa: E712
    if not stud:
        raise HTTPException(status_code=400, detail="Студент не найден в группе занятия")
    from ...models import grade_id as _grade_key
    gid = _grade_key(stud.id, lesson_id)   #ЭТАП 3: ключ по неизменяемому id студента
    now = _now_iso()
    cleared = (value == "")
    row = db.get(Grade, gid)
    #Прежнее значение запоминаем ДО перезаписи — по нему отличаем «поставили впервые»
    #от «исправили». Ранее СНЯТАЯ оценка (надгробие) прежним значением не считается:
    #иначе простановка балла после снятия выглядела бы как исправление.
    previous = "" if (row is None or row.deleted) else (row.grade or "")
    if row is None:
        row = Grade(id=gid, student_f=surname, student_n=name, lesson_id=lesson_id)
        db.add(row)
    row.grade = value
    row.device = "web"
    row.updated_at = now
    row.deleted = cleared
    #Этап 1 миграции: рядом с ФИО-ключом кладём неизменяемый id студента. Студент уже
    #найден выше (проверка «состоит в группе занятия»), так что это бесплатно.
    row.student_id = stud.id
    db.commit()
    #Пуш студенту. СНЯТИЕ оценки не уведомляем: «у вас новая оценка» при её удалении —
    #прямая дезинформация. Ошибки внутри не всплывают: сбой доставки не должен мешать
    #преподавателю поставить балл.
    #Повторное сохранение ТОГО ЖЕ балла молчит: ничего не изменилось, а лишнее
    #уведомление приучает отключать уведомления вовсе.
    if not cleared and stud.login and previous != value:
        from ... import rustore_push
        if previous:
            rustore_push.notify_grade_changed(db, stud.login, subject=lesson.subject,
                                              lesson_id=lesson_id,
                                              old=previous, new=value)
        else:
            rustore_push.notify_new_grade(db, stud.login, subject=lesson.subject,
                                          lesson_id=lesson_id, value=value)
        #§D12: тот же факт — постом в личный канал «Мои оценки» (мессенджер). Отдельная
        #подсистема от пуша выше; сбой здесь НИКОГДА не должен мешать выставлению оценки.
        try:
            from ..messenger import notify_grade_posted
            notify_grade_posted(db, stud.id, user.full_name or user.name or user.login,
                               lesson.subject, value)
        except Exception:
            pass
    #Риск отчисления (3.6): пересчитываем ПОСЛЕ любой правки оценки — в том числе при
    #снятии (снятая двойка риск снижает, и запомнить это надо, иначе следующий рост не
    #посчитается новостью). Как и хуки выше — best-effort, ошибка не роняет простановку.
    try:
        _maybe_notify_dropout_risk(db, stud, lesson.group_name)
    except Exception:
        db.rollback()
    audit.log(db, actor=user.login, role=user.role,
              action="grade.clear" if cleared else "grade.set",
              target=f"{surname} {name}",
              detail=f"{lesson.subject} · {lesson_id}" + ("" if cleared else f" = {value}"))
    return {"ok": True, "id": gid, "grade": value, "deleted": cleared, "updated_at": now}


# --- Занятия (CRUD) --- id = str(uuid4), как создаёт десктоп (core.GradeBook) →
# десктоп подхватывает занятия pull'ом. Преподаватель ведёт только СВОИ предметы.
@router.post("/teacher/lesson")
def teacher_create_lesson(payload: dict = Body(...),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Создать занятие (пару). Номер, если не передан, — следующий по типу в этом
    журнале (как авто-нумерация в десктопе).

    `subgroup` (§ролей, 3.6.1) — 0 (по умолчанию, «Совместно»/предмет не разделён), 1
    или 2. На РАЗДЕЛЁННОМ предмете преподаватель может создавать занятие только для
    подгруппы, которую реально ведёт (0/«Совместно» — только если ведёт ОБЕ, см.
    webdata.teacher_owned_subgroups); на НЕразделённом subgroup всегда 0, что бы ни
    прислал клиент — там подгрупп попросту нет."""
    _require("teacher", user)
    group = (payload.get("group") or "").strip()
    subject = (payload.get("subject") or "").strip()
    ltype = (payload.get("type") or "").strip()
    if not (group and subject and ltype):
        raise HTTPException(status_code=400, detail="Нужны group, subject и type")
    #Новое занятие всегда в ТЕКУЩЕМ учебном периоде (штампуем год+семестр) — тем же
    #термином и проверяем назначение.
    ty, ts = W.current_term(W.load_config(db))
    _teacher_check_assignment(db, user, group, subject, ty, ts)

    sh_row = W.subject_hours_row(db, group, subject, ty, ts)
    subgroup = 0
    if sh_row and sh_row.split:
        try:
            subgroup = int(payload.get("subgroup") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="subgroup должен быть 0, 1 или 2")
        if subgroup not in (0, 1, 2):
            raise HTTPException(status_code=400, detail="subgroup должен быть 0, 1 или 2")
        owned = W.teacher_owned_subgroups(sh_row, user.id)
        if subgroup == 0 and owned != {1, 2}:
            raise HTTPException(status_code=403,
                                detail="«Совместно» доступно только тому, кто ведёт ОБЕ подгруппы")
        if subgroup in (1, 2) and subgroup not in owned:
            raise HTTPException(status_code=403, detail=f"Подгруппа {subgroup} вам не назначена")

    number = payload.get("number")
    if not number:
        number = W.next_lesson_number(db, group, subject, ltype, subgroup)
    import uuid as _uuid
    lid = str(_uuid.uuid4())
    topic = (payload.get("topic") or "").strip()
    db.add(Lesson(id=lid, group_name=group, subject=subject, type=ltype,
                  number=int(number), topic=topic,
                  date=(payload.get("date") or "").strip(),
                  retake_date=(payload.get("retake_date") or "").strip(),
                  hour=int(payload.get("hour") or 0), extra={},
                  year=ty, semester=ts, subgroup=subgroup,
                  updated_at=_now_iso(), deleted=False))
    db.commit()
    if ltype == "ДЗ":
        _notify_homework(db, group, subject, lid, topic, int(number),
                         author_login=user.login)
    return {"ok": True, "id": lid, "number": int(number), "subgroup": subgroup}


@router.post("/events")
def create_event_notification(payload: dict = Body(...),
                              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Мероприятие/событие (олимпиада, конкурс, выступление и т.п.) — рассылается
    выбранной аудитории уведомлением (вкладка «Мероприятия», см. NotificationsInbox.vue).
    Автор выбирает аудиторию при создании: `groups: []` — вся коллегия (ТОЛЬКО админ,
    у преподавателя слишком широкий охват для одной кнопки), непустой список — те
    группы (у преподавателя — не любые: только назначенные ему группы, W.teacher_
    assignments — тот же принцип ролевого скоупа, что и везде в приложении)."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Доступно преподавателям и администрации")
    title = (payload.get("title") or "").strip()[:150]
    body = (payload.get("body") or "").strip()[:2000]
    if not title or not body:
        raise HTTPException(status_code=400, detail="Укажите заголовок и текст")
    groups = [g.strip() for g in (payload.get("groups") or []) if (g or "").strip()]
    if user.role == "teacher":
        ty1, ts1 = W.current_term(W.load_config(db))
        allowed = set(W.teacher_group_names(db, user.id, ty1, ts1))
        if not groups:
            raise HTTPException(status_code=400, detail="Преподаватель должен выбрать группу(ы)")
        bad = [g for g in groups if g not in allowed]
        if bad:
            raise HTTPException(status_code=403, detail=f"Недоступные группы: {', '.join(bad)}")
    targets = []
    seen = set()
    if groups:
        for g in groups:
            for stud in W.students_in_group(db, g):
                if stud.login and stud.login not in seen:
                    seen.add(stud.login)
                    targets.append(stud)
    else:
        targets = (db.query(User)
                   .filter(User.role == "student", User.deleted == False).all())  # noqa: E712
    #Одна метка на всю рассылку: письмо ложится строкой на каждого получателя, и без неё
    #вкладка «Отправленные» не смогла бы отличить одно объявление на 30 человек от
    #тридцати разных (см. NotifyEvent.batch_id).
    import uuid
    batch = str(uuid.uuid4())
    sent = 0
    for stud in targets:
        if not stud.login:
            continue
        try:
            from ... import rustore_push
            rustore_push.notify_event(db, stud.login, title, body,
                                      author_login=user.login, batch_id=batch)
            sent += 1
        except Exception as e:      # noqa: BLE001 — рассылка не должна ронять запрос
            print(f"[events] не удалось уведомить {stud.login}: {e}")
    return {"ok": True, "sent": sent, "recipients": len(targets), "batch_id": batch}


@router.get("/events/sent")
def list_sent_notifications(limit: int = 50,
                            user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """Что Я разослал: одна строка на РАССЫЛКУ, а не на получателя.

    Доступно только тем, кто в принципе может отправлять (преподаватель/админ) — у
    студента раздел не имел бы смысла, и лишняя пустая вкладка хуже её отсутствия.

    Видно ровно СВОИ рассылки: письма коллеги — это его переписка с его группами, а не
    общая сводка (тот же ролевой скоуп, что и везде). Админ тоже видит только свои: для
    надзора есть аудит, а не чужая вкладка «Отправленные».

    Автоматические письма (оценка, расписание) сюда не попадают по построению: у них
    `author_login` пуст, автора-человека у них нет."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Доступно преподавателям и администрации")
    rows = (db.query(NotifyEvent)
            .filter(NotifyEvent.author_login == user.login)
            .order_by(NotifyEvent.created_at.desc())
            .limit(max(1, min(limit, 200)) * 200)      #с запасом: строк на партию много
            .all())
    #Схлопываем по партии В PYTHON, а не в SQL: нужен и счётчик получателей, и сколько из
    #них ПРОЧИТАЛО — на SQLite это два разных агрегата с group by, а объём здесь мал
    #(письма одного автора). Тем же приёмом и по той же причине собран `directory()`.
    batches: dict = {}
    for r in rows:
        #У писем до появления метки партии её нет — тогда партия это само письмо.
        key = r.batch_id or f"one:{r.id}"
        b = batches.get(key)
        if b is None:
            b = batches[key] = {
                "batch_id": r.batch_id or "", "kind": r.kind,
                "title": r.title or "", "body": r.body or "",
                "subject": r.subject or "", "created_at": r.created_at or "",
                "recipients": 0, "read": 0,
            }
        b["recipients"] += 1
        if r.read_at:
            b["read"] += 1
        #Время рассылки — самое РАННЕЕ письмо партии: рассылка на сотню человек пишется
        #не мгновенно, и по последнему письму дата уехала бы.
        if r.created_at and r.created_at < b["created_at"]:
            b["created_at"] = r.created_at
    items = sorted(batches.values(), key=lambda x: x["created_at"], reverse=True)
    return {"items": items[:max(1, min(limit, 200))]}


def _notify_homework(db: Session, group: str, subject: str, lesson_id: str,
                     task: str, number: int, author_login: str = "") -> None:
    """Разослать студентам группы уведомление о заданном ДЗ.

    Обёрнуто в try/except целиком: занятие УЖЕ создано и закоммичено, и падение
    рассылки не имеет права превращать успешное действие преподавателя в ошибку 500.
    То же правило, что у постов в системные каналы ниже по файлу.

    `author_login` — чтобы ДЗ попало в его вкладку «Отправленные» одной строкой на всю
    группу (метка партии, см. NotifyEvent.batch_id)."""
    try:
        import uuid
        from ... import rustore_push
        batch = str(uuid.uuid4())
        for stud in W.students_in_group(db, group):
            if not stud.login:
                continue        #без логина уведомлять некого
            rustore_push.notify_homework(db, stud.login, subject=subject,
                                         lesson_id=lesson_id, task=task, number=number,
                                         author_login=author_login, batch_id=batch)
    except Exception as e:      # noqa: BLE001 — намеренно глушим любую беду рассылки
        print(f"[homework] не удалось разослать уведомления о ДЗ: {e}")


@router.put("/teacher/lesson/{lesson_id}")
def teacher_update_lesson(lesson_id: str, payload: dict = Body(...),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require("teacher", user)
    row = db.get(Lesson, lesson_id)
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    _teacher_check_assignment(db, user, row.group_name, row.subject, row.year, row.semester)
    _ensure_current_term(W.load_config(db), row)   #архив — read-only
    for field in ("topic", "date", "retake_date"):
        if field in payload:
            setattr(row, field, (payload.get(field) or "").strip())
    #Даты пересдач №2+ живут в extra (как в десктопе: retake_date_2..5).
    extra_changed = False
    extra = dict(row.extra or {})
    for n in range(2, 6):
        k = f"retake_date_{n}"
        if k in payload:
            extra[k] = (payload.get(k) or "").strip()
            extra_changed = True
    if extra_changed:
        row.extra = extra
    if "number" in payload and payload["number"]:
        row.number = int(payload["number"])
    if "hour" in payload:
        row.hour = int(payload.get("hour") or 0)
    row.updated_at = _now_iso()
    db.commit()
    return {"ok": True, "id": lesson_id}


@router.delete("/teacher/lesson/{lesson_id}")
def teacher_delete_lesson(lesson_id: str,
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Мягкое удаление занятия (надгробие) — доедет до десктопа и скроет колонку."""
    _require("teacher", user)
    row = db.get(Lesson, lesson_id)
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    _teacher_check_assignment(db, user, row.group_name, row.subject, row.year, row.semester)
    _ensure_current_term(W.load_config(db), row)   #архив — read-only
    row.deleted = True
    row.updated_at = _now_iso()
    db.commit()
    return {"ok": True, "id": lesson_id}


@router.get("/teacher/journal-export")
def teacher_journal_export(group: str = Query(...), subject: str = Query(...),
                           fmt: str = Query("xlsx"), year: str = Query(""), semester: int = Query(0),
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Экспорт журнала (fmt=xlsx|docx) за выбранный семестр. Единый стиль десктопа и
    веба: Times New Roman 14, ч/б, титульная шапка, средний по группе, адаптивная
    ширина (текст не обрезается)."""
    _require("teacher", user)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    _teacher_check_assignment(db, user, group, subject, ty, ts)
    tscale = W.teacher_scale(user)
    lessons = W.group_lessons(db, group, subject, year=ty, semester=ts)
    rows = []
    for s in W.students_in_group(db, group):
        recs = W.student_records(db, s.surname, s.name, group)
        rows.append({"surname": s.surname, "name": s.name, "records": recs,
                     "average": W.average(lessons, recs, cfg, scale=tscale)})
    if fmt == "docx":
        from ... import docx_export
        data = docx_export.build_journal_docx(group, subject, lessons, rows)
    else:
        from ... import xlsx_export
        data = xlsx_export.build_journal_xlsx(group, subject, lessons, rows)
    return _file_response(data, f"Журнал_{group}_{subject}_{ty}_{ts}", fmt)


def _compose_name(name_in: str, patronymic: str) -> tuple:
    """Возвращает (key_name, patronymic). key_name = «Имя Отчество» — это КЛЮЧ оценок
    и синка (grades.student_n, stud:surname|name|group), его формат менять нельзя.

    - отчество передано отдельным полем → собираем «имя отчество» (без дублирования,
      если имя уже оканчивается на это отчество);
    - отчество не передано, но в имени есть пробел (старый фронт прислал полную форму) →
      вычленяем отчество из хвоста, само имя-ключ оставляем как есть."""
    name_in = (name_in or "").strip()
    patronymic = (patronymic or "").strip()
    if patronymic:
        key = name_in if name_in.endswith(patronymic) else f"{name_in} {patronymic}".strip()
        return key, patronymic
    patr = name_in.split(" ", 1)[1].strip() if " " in name_in else ""
    return name_in, patr


def _ensure_group_row(db: Session, name: str):
    """Заводит группу в таблице groups, если её ещё нет (id=grp:name) — как десктоп при
    добавлении студента (_ensure_group_exists). Так группа не «висит» и уедет в десктоп."""
    name = (name or "").strip()
    if not name:
        return
    gid = f"grp:{name}"
    row = db.get(Group, gid)
    if row is None:
        db.add(Group(id=gid, name=name, subjects=[], updated_at=_now_iso(), deleted=False))
    elif row.deleted:
        row.deleted = False
        row.updated_at = _now_iso()


@router.post("/admin/students")
def admin_create_student(payload: dict = Body(...),
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Создать студента (id=stud:login, как в sync_engine). Пароль хешируется тем же
    гибридом (server.security) → вход работает и с сайта, и из десктопа. Группа
    авто-создаётся, если её ещё нет (пункт 3 на сайте)."""
    surname = (payload.get("surname") or "").strip()
    name_in = (payload.get("name") or "").strip()          #ИМЯ (или полная форма — старый фронт)
    patronymic = (payload.get("patronymic") or "").strip()  #ОТЧЕСТВО отдельным полем
    login = (payload.get("login") or "").strip()
    group = (payload.get("group") or "").strip()
    password = payload.get("password") or ""
    if not (surname and name_in):
        raise HTTPException(status_code=400, detail="Нужны фамилия и имя")
    if not login:
        raise HTTPException(status_code=400, detail="Нужен логин")
    #name = «Имя Отчество» — это КЛЮЧ оценок и синка (не меняем формат). Если отчество
    #пришло отдельным полем — собираем; если пришла полная форма без отчества — вычленяем.
    key_name, patronymic = _compose_name(name_in, patronymic)
    sid = f"stud:{login}"
    existing = db.get(User, sid)
    if existing is not None and not existing.deleted:
        raise HTTPException(status_code=409, detail="Студент с таким логином уже есть")
    _ensure_group_row(db, group)
    row = existing or User(id=sid)
    if existing is None:
        db.add(row)
    row.role = "student"
    row.login = login
    row.surname = surname
    row.name = key_name
    row.patronymic = patronymic
    row.group_name = group
    row.full_name = ""
    row.subjects = []
    row.group_assignments = {}
    if password:
        from ...security import hash_password
        row.password_hash = hash_password(password)
    row.updated_at = _now_iso()
    row.deleted = False
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="student.create",
              target=login, detail=f"{surname} {key_name} · {group}")
    return {"ok": True, "login": login, "id": sid}


def _rekey_student_grades(db: Session, old_f: str, old_n: str,
                          new_f: str, new_n: str, student_id: str = "") -> int:
    """Обновляет ФИО в строках оценок студента. Возвращает число тронутых строк.

    ЭТАП 3 миграции сильно упростил эту функцию. Раньше оценки ключевались по ФИО, и
    переименование означало ПЕРЕНОС истории: под новым ФИО создавались записи-копии с
    новым id, а старые прикапывались надгробиями. Операция была хрупкой — сбой посреди
    пути оставлял часть оценок осиротевшими, а на другие ПК уезжала пачка надгробий.

    Теперь ключ — неизменяемый student_id, и ФИО в таблицах живёт лишь как
    ДЕНОРМАЛИЗОВАННАЯ КОПИЯ для показа и старых выборок. Поэтому смена фамилии — это
    обычный UPDATE двух полей: ключи не двигаются, история никуда не переезжает,
    терять по дороге нечего.

    Ищем по student_id, а НЕ по старому ФИО: у переименованной студентки в базе может
    быть смесь строк (часть уже обновлена прошлым вызовом), и поиск по ФИО находил бы
    только часть.
    """
    if (old_f, old_n) == (new_f, new_n):
        return 0
    now = _now_iso()
    touched = 0
    for model in (Grade, TermGrade):
        rows = db.query(model).filter(model.student_id == student_id).all()             if student_id else             db.query(model).filter(model.student_f == old_f,
                                   model.student_n == old_n).all()
        for r in rows:
            if r.student_f == new_f and r.student_n == new_n:
                continue                      #уже актуально — метку не трогаем
            r.student_f, r.student_n = new_f, new_n
            r.updated_at = now
            touched += 1
    return touched


@router.put("/admin/students/{login}")
def admin_update_student(login: str, payload: dict = Body(...),
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Правка студента. Логин — ключ (id=stud:login), его не меняем: смена логина = это
    другой студент (создайте нового). Меняем ФИО/группу/пароль. Пустой пароль —
    оставляем прежний хеш. При смене ФИО ОЦЕНКИ ПЕРЕКЛЮЧАЮТСЯ на новый ключ."""
    sid = f"stud:{login}"
    row = db.get(User, sid)
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Студент не найден")
    old_f, old_n = row.surname or "", row.name or ""
    if "surname" in payload:
        row.surname = (payload.get("surname") or "").strip()
    #Имя/отчество: пересобираем name-ключ из имени и отчества (отчество храним отдельно).
    if "name" in payload or "patronymic" in payload:
        name_in = (payload.get("name") if "name" in payload else W.first_name(row)) or ""
        patr_in = (payload.get("patronymic") if "patronymic" in payload
                   else (row.patronymic or ""))
        row.name, row.patronymic = _compose_name(name_in, patr_in)
    #ФИО изменилось → обновляем его КОПИЮ в строках оценок. Ключи (student_id) при этом
    #не двигаются: история остаётся на месте, переносить нечего.
    moved = _rekey_student_grades(db, old_f, old_n, row.surname or "", row.name or "",
                                  student_id=row.id)
    if moved:
        audit.log(db, actor=_admin.login, role="admin", action="student.rekey",
                  target=f"{old_f} {old_n} → {row.surname} {row.name}",
                  detail=f"обновлено строк оценок: {moved}")
    if "group" in payload:
        group = (payload.get("group") or "").strip()
        _ensure_group_row(db, group)
        row.group_name = group
    password = payload.get("password") or ""
    if password:
        from ...security import hash_password
        row.password_hash = hash_password(password)
    row.updated_at = _now_iso()
    db.commit()
    return {"ok": True, "login": login}


@router.delete("/admin/students/{login}")
def admin_delete_student(login: str,
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Мягкое удаление студента (надгробие deleted=1): удаление доедет до десктопа и
    других клиентов через pull, а не «воскреснет» на следующем синке."""
    sid = f"stud:{login}"
    row = db.get(User, sid)
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Студент не найден")
    row.deleted = True
    row.updated_at = _now_iso()
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="student.delete", target=login)
    return {"ok": True, "login": login}


def _norm_category(value) -> str:
    """Категория расписания портала — пусто/неизвестное значение трактуем как
    "college" (см. Group.category докстринг): единственная категория с реальными
    аккаунтами, дефолт для всех форм создания групп, если админ её не менял."""
    key = (value or "").strip()
    return key if key in schedule_parser.CATEGORIES else "college"


# --- Группы (CRUD) --- id=grp:name (как в sync_engine); удаление мягкое (надгробие).
@router.post("/admin/groups")
def admin_create_group(payload: dict = Body(...),
                       _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Нужно название группы")
    gid = f"grp:{name}"
    existing = db.get(Group, gid)
    if existing is not None and not existing.deleted:
        raise HTTPException(status_code=409, detail="Группа с таким названием уже есть")
    row = existing or Group(id=gid)
    if existing is None:
        db.add(row)
    row.name = name
    row.subjects = payload.get("subjects") or []
    if "category" in payload:
        row.category = _norm_category(payload.get("category"))
    row.updated_at = _now_iso()
    row.deleted = False
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="group.create", target=name)
    return {"ok": True, "name": name, "category": row.category or "college"}


def _archive_dropped_subjects(db, group: str, old_subjects, new_subjects, now: str):
    """Предмет ушёл из плана группы (Group.subjects ЗАМЕНИЛИ — ручная правка или реимпорт
    учебного плана) — строка `SubjectHours` за ТЕКУЩИЙ термин гасится (`deleted=True`),
    а не остаётся висеть рядом со свежим планом.

    Живой баг 3.6.1, тремя разными симптомами одного корня: (1) «предмет убрали у
    группы, а журнал у препода остался» — `teacher_assignments` находил старую строку
    по `teacher_id`; (2) `group_plan_subjects` (единый источник «что сейчас изучает
    группа» для студента/куратора/родителя/Вектора) продолжал засчитывать предмет в
    план — она сверяется и по `Group.subjects`, И по живым строкам `SubjectHours`,
    поэтому одной замены списка недостаточно; (3) `zet_summary_for_student` считал
    ЗЕТ убранного предмета в знаменатель — она перечисляет именно живые `SubjectHours`.
    Гашение строки закрывает все три одним действием.

    Часы/ЗЕТ ЗНАЧЕНИЯ не стираем (`hours_total`/`zet` остаются в строке) — это и есть
    «архив»: история видна тем, кто явно смотрит прошлое (админ), просто не
    подмешивается в ТЕКУЩИЙ план. Повторное добавление того же предмета обратно в
    Group.subjects находит ЭТУ ЖЕ строку по составному id (`subject_hours_id`) и
    снимает с неё `deleted` — второй записи не создаётся. Архивные (прошлый термин)
    строки не трогаем — история не переписывается."""
    dropped = set(old_subjects or []) - set(new_subjects or [])
    if not dropped:
        return
    ty, ts = W.current_term(W.load_config(db))
    rows = (db.query(SubjectHours)
            .filter(SubjectHours.group_name == group, SubjectHours.subject.in_(dropped),
                    SubjectHours.year == ty, SubjectHours.semester == ts,
                    SubjectHours.deleted == False).all())  # noqa: E712
    for r in rows:
        r.teacher_id = ""
        r.deleted = True
        r.updated_at = now


@router.put("/admin/groups/{name:path}")
def admin_update_group(name: str, payload: dict = Body(...),
                       _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Правка группы (название — ключ, не меняем). Меняем список предметов/категорию."""
    row = db.get(Group, f"grp:{name}")
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    now = _now_iso()
    if "subjects" in payload:
        new_subjects = payload.get("subjects") or []
        _archive_dropped_subjects(db, name, row.subjects, new_subjects, now)
        row.subjects = new_subjects
    if "category" in payload:
        row.category = _norm_category(payload.get("category"))
    row.updated_at = now
    db.commit()
    return {"ok": True, "name": name}


@router.delete("/admin/groups/{name:path}")
def admin_delete_group(name: str,
                       _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(Group, f"grp:{name}")
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    row.deleted = True
    row.updated_at = _now_iso()
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="group.delete", target=name)
    return {"ok": True, "name": name}


@router.post("/admin/groups/import-schedule-category")
def admin_import_schedule_category(payload: dict = Body(...),
                                   _admin: User = Depends(require_admin),
                                   db: Session = Depends(get_db)):
    """Заводит группу-каталожную запись из НЕколледжевой категории расписания портала
    (Бакалавриат/Заочное 1/Заочное 2) — {category, group_name}. В отличие от
    admin_bind_subjects (импорт предметов ИЗ расписания уже существующих КОЛЛЕДЖ-групп),
    здесь часов/журнала (плана на семестр, ЗЕТ) нет вовсе — учебного плана у этих
    категорий не существует. Предметы, однако, ставим — ИЗ ТОГО ЖЕ снимка расписания
    (второго похода на портал не нужно): без них группа выглядела бы пустой каталожной
    записью без единого предмета, хотя расписание для неё уже разобрано.

    group_name сверяется с РЕАЛЬНЫМ списком групп портала для этой категории (тот же
    кэш, что отдаёт GET /schedule/groups) — свободного ввода имени нет специально,
    чтобы не расходиться с сайтом и не плодить опечатки."""
    category = (payload.get("category") or "").strip()
    group_name = (payload.get("group_name") or "").strip()
    if not category or category not in schedule_parser.CATEGORIES:
        raise HTTPException(status_code=400, detail="Нужна известная категория расписания")
    if not group_name:
        raise HTTPException(status_code=400, detail="Нужно название группы")
    if category != schedule_web.default_category():
        real_names = schedule_web.list_groups(category)
        if group_name not in real_names:
            raise HTTPException(status_code=422,
                                detail="Такой группы нет в текущем снимке расписания этой "
                                       "категории (сайт недоступен либо имя изменилось)")

    #Предметы — уникальные названия ИЗ УЖЕ РАЗОБРАННОГО расписания этой группы (те же
    #данные, что рисует вкладка «Расписание»). Сайт может быть недоступен именно сейчас —
    #тогда просто пусто, как и раньше; это не повод отказывать в создании группы.
    subjects = []
    try:
        sched = schedule_web.get_group(group_name, category)
        if sched:
            subjects = sorted({ls.get("subject") for days in (sched.get("weeks") or {}).values()
                               for lessons in days.values() for ls in lessons
                               if ls.get("subject")})
    except Exception:
        subjects = []

    gid = f"grp:{group_name}"
    existing = db.get(Group, gid)
    if existing is not None and not existing.deleted:
        raise HTTPException(status_code=409, detail="Группа с таким названием уже есть")
    row = existing or Group(id=gid)
    if existing is None:
        db.add(row)
    row.name = group_name
    row.subjects = subjects
    row.category = category
    row.updated_at = _now_iso()
    row.deleted = False
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="group.import_schedule_category",
              target=group_name, detail=category)
    return {"ok": True, "name": group_name, "category": category}


@router.post("/admin/groups/import-schedule-category-all")
def admin_import_schedule_category_all(payload: dict = Body(...),
                                       _admin: User = Depends(require_admin),
                                       db: Session = Depends(get_db)):
    """«Все» — массовый импорт ВСЕХ групп категории одним нажатием, а не по одной
    (Бакалавриат/Заочное 1/2 — 90-220 групп на категорию, кликать по одной неразумно).

    Переиспользует ТОТ ЖЕ полный снимок расписания, что и admin_bind_subjects для
    колледжа (schedule_web.full_state) — он и так делает всю тяжёлую работу (десятки-
    сотни GET на портал) лениво и в фоне с флагом building; второй такой crawler
    писать незачем. Пока снимок не готов — {ok: false, building: true}, клиент
    покажет статус и нажмёт ещё раз (тот же UX, что у «Обновить группы»).

    Уже существующие группы НЕ пересоздаёт (считает в skipped), но если у такой группы
    список предметов ПУСТ — доливает его из уже разобранного снимка: закрывает случай
    «группу когда-то завели по одной ДО того, как импорт стал подставлять предметы»
    без второго прохода руками. Непустые списки (в т.ч. правленные вручную) не трогает."""
    category = (payload.get("category") or "").strip()
    if not category or category not in schedule_parser.CATEGORIES:
        raise HTTPException(status_code=400, detail="Нужна известная категория расписания")
    if category == schedule_web.default_category():
        raise HTTPException(status_code=400,
                            detail="Массовый импорт — только для категорий вне колледжа")

    snap, building = schedule_web.full_state(category)
    if snap is None or not snap.groups:
        return {"ok": False, "building": building, "imported": 0, "skipped": 0, "total": 0}

    now = _now_iso()
    imported = 0
    skipped = 0
    for name, gsched in snap.groups.items():
        gid = f"grp:{name}"
        existing = db.get(Group, gid)
        if existing is not None and not existing.deleted:
            skipped += 1
            #Бэкфилл: группа могла быть заведена ДО того, как одиночный/массовый импорт
            #стали подставлять предметы (или портал не ответил в момент её импорта) —
            #раз уж расписание всё равно только что разобрано, доливаем предметы
            #в пустую запись бесплатно. ТОЛЬКО пустую — уже заполненные (в т.ч. вручную
            #админом) не трогаем, это не re-sync существующих данных.
            if not existing.subjects:
                subs = gsched.subjects()
                if subs:
                    existing.subjects = subs
                    existing.updated_at = now
            continue
        row = existing or Group(id=gid)
        if existing is None:
            db.add(row)
        row.name = name
        row.subjects = gsched.subjects()
        row.category = category
        row.updated_at = now
        row.deleted = False
        imported += 1
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="group.import_schedule_category_all",
              target=category, detail=f"imported={imported} skipped={skipped}")
    return {"ok": True, "building": building, "imported": imported, "skipped": skipped,
           "total": len(snap.groups)}


@router.post("/admin/groups/bind-subjects")
def admin_bind_subjects(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Привязывает к КАЖДОЙ группе колледжа предметы ИЗ ЕЁ расписания (портал ВСГУТУ) и
    пополняет каталог предметов. Использует полный снимок расписания (schedule_web —
    строится лениво в фоне, ~минута). Пока снимок готовится — {building: true}, клиент
    подождёт и нажмёт снова. Группы, которых ещё нет, заводятся; у существующих предметы
    ОБЪЕДИНЯЮТСЯ. Всё пишется в те же таблицы → синкается в десктоп."""
    #ФАНТОМЫ: несколько групп с ОДНИМ именем, но разными id (демо-остатки вроде
    #g:webtest — имя «К74/1», но 1 предмет). Оставляем каноничную grp:name (или с
    #бОльшим числом предметов), прочие с тем же именем удаляем. Hard-delete: на десктопе
    #группы мёрджатся по ИМЕНИ, поэтому надгробие фантома задело бы настоящую — а так нет.
    from collections import defaultdict
    dups = defaultdict(list)
    for g in db.query(Group).all():
        dups[g.name].append(g)
    removed = 0
    for gname, gs in dups.items():
        if len(gs) < 2:
            continue
        canon = next((x for x in gs if x.id == f"grp:{gname}"), None) \
            or max(gs, key=lambda x: len(x.subjects or []))
        for x in gs:
            if x.id != canon.id:
                db.delete(x)
                removed += 1
    if removed:
        db.commit()

    snap, building = schedule_web.full_state()
    if snap is None or not snap.groups:
        return {"ok": bool(removed), "building": building, "bound": 0,
                "subjects": 0, "removed": removed}
    now = _now_iso()
    bound = 0
    all_subjects = set()
    for name, gsched in snap.groups.items():
        subs = sorted({s for s in gsched.subjects() if s})
        if not subs:
            continue
        all_subjects.update(subs)
        gid = f"grp:{name}"
        row = db.get(Group, gid)
        if row is None:
            db.add(Group(id=gid, name=name, subjects=subs, updated_at=now, deleted=False))
            bound += 1
        else:
            #РАСПИСАНИЕ — основа: ЗАМЕНЯЕМ предметы группы на предметы из расписания, а не
            #объединяем со старыми (раньше union оставлял то, что выставил админ вручную —
            #Ярослав просил, чтобы по умолчанию были ИЗ РАСПИСАНИЯ). Менять по-прежнему можно
            #вручную в карточке группы; повторный «Из расписания» пересинхронит с порталом.
            new = sorted(subs)
            if new != list(row.subjects or []) or row.deleted:
                _archive_dropped_subjects(db, name, row.subjects, new, now)
                row.subjects = new
                row.deleted = False
                row.updated_at = now
                bound += 1
    for s in all_subjects:                                   #пополняем каталог предметов
        sid = f"subj:{s}"
        if db.get(Subject, sid) is None:
            db.add(Subject(id=sid, name=s, updated_at=now, deleted=False))
    db.commit()
    return {"ok": True, "building": building, "bound": bound, "subjects": len(all_subjects)}


# --- Импорт специальности/учебного плана ВСГУТУ (parsers/esstu_parser.py) ---------

#Список специальностей меняется на сайте колледжа редко — TTL-кэш в памяти процесса
#(тот же приём, что schedule_web.py уже применяет для похожей задачи: внешний сайт,
#не свои данные, дёргать его на каждый клик в диалоге импорта незачем).
_ESSTU_SPECIALTIES_CACHE = {"ts": 0.0, "data": []}
_ESSTU_SPECIALTIES_TTL = 3 * 3600


@router.get("/admin/esstu/specialties")
def admin_esstu_specialties(group: str = Query(""), _admin: User = Depends(require_admin)):
    """Справочник специальностей колледжа с сайта ВСГУТУ — для диалога импорта
    учебного плана. Сайт недоступен/структура страницы изменилась —
    esstu_parser.get_all_specialties() сама вернёт [] (см. её докстринг), это НЕ
    ошибка запроса — фронт покажет пустой список и ссылку «повторить».

    group (опц.) — имя группы, для которой открыт диалог: если её буквенный
    префикс узнаётся (esstu_parser.match_specialty), подсказываем код специальности
    ОДНИМ источником правды на сервере — а не второй копией того же маппинга в JS."""
    import time
    now = time.time()
    if not (_ESSTU_SPECIALTIES_CACHE["data"]
           and now - _ESSTU_SPECIALTIES_CACHE["ts"] < _ESSTU_SPECIALTIES_TTL):
        _ESSTU_SPECIALTIES_CACHE["data"] = esstu_parser.get_all_specialties()
        _ESSTU_SPECIALTIES_CACHE["ts"] = now
    specialties = _ESSTU_SPECIALTIES_CACHE["data"]
    suggested = esstu_parser.match_specialty(group, specialties) if group else None
    return {"specialties": specialties, "suggested_code": (suggested or {}).get("code", "")}


#Годы набора, для которых у СПЕЦИАЛЬНОСТИ реально опубликован план — свои на
#каждый код, тот же TTL-приём, что у справочника специальностей выше. Раньше
#год поступления вводился руками (число), и легко было промахнуться мимо
#реально существующих на сайте лет — теперь выбор ограничен тем, что там
#действительно есть, само перечисление уже умеет _fetch_plan_years.
_ESSTU_PLAN_YEARS_CACHE: dict = {}
_ESSTU_PLAN_YEARS_TTL = 3 * 3600


@router.get("/admin/esstu/plan-years")
def admin_esstu_plan_years(specialty_code: str = Query(...),
                           _admin: User = Depends(require_admin)):
    """Годы набора с реально опубликованным планом для данной специальности —
    наполняет выпадающий список «Год поступления» в диалоге импорта (вместо
    ручного ввода числа, которое почти всегда промахивалось: у специальности
    обычно доступны только 3-5 последних лет, а не с основания колледжа)."""
    import time
    now = time.time()
    entry = _ESSTU_PLAN_YEARS_CACHE.get(specialty_code)
    if not entry or now - entry["ts"] >= _ESSTU_PLAN_YEARS_TTL:
        years = sorted(esstu_parser._fetch_plan_years(specialty_code), reverse=True)
        entry = {"ts": now, "years": years}
        _ESSTU_PLAN_YEARS_CACHE[specialty_code] = entry
    return {"years": entry["years"]}


@router.post("/admin/groups/import-esstu")
def admin_import_esstu(payload: dict = Body(...),
                       _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Импорт специальности + учебного плана ВСГУТУ в группу: {group, specialty_code,
    enrollment_year}. Группа — в BODY, НЕ в пути (инвариант §10 — слэш в имени группы
    ломает путь URL).

    Подтягивает план целиком (esstu_parser.get_study_plan), считает курс/семестр
    группы ОТ ГОДА ПОСТУПЛЕНИЯ и ТЕКУЩЕГО термина (study_hours.course_and_semester —
    не календарные дни, а те же дискретные термины, которыми уже устроена вся
    остальная система), и заносит в Group.subjects/SubjectHours ТОЛЬКО дисциплины
    ТЕКУЩЕГО семестра — не всю четырёхлетнюю программу разом (иначе через год
    список предметов группы пришлось бы перестраивать вручную). Дисциплины, для
    которых семестр из плана извлечь не удалось (см. esstu_parser — сетка семестров
    не на каждом документе калибруется), ВСЁ РАВНО попадают в Group.subjects
    (лучше показать «предмет есть, часов пока нет», чем молча его не показать), но
    БЕЗ строки SubjectHours — часы по ним админ заполняет вручную, как раньше.

    Как admin_bind_subjects (импорт предметов ИЗ РАСПИСАНИЯ) — та же логика:
    ЗАМЕНЯЕМ Group.subjects (не объединяем), внешний источник считается основой на
    момент импорта; повторный импорт пересинхронит с планом."""
    group = (payload.get("group") or "").strip()
    specialty_code = (payload.get("specialty_code") or "").strip()
    enrollment_year = payload.get("enrollment_year")
    if not group or not specialty_code or not enrollment_year:
        raise HTTPException(status_code=400,
                            detail="Нужны group, specialty_code, enrollment_year")
    try:
        enrollment_year = int(enrollment_year)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="enrollment_year должен быть числом (год)")

    grp = db.get(Group, f"grp:{group}")
    if grp is None or grp.deleted:
        #Фолбэк по имени: GET /admin/groups отдаёт группы ТОЛЬКО по name (id клиенту
        #вообще не виден), а название приходит сюда тем же значением без повторного
        #ввода. Если у строки id почему-то разъехался с `grp:{name}` (старые данные,
        #ручная правка БД, миграция) — группа видна в списке, но реконструкция id
        #мимо неё промахивается. Остальные три места с этим лукапом не трогаем: там
        #расхождение не воспроизведено, а этот фолбэк — расширение, не сужение.
        grp = (db.query(Group)
              .filter(Group.name == group, Group.deleted == False)  # noqa: E712
              .first())
    if grp is None or grp.deleted:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    plan = esstu_parser.get_study_plan(specialty_code, enrollment_year)
    if not plan:
        raise HTTPException(status_code=422,
                            detail="Учебный план не найден для этой специальности/года набора "
                                   "(сайт ВСГУТУ недоступен, план не опубликован, либо не "
                                   "распознан — подробности в логе сервера)")

    cfg = W.load_config(db)
    ty, ts = W.current_term(cfg)
    course, overall_semester = W.study_hours.course_and_semester(enrollment_year, ty, ts)

    current_rows = [r for r in plan if r["hours_by_semester"].get(overall_semester)]
    unmapped_rows = [r for r in plan if not r["hours_by_semester"]]
    now = _now_iso()

    #Group.subjects — ЗАМЕНА (как admin_bind_subjects), план — источник истины на
    #момент импорта. Дубли имён (одно название в разных циклах, напр. «История»)
    #схлопываются — Group.subjects хранит имена, не индексы дисциплин плана.
    all_names = sorted({r["subject"] for r in current_rows} | {r["subject"] for r in unmapped_rows})
    #Предметы, которых в СВЕЖЕМ плане больше нет (напр. группу «доучили» до другого курса
    #или починили ранее неверно посчитанный курс, см. CLAUDE.md 3.6.1) — их строка часов
    #уходит в архив (deleted=True) за ТЕКУЩИЙ термин; сами часы/ЗЕТ не стираем.
    _archive_dropped_subjects(db, group, grp.subjects, all_names, now)
    grp.subjects = all_names
    grp.specialty_code = specialty_code
    grp.enrollment_year = enrollment_year
    grp.updated_at = now
    grp.deleted = False

    saved = 0
    for row in current_rows:
        name = row["subject"]
        #ВАЖНО: hours_total в SubjectHours — часы «на семестр» (см. models.py::
        #SubjectHours docstring), а НЕ общий итог по дисциплине за все 4 курса —
        #берём ИМЕННО часы текущего семестра из сетки, не row["hours"] (это было
        #реальной ошибкой первой версии, поймано тестом: группа получала часы
        #всей четырёхлетней программы в один семестр).
        sem_hours = row["hours_by_semester"].get(overall_semester) or 0
        hid = subject_hours_id(group, name, ty, ts)
        existing = db.get(SubjectHours, hid)
        sh = existing or SubjectHours(id=hid, group_name=group, subject=name, year=ty, semester=ts)
        if existing is None:
            db.add(sh)
        sh.hours_total = int(sem_hours)
        sh.zet = W.study_hours.zet_hint(sem_hours) or None
        #teacher_id НЕ трогаем: это отдельное ручное назначение администратора
        #(§ролей препод↔предмет↔группа), к содержимому учебного плана отношения
        #не имеет — импорт правит только часы/ЗЕТ, а не «кто ведёт».
        sh.updated_at = now
        sh.deleted = False
        saved += 1

    for name in all_names:                                    #пополняем каталог предметов
        sid = f"subj:{name}"
        if db.get(Subject, sid) is None:
            db.add(Subject(id=sid, name=name, updated_at=now, deleted=False))

    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="group.import_esstu",
              target=group, detail=f"{specialty_code} набор {enrollment_year}, курс {course}")
    return {
        "ok": True,
        "group": group,
        "course": course,
        "semester": overall_semester,
        "term": {"year": ty, "semester": ts},
        "imported": [r["subject"] for r in current_rows],
        "unmapped": sorted({r["subject"] for r in unmapped_rows} - {r["subject"] for r in current_rows}),
        "saved_hours": saved,
    }


# --- Предметы (CRUD) --- id=subj:name. NB: на десктопе список предметов аддитивный
# (apply_remote объединяет множества), поэтому удаление предмета убирает его из веба и
# таблицы, но на десктопе он может остаться до ручной чистки — это поведение синка §subjects.
@router.post("/admin/subjects")
def admin_create_subject(payload: dict = Body(...),
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Нужно название предмета")
    sid = f"subj:{name}"
    existing = db.get(Subject, sid)
    if existing is not None and not existing.deleted:
        raise HTTPException(status_code=409, detail="Такой предмет уже есть")
    row = existing or Subject(id=sid)
    if existing is None:
        db.add(row)
    row.name = name
    row.updated_at = _now_iso()
    row.deleted = False
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="subject.create", target=name)
    return {"ok": True, "name": name}


@router.put("/admin/subjects/{name:path}")
def admin_rename_subject(name: str, payload: dict = Body(...),
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Переименование предмета — правит НЕ ТОЛЬКО каталог, а ВЕЗДЕ, где имя предмета
    лежит ПРОСТОЙ СТРОКОЙ (внешнего ключа на Subject.id нигде нет): Group.subjects
    (JSON-список), Lesson.subject, User.subjects (нагрузка препода), ScheduleOverride.subject
    и SubjectHours (там имя вдобавок сидит В ID — `hrs:{группа}|{предмет}|{год}|{семестр}`,
    той же природы, что и id самого Subject, — строку id менять нельзя, переносим на
    новый id, старую строку гасим, как и каталожную запись). Без каскада переименование
    выглядело бы наполовину сделанным — каталог показывает новое имя, а везде
    остальном старое, будто это два разных предмета."""
    old = (name or "").strip()
    new = (payload.get("name") or "").strip()
    if not new:
        raise HTTPException(status_code=400, detail="Нужно новое название")
    if new == old:
        return {"ok": True, "name": new}
    row = db.get(Subject, f"subj:{old}")
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    new_id = f"subj:{new}"
    existing = db.get(Subject, new_id)
    if existing is not None and not existing.deleted:
        raise HTTPException(status_code=409, detail="Предмет с таким названием уже есть")
    now = _now_iso()

    #Каталог: id включает имя, физически переименовать нельзя — гасим старую запись,
    #заводим/оживляем новую (в самой записи, кроме имени, ничего не хранится).
    row.deleted = True
    row.updated_at = now
    if existing is not None:
        existing.deleted = False
        existing.updated_at = now
    else:
        db.add(Subject(id=new_id, name=new, updated_at=now))

    for g in db.query(Group).filter(Group.deleted == False).all():  # noqa: E712
        subs = g.subjects or []
        if old in subs:
            g.subjects = [new if s == old else s for s in subs]
            g.updated_at = now

    for u in db.query(User).filter(User.role == "teacher", User.deleted == False).all():  # noqa: E712
        subs = u.subjects or []
        if old in subs:
            u.subjects = [new if s == old else s for s in subs]
            u.updated_at = now

    db.query(Lesson).filter(Lesson.subject == old, Lesson.deleted == False).update(  # noqa: E712
        {"subject": new, "updated_at": now}, synchronize_session=False)
    db.query(ScheduleOverride).filter(
        ScheduleOverride.subject == old, ScheduleOverride.deleted == False).update(  # noqa: E712
        {"subject": new, "updated_at": now}, synchronize_session=False)

    #SubjectHours — id сам содержит имя предмета, поэтому переносим построчно на новый id
    #(а не bulk-UPDATE колонки subject, это бы оставило старый id, конфликтующий по смыслу
    #с новым содержимым — тот же принцип, что у Subject.id выше).
    for hr in db.query(SubjectHours).filter(
            SubjectHours.subject == old, SubjectHours.deleted == False).all():  # noqa: E712
        new_hid = subject_hours_id(hr.group_name, new, hr.year, hr.semester)
        target = db.get(SubjectHours, new_hid)
        if target is None:
            target = SubjectHours(id=new_hid, group_name=hr.group_name, subject=new,
                                  year=hr.year, semester=hr.semester)
            db.add(target)
        target.hours_total = hr.hours_total
        target.teacher_id = hr.teacher_id
        target.zet = hr.zet
        target.deleted = False
        target.updated_at = now
        hr.deleted = True
        hr.updated_at = now

    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="subject.rename",
             target=f"{old} → {new}")
    return {"ok": True, "name": new}


@router.delete("/admin/subjects/{name:path}")
def admin_delete_subject(name: str,
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(Subject, f"subj:{name}")
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    row.deleted = True
    row.updated_at = _now_iso()
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="subject.delete", target=name)
    return {"ok": True, "name": name}


# --- Преподаватели (CRUD) --- id=teach:login (как в sync_engine); ФИО — full_name,
# нагрузка — список subjects. Пароль тем же гибридным хешем; удаление мягкое.
@router.post("/admin/teachers")
def admin_create_teacher(payload: dict = Body(...),
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    full_name = (payload.get("full_name") or "").strip()
    login = (payload.get("login") or "").strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Нужно ФИО преподавателя")
    if not login:
        raise HTTPException(status_code=400, detail="Нужен логин")
    tid = f"teach:{login}"
    existing = db.get(User, tid)
    if existing is not None and not existing.deleted:
        raise HTTPException(status_code=409, detail="Преподаватель с таким логином уже есть")
    row = existing or User(id=tid)
    if existing is None:
        db.add(row)
    row.role = "teacher"
    row.login = login
    row.full_name = full_name
    row.surname = ""
    row.name = ""
    row.group_name = ""
    row.subjects = payload.get("subjects") or []
    #Куратор: непустой список групп = роль куратора (read-only доступ ко всем предметам групп).
    row.curated_groups = payload.get("curated_groups") or []
    row.group_assignments = {}
    password = payload.get("password") or ""
    if password:
        from ...security import hash_password
        row.password_hash = hash_password(password)
    row.updated_at = _now_iso()
    row.deleted = False
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="teacher.create",
              target=login, detail=full_name)
    return {"ok": True, "login": login}


@router.put("/admin/teachers/{login}")
def admin_update_teacher(login: str, payload: dict = Body(...),
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Правка преподавателя (логин — ключ). Меняем ФИО/нагрузку(предметы)/пароль."""
    row = db.get(User, f"teach:{login}")
    if row is None or row.deleted or row.role != "teacher":
        raise HTTPException(status_code=404, detail="Преподаватель не найден")
    if "full_name" in payload:
        row.full_name = (payload.get("full_name") or "").strip()
    if "subjects" in payload:
        row.subjects = payload.get("subjects") or []
    #Выдача/снятие кураторства — только админ; логируем (роль остаётся teacher).
    if "curated_groups" in payload:
        before = list(row.curated_groups or [])
        row.curated_groups = payload.get("curated_groups") or []
        if list(row.curated_groups) != before:
            audit.log(db, actor=_admin.login, role="admin", action="curator.set",
                      target=login, detail=", ".join(row.curated_groups) or "(снято)")
    password = payload.get("password") or ""
    if password:
        from ...security import hash_password
        row.password_hash = hash_password(password)
    row.updated_at = _now_iso()
    db.commit()
    return {"ok": True, "login": login}


@router.delete("/admin/teachers/{login}")
def admin_delete_teacher(login: str,
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(User, f"teach:{login}")
    if row is None or row.deleted or row.role != "teacher":
        raise HTTPException(status_code=404, detail="Преподаватель не найден")
    row.deleted = True
    row.updated_at = _now_iso()
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="teacher.delete", target=login)
    return {"ok": True, "login": login}


# --- Заявки на регистрацию студентов (одобрение админом) ------------------------
@router.get("/admin/registrations")
def admin_registrations(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Список заявок студентов на самостоятельную регистрацию, ждущих решения."""
    rows = db.query(RegistrationRequest).filter(
        RegistrationRequest.status == "pending").order_by(RegistrationRequest.created_at).all()
    return {"requests": [{"id": r.id, "full_name": r.full_name, "group": r.group_name,
                          "phone": gost.decrypt(r.phone), "email": r.email,
                          "created_at": r.created_at}
                         for r in rows]}


@router.post("/admin/registrations/approve")
def admin_approve_registration(payload: dict = Body(...),
                               _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Одобрить заявку: сгенерировать пароль (8 симв, 1 заглавная, 1 спец), логин = e-mail,
    завести СТУДЕНТА (пароль хешируем) в его группу и выслать креды на почту. Если SMTP не
    настроен — возвращаем пароль админу, чтобы передать вручную (регистрация не ломается).
    id студента = stud:email (как в синке) → аккаунт доедет до десктопа обычным pull."""
    req = db.get(RegistrationRequest, (payload.get("id") or "").strip())
    if req is None or req.status != "pending":
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    email = req.email
    if db.query(User).filter(User.login == email, User.deleted == False).first():  # noqa: E712
        req.status = "rejected"
        req.note = "дубликат — аккаунт уже есть"
        db.commit()
        raise HTTPException(status_code=409, detail="Аккаунт с такой почтой уже существует")

    pw = reg_utils.gen_password()
    #name = «Имя Отчество» (parts[1:]) — прежний КЛЮЧ (не меняем). Отчество (parts[2:])
    #дополнительно кладём в отдельное поле patronymic. Формат ключа не трогаем.
    parts = req.full_name.split()
    surname = parts[0] if parts else ""
    name = " ".join(parts[1:]) if len(parts) > 1 else ""
    patronymic = " ".join(parts[2:]) if len(parts) > 2 else ""
    from ...security import hash_password
    sid = f"stud:{email}"
    row = db.get(User, sid) or User(id=sid)
    if db.get(User, sid) is None:
        db.add(row)
    row.role = "student"
    row.login = email
    row.password_hash = hash_password(pw)
    row.full_name = req.full_name
    row.surname = surname
    row.name = name
    row.patronymic = patronymic
    row.group_name = req.group_name
    row.subjects = []
    row.group_assignments = {}
    row.updated_at = _now_iso()
    row.deleted = False
    req.status = "approved"
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="reg.approve",
              target=email, detail=req.group_name)

    sent = mailer.send_email(
        email, "GradeBookAI — доступ к электронному журналу",
        f"Здравствуйте, {req.full_name}!\n\nВаша регистрация одобрена.\n"
        f"Логин: {email}\nПароль: {pw}\nГруппа: {req.group_name}\n\n"
        f"Войдите на https://esstu-gradebook.ru",
        html=mailer._brand_html("Регистрация одобрена", [
            f"Здравствуйте, <b>{req.full_name}</b>! Ваш доступ к электронному журналу готов.",
            f"Логин: <b>{email}</b>",
            f"Пароль: <b style='font-size:18px'>{pw}</b>",
            f"Группа: <b>{req.group_name}</b>",
            "Войдите на <a href='https://esstu-gradebook.ru'>esstu-gradebook.ru</a>."]))
    #Пароль отдаём админу ТОЛЬКО если письмо не ушло (иначе не светим лишний раз).
    return {"ok": True, "sent": sent, "login": email,
            "password": None if sent else pw}


@router.post("/admin/registrations/reject")
def admin_reject_registration(payload: dict = Body(...),
                              _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    req = db.get(RegistrationRequest, (payload.get("id") or "").strip())
    if req is None or req.status != "pending":
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    req.status = "rejected"
    req.note = (payload.get("note") or "отклонено администратором").strip()
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="reg.reject", target=req.email)
    return {"ok": True}


# --- Журнал аудита (ФСТЭК №21) — только чтение, только админ ---------------------
@router.get("/admin/audit")
def admin_audit(limit: int = Query(200, ge=1, le=1000), action: str = Query(""),
                actor: str = Query(""), _admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    """Персистентный журнал значимых действий (входы/выходы, изменения оценок и ПДн,
    регистрации). Только чтение — записи неизменяемы. Фильтры по коду действия и логину."""
    return {"events": audit.recent(db, limit=limit, action=action or None,
                                   actor=actor or None)}


# --- Настройки ИИ «Вектор» (провайдер + ключ GigaChat) — 1:1 с десктопом -----------
# Хранятся в той же строке ConfigKV key="config", что и на десктопе (синхронизируется
# в обе стороны). Пишем с серверной меткой updated_at (LWW, §3) → ключ админа, заданный
# на ПК, доедет на веб и наоборот.
_AI_CFG_KEYS = ("vector_llm", "gigachat_credentials", "gigachat_scope",
                "gigachat_model", "local_model", "tts_enabled", "tts_engine",
                "stt_mode")
