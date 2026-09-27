"""
courses.py — учебные курсы (аналог «Курсы» портала колледжа): структура, материалы,
задания, авторы.

🔒 СЕРВЕРНАЯ подсистема (модели вне SYNC_MODELS, см. models.py) — как мессенджер. Курсы
контентные, офлайн-синк им не нужен; десктоп-онлайн получает их тем же REST.

Скоуп по ролям (row-level, как везде):
  • студент  — курсы СВОЕЙ группы (`Course.group_name == user.group_name`), не в архиве, ЧТЕНИЕ;
  • преподаватель — курсы, где он АВТОР, либо где (группа, предмет) курса в его назначениях
    текущего термина; создавать может по своим (группа+предмет) назначениям;
  • админ — все, полный доступ;
  • родитель — курсы группы(групп) своих АКТИВНЫХ детей, ЧТЕНИЕ.

Материалы — ссылки (`kind='link'`), текст и ФАЙЛЫ (`kind='file'`, аудит 22.09.2026, F-26).
Файл идёт через ту же инфраструктуру вложений, что у мессенджера (`app/storage.py`):
режим выбирает машина по свободному месту/ключам S3, файл мимо нашего сервера, тип — по
белому списку, размер и суточный потолок — та же дверь (`start_signed_upload`). Владелец
вложения — `course:<id>`, поэтому ссылку на скачивание выдаёт ТОЛЬКО курс и только тем,
кто курс видит (`_can_view`); через мессенджер её не получить — такой беседы нет.
⚠️ Антивирусной проверки нет: защита — белый список типов (исполняемых в нём нет) и то,
что файл открывает браузер человека, а не наш сервер. На приёмке это называть прямо.
"""
from ._common import *  # noqa: F401,F403  (router, get_current_user, get_db, User, W, _now_iso, ...)
from ...models import (Course, CourseAuthor, CourseSection, CourseMaterial,
                       CourseAssignment, ParentLink, Attachment)
from ..messenger.attachments import signed_download, start_signed_upload


def _course_scope(cid: int) -> str:
    """Владелец файлов курса в таблице вложений (см. шапку)."""
    return f"course:{int(cid)}"


# ── Вспомогательное ───────────────────────────────────────────────────────────────────
def _user_name(db: Session, uid: str) -> str:
    """ФИО пользователя по id ('' если не найден) — для подписи авторов/выдавшего задание."""
    if not uid:
        return ""
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        return ""
    #surname+name — раздельная форма; full_name — канонический ключ ФИО (у препода это он).
    combined = f"{(u.surname or '').strip()} {(u.name or '').strip()}".strip()
    return combined or (u.full_name or "").strip() or (u.login or "")


def _parent_group_names(db: Session, user: User) -> set:
    """Учебные группы АКТИВНЫХ детей родителя (для скоупа чтения курсов)."""
    groups = set()
    for link in (db.query(ParentLink)
                 .filter(ParentLink.parent_id == user.id, ParentLink.status == "active").all()):
        child = db.query(User).filter(User.id == link.student_id).first()
        if child and child.group_name:
            groups.add(child.group_name)
    return groups


