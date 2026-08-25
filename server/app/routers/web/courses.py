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

MVP: материалы — ссылки (`kind='link'`) и текст. Загрузка файлов-материалов — следующий
шаг через уже готовую инфраструктуру вложений `app/storage.py` (та же, что у мессенджера:
режим выбирает машина по свободному месту/ключам S3, файл идёт мимо нашего сервера).
"""
from ._common import *  # noqa: F401,F403  (router, get_current_user, get_db, User, W, _now_iso, ...)
from ...models import (Course, CourseAuthor, CourseSection, CourseMaterial,
                       CourseAssignment, ParentLink)


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


def _material_out(m: CourseMaterial) -> dict:
    return {"id": m.id, "section_id": m.section_id or 0, "kind": m.kind or "link",
            "title": m.title or "", "url": m.url or "", "position": m.position or 0}


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
    by_section = {}
    orphan = []
    for m in sorted(mats, key=lambda x: (x.position or 0, x.id)):
        (by_section.setdefault(m.section_id, []) if m.section_id else orphan).append(_material_out(m))

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


@router.post("/courses/{course_id}/materials")
def add_material(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 title: str = Body(..., embed=True), url: str = Body("", embed=True),
                 kind: str = Body("link", embed=True), section_id: int = Body(0, embed=True)):
    """Добавить материал-ссылку/текст. kind='file' пока не поддержан (загрузка файлов — отдельно)."""
    c = _course_or_404(db, course_id)
    _require_edit(db, user, c)
    kind = (kind or "link").strip()
    if kind not in ("link", "text"):
        raise HTTPException(status_code=400, detail="Пока поддержаны материалы-ссылки и текст")
    title = (title or "").strip()
    url = (url or "").strip()
    if kind == "link" and not url:
        raise HTTPException(status_code=400, detail="Нужна ссылка на материал")
    if not title:
        title = url or "Материал"
    # section_id должен принадлежать этому курсу (иначе материал уедет в чужой раздел)
    sid = int(section_id or 0)
    if sid and not db.query(CourseSection).filter(CourseSection.id == sid,
                                                  CourseSection.course_id == c.id).first():
        raise HTTPException(status_code=400, detail="Раздел не принадлежит этому курсу")
    m = CourseMaterial(course_id=c.id, section_id=sid, kind=kind, title=title, url=url,
                       position=0, created_at=_now_iso())
    db.add(m); c.updated_at = _now_iso(); db.commit()
    return {"id": m.id}


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
        db.delete(m); c.updated_at = _now_iso(); db.commit()
    return {"ok": True}


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