def _course_or_404(db: Session, cid: int) -> Course:
    c = db.query(Course).filter(Course.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Курс не найден")
    return c


def _author_ids(db: Session, cid: int) -> list:
    return [a.teacher_id for a in db.query(CourseAuthor).filter(CourseAuthor.course_id == cid).all()]


def _teacher_pairs(db: Session, user: User) -> set:
    """Пары (группа, предмет), назначенные преподавателю в ТЕКУЩЕМ термине."""
    cfg = W.load_config(db)
    year, semester = W.current_term(cfg)
    return set(W.teacher_assignments(db, user.id, year, semester))


def _can_view(db: Session, user: User, c: Course) -> bool:
    if user.role == "admin":
        return True
    if user.role == "student":
        #Непустая группа обязательна с ОБЕИХ сторон: иначе курс без группы (заведённый
        #админом) утёк бы студенту без группы по совпадению '' == '' (находка Полковника).
        return (not c.archived) and bool(c.group_name) and c.group_name == (user.group_name or "")
    if user.role == "parent":
        return (not c.archived) and c.group_name in _parent_group_names(db, user)
    if user.role == "teacher":
        if user.id in _author_ids(db, c.id):
            return True
        return (c.group_name, c.subject) in _teacher_pairs(db, user)
    return False


def _require_edit(db: Session, user: User, c: Course) -> None:
    """Править курс может админ или его автор. Архивный курс не редактируется (только читается)."""
    if user.role == "admin":
        return
    if user.role == "teacher" and user.id in _author_ids(db, c.id):
        if c.archived:
            raise HTTPException(status_code=409, detail="Курс в архиве — только чтение")
        return
    raise HTTPException(status_code=403, detail="Править курс может только его автор или админ")


def _material_out(m: CourseMaterial, files: dict = None) -> dict:
    out = {"id": m.id, "section_id": m.section_id or 0, "kind": m.kind or "link",
           "title": m.title or "", "url": m.url or "", "position": m.position or 0}
    if (m.kind or "") == "file":
        a = (files or {}).get(m.file_path or "")
        out["url"] = ""
        out["file"] = ({"name": a.name or "", "size": int(a.size or 0), "mime": a.mime or ""}
                       if a is not None else None)
    return out


def _course_brief(db: Session, c: Course) -> dict:
    """Карточка курса для списка: авторы (имена) + счётчики материалов/заданий."""
    authors = [_user_name(db, tid) for tid in _author_ids(db, c.id)]
    mats = db.query(CourseMaterial).filter(CourseMaterial.course_id == c.id).count()
    asg = db.query(CourseAssignment).filter(CourseAssignment.course_id == c.id).count()
    return {"id": c.id, "title": c.title or "", "subject": c.subject or "",
            "group_name": c.group_name or "", "authors": [a for a in authors if a],
            "materials_count": mats, "assignments_count": asg,
            "created_at": c.created_at or "", "archived": bool(c.archived)}


# ── Чтение ────────────────────────────────────────────────────────────────────────────
@router.get("/courses")
def list_courses(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 q: str = Query(""), include_archived: bool = Query(False)):
    """Список курсов, доступных вызывающему (скоуп по роли). q — поиск по названию/предмету."""
    query = db.query(Course)
    if user.role == "student":
        g = (user.group_name or "")
        if not g:
            return {"courses": []}   #студент без группы не видит «безгруппных» курсов ('' == '')
        query = query.filter(Course.group_name == g, Course.archived == False)  # noqa: E712
    elif user.role == "parent":
        groups = _parent_group_names(db, user)
        if not groups:
            return {"courses": []}
        query = query.filter(Course.group_name.in_(groups), Course.archived == False)  # noqa: E712
    elif user.role == "teacher":
        author_cids = [a.course_id for a in
                       db.query(CourseAuthor).filter(CourseAuthor.teacher_id == user.id).all()]
        pairs = _teacher_pairs(db, user)
        # фильтрация по парам — в Python: пар немного, а составить OR по кортежам в SQLite неудобно
        rows = query.all()
        cand = [c for c in rows if c.id in author_cids or (c.group_name, c.subject) in pairs]
        rows = cand
    else:  # admin
        rows = None
    if user.role in ("student", "parent"):
        rows = query.all()
    elif user.role == "admin":
        rows = query.all() if include_archived else query.filter(Course.archived == False).all()  # noqa: E712
    ql = (q or "").strip().lower()
    out = []
    for c in rows:
        if ql and ql not in (c.title or "").lower() and ql not in (c.subject or "").lower():
            continue
        out.append(_course_brief(db, c))
    out.sort(key=lambda x: (x["archived"], -x["id"]))
    return {"courses": out}


@router.get("/courses/{course_id}")
def course_detail(course_id: int, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Полный курс: структура (разделы с материалами) + материалы вне разделов + задания."""
    c = _course_or_404(db, course_id)
    if not _can_view(db, user, c):
        raise HTTPException(status_code=403, detail="Курс вам недоступен")
    can_edit = (user.role == "admin") or (user.role == "teacher" and user.id in _author_ids(db, c.id))

    mats = db.query(CourseMaterial).filter(CourseMaterial.course_id == c.id).all()
    att_ids = [m.file_path for m in mats if (m.kind or "") == "file" and m.file_path]
    files = ({a.id: a for a in db.query(Attachment).filter(Attachment.id.in_(att_ids)).all()}
             if att_ids else {})
    by_section = {}
    orphan = []
    for m in sorted(mats, key=lambda x: (x.position or 0, x.id)):
        (by_section.setdefault(m.section_id, []) if m.section_id else orphan).append(
            _material_out(m, files))

    sections = []
    for s in (db.query(CourseSection).filter(CourseSection.course_id == c.id)
              .order_by(CourseSection.position, CourseSection.id).all()):
        sections.append({"id": s.id, "title": s.title or "", "position": s.position or 0,
                         "materials": by_section.get(s.id, [])})

    assignments = []
    for a in (db.query(CourseAssignment).filter(CourseAssignment.course_id == c.id)
              .order_by(CourseAssignment.id).all()):
        assignments.append({"id": a.id, "title": a.title or "", "description": a.description or "",
                            "due_date": a.due_date or "", "url": a.url or "",
                            "teacher_name": _user_name(db, a.teacher_id), "created_at": a.created_at or ""})

    return {
        "id": c.id, "title": c.title or "", "subject": c.subject or "",
        "group_name": c.group_name or "", "description": c.description or "",
        "archived": bool(c.archived), "can_edit": can_edit,
        "authors": [{"id": tid, "name": _user_name(db, tid)} for tid in _author_ids(db, c.id)],
        "sections": sections, "materials": orphan, "assignments": assignments,
    }


# ── Запись (преподаватель-автор / админ) ──────────────────────────────────────────────
@router.post("/courses")
def create_course(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  title: str = Body(..., embed=True), subject: str = Body("", embed=True),
                  group_name: str = Body("", embed=True), description: str = Body("", embed=True)):
    """Создать курс. Преподаватель — только по СВОЕЙ паре (группа+предмет) текущего термина;
    админ — по любой. Создатель автоматически становится автором."""
    title = (title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Нужно название курса")
    group_name = (group_name or "").strip()
    subject = (subject or "").strip()
    if user.role == "teacher":
        if (group_name, subject) not in _teacher_pairs(db, user):
            raise HTTPException(status_code=403,
                                detail="Курс можно создать только по своей группе и предмету")
    elif user.role != "admin":
        raise HTTPException(status_code=403, detail="Создавать курсы может преподаватель или админ")
    now = _now_iso()
    c = Course(title=title, subject=subject, group_name=group_name, description=(description or "").strip(),
               created_by=user.id, created_at=now, updated_at=now, archived=False)
    db.add(c)
    db.flush()  # получить c.id
    db.add(CourseAuthor(course_id=c.id, teacher_id=user.id, added_at=now))
    db.commit()
    audit.log(db, actor=user.login, action="course.create", target=str(c.id), detail=title)
    return {"id": c.id}


@router.post("/courses/{course_id}/sections")
def add_section(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                title: str = Body(..., embed=True), position: int = Body(0, embed=True)):
    c = _course_or_404(db, course_id)
    _require_edit(db, user, c)
    title = (title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Нужно название раздела")
    s = CourseSection(course_id=c.id, title=title, position=int(position or 0), created_at=_now_iso())
    db.add(s); c.updated_at = _now_iso(); db.commit()
    return {"id": s.id}


@router.post("/courses/{course_id}/files/sign")
def sign_course_file(course_id: int, payload: dict = Body(...),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Подписать загрузку файла материала. Права — как на правку курса (автор или админ)."""
    c = _course_or_404(db, course_id)
    _require_edit(db, user, c)
    return start_signed_upload(db, user, _course_scope(c.id), payload)


@router.post("/courses/{course_id}/materials")
def add_material(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 title: str = Body(..., embed=True), url: str = Body("", embed=True),
                 kind: str = Body("link", embed=True), section_id: int = Body(0, embed=True),
                 attachment_id: str = Body("", embed=True)):
    """Добавить материал: ссылку, текст или загруженный файл (`attachment_id`, F-26)."""
    c = _course_or_404(db, course_id)
    _require_edit(db, user, c)
    kind = (kind or "link").strip()
    if kind not in ("link", "text", "file"):
        raise HTTPException(status_code=400, detail="Материал — ссылка, текст или файл")
    title = (title or "").strip()
    url = (url or "").strip()
    if kind == "link" and not url:
        raise HTTPException(status_code=400, detail="Нужна ссылка на материал")
    att = None
    if kind == "file":
        #Три проверки, и все обязательны (как у отправки файла в беседе): файл загружен
        #ДЛЯ ЭТОГО курса, загрузка ПОДТВЕРЖДЕНА, и загружал его тот, кто сейчас добавляет
        #(или админ). Иначе чужой файл другого курса «переезжал» бы сюда по id.
        att = db.query(Attachment).filter(Attachment.id == (attachment_id or "")).first()
        if (att is None or att.conversation_id != _course_scope(c.id) or not att.ready
                or (att.uploader_id != user.id and user.role != "admin")):
            raise HTTPException(status_code=400, detail="Файл не загружен для этого курса")
        url = ""
        title = title or att.name or "Файл"
    if not title:
        title = url or "Материал"
    # section_id должен принадлежать этому курсу (иначе материал уедет в чужой раздел)
    sid = int(section_id or 0)
    if sid and not db.query(CourseSection).filter(CourseSection.id == sid,
                                                  CourseSection.course_id == c.id).first():
        raise HTTPException(status_code=400, detail="Раздел не принадлежит этому курсу")
    m = CourseMaterial(course_id=c.id, section_id=sid, kind=kind, title=title, url=url,
                       file_path=att.id if att is not None else "",
                       position=0, created_at=_now_iso())
    db.add(m); c.updated_at = _now_iso(); db.commit()
    if att is not None:
        audit.log(db, actor=user.login, role=user.role, action="course.file",
                  target=f"курс #{c.id}", detail=f"{att.name} ({int(att.size or 0)} байт)")
    return {"id": m.id}


@router.get("/courses/{course_id}/materials/{material_id}/file")
def course_file_url(course_id: int, material_id: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Ссылка на скачивание файла материала — тем, кто видит курс, и на минуты."""
    c = _course_or_404(db, course_id)
    if not _can_view(db, user, c):
        raise HTTPException(status_code=403, detail="Курс вам недоступен")
    m = db.query(CourseMaterial).filter(CourseMaterial.id == material_id,
                                        CourseMaterial.course_id == c.id).first()
    a = (db.query(Attachment).filter(Attachment.id == (m.file_path or "")).first()
         if m is not None and (m.kind or "") == "file" else None)
    if a is None or not a.ready or a.conversation_id != _course_scope(c.id):
        raise HTTPException(status_code=404, detail="Файл не найден")
    return {"url": signed_download(a), "name": a.name or "", "mime": a.mime or ""}


@router.post("/courses/{course_id}/assignments")
def add_assignment(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                   title: str = Body(..., embed=True), due_date: str = Body("", embed=True),
                   description: str = Body("", embed=True), url: str = Body("", embed=True)):
    c = _course_or_404(db, course_id)
    _require_edit(db, user, c)
    title = (title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Нужно название задания")
    a = CourseAssignment(course_id=c.id, title=title, due_date=(due_date or "").strip(),
                         description=(description or "").strip(), url=(url or "").strip(),
                         teacher_id=user.id, created_at=_now_iso())
    db.add(a); c.updated_at = _now_iso(); db.commit()
    return {"id": a.id}


@router.delete("/courses/{course_id}/materials/{material_id}")
def delete_material(course_id: int, material_id: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    c = _course_or_404(db, course_id)
    _require_edit(db, user, c)
    m = db.query(CourseMaterial).filter(CourseMaterial.id == material_id,
                                        CourseMaterial.course_id == c.id).first()
    if m:
        att_id = m.file_path if (m.kind or "") == "file" else ""
        db.delete(m); c.updated_at = _now_iso(); db.commit()
        _drop_course_file(db, c.id, att_id)
    return {"ok": True}


def _drop_course_file(db: Session, cid: int, att_id: str) -> None:
    """Удалить файл материала, если на него не ссылается больше ни один материал курса.

    ⚠️ В отличие от беседы, файл курса хранить после удаления незачем: у сообщения его
    держит модерация (жалоба обязана показать оригинал), у материала такой причины нет,
    а сирота в хранилище — чужие байты, за которые платит колледж."""
    if not att_id:
        return
    if db.query(CourseMaterial).filter(CourseMaterial.file_path == att_id).count():
        return
    a = db.query(Attachment).filter(Attachment.id == att_id,
                                    Attachment.conversation_id == _course_scope(cid)).first()
    if a is None:
        return
    try:
        from ... import storage
        storage.remove(a.id, a.storage_key)
    except Exception as e:      # noqa: BLE001 — не удалился объект: запись всё равно уберём
        print(f"[courses] файл {a.id} не удалён из хранилища: {e}")
    db.delete(a)
    db.commit()


@router.delete("/courses/{course_id}/sections/{section_id}")
def delete_section(course_id: int, section_id: int, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Удалить раздел. Материалы раздела НЕ удаляем — переносим «вне раздела» (section_id=0),
    иначе клик по разделу молча уносил бы вложенные материалы студента."""
    c = _course_or_404(db, course_id)
    _require_edit(db, user, c)
    s = db.query(CourseSection).filter(CourseSection.id == section_id,
                                       CourseSection.course_id == c.id).first()
    if s:
        for m in db.query(CourseMaterial).filter(CourseMaterial.course_id == c.id,
                                                 CourseMaterial.section_id == section_id).all():
            m.section_id = 0
        db.delete(s); c.updated_at = _now_iso(); db.commit()
    return {"ok": True}


@router.delete("/courses/{course_id}/assignments/{assignment_id}")
def delete_assignment(course_id: int, assignment_id: int, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    c = _course_or_404(db, course_id)
    _require_edit(db, user, c)
    a = db.query(CourseAssignment).filter(CourseAssignment.id == assignment_id,
                                          CourseAssignment.course_id == c.id).first()
    if a:
        db.delete(a); c.updated_at = _now_iso(); db.commit()
    return {"ok": True}


@router.delete("/courses/{course_id}")
def archive_course(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """АРХИВИРУЕМ, а не удаляем жёстко: курс — учебный документ, а материалы/задания могут
    быть на виду у студентов. Разархивировать — PATCH archived=false (админ/автор)."""
    c = _course_or_404(db, course_id)
    if user.role == "admin":
        pass
    elif user.role == "teacher" and user.id in _author_ids(db, c.id):
        pass
    else:
        raise HTTPException(status_code=403, detail="Архивировать курс может только его автор или админ")
    c.archived = True; c.updated_at = _now_iso(); db.commit()
    audit.log(db, actor=user.login, action="course.archive", target=str(c.id))
    return {"ok": True}
