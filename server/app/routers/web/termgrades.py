"""
termgrades.py — Итоговые оценки за семестр и ведомости промежуточной аттестации.

Часть пакета `routers/web` (разрезан в 3.6: один файл на 4288 строк правили
62 коммита за полгода — он и был главным источником конфликтов при
одновременной работе). Общий роутер и хелперы — в `_common.py`; порядок
регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — общий router, модели, хелперы


# ИТОГОВЫЕ ОЦЕНКИ ЗА СЕМЕСТР + ВЕДОМОСТИ (промежуточная аттестация) ────────────────
def _term_grade_id(student_id, subject, year, semester):
    """ЭТАП 3: ключ считает models.term_grade_id — единый на обе платформы. Раньше
    формат собирался тут строкой из ФИО, и любое расхождение с десктопом плодило дубли."""
    from ...models import term_grade_id
    return term_grade_id(student_id, subject, year, semester)


@router.post("/teacher/term-grade")
def teacher_set_term_grade(payload: dict = Body(...),
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Преподаватель выставляет ИТОГОВУЮ оценку за семестр по СВОЕМУ предмету (текущий
    термин). Пустая = снять. Форма контроля (зачёт/экзамен/диффзачёт) — опционально."""
    _require("teacher", user)
    surname = (payload.get("surname") or "").strip()
    name = (payload.get("name") or "").strip()
    subject = (payload.get("subject") or "").strip()
    group = (payload.get("group") or "").strip()
    grade = (payload.get("grade") or "").strip()
    form = (payload.get("form") or "").strip()
    if not (surname and name and subject and group):
        raise HTTPException(status_code=400, detail="Нужны surname, name, subject, group")
    ty, ts = W.current_term(W.load_config(db))
    _teacher_check_assignment(db, user, group, subject, ty, ts)
    stud = db.query(User).filter(
        User.role == "student", User.surname == surname, User.name == name,
        User.group_name == group, User.deleted == False).first()  # noqa: E712
    if not stud:
        raise HTTPException(status_code=400, detail="Студент не найден в группе")
    gid = _term_grade_id(stud.id, subject, ty, ts)
    now = _now_iso()
    row = db.get(TermGrade, gid)
    if row is None:
        row = TermGrade(id=gid, student_f=surname, student_n=name, subject=subject,
                        year=ty, semester=ts)
        db.add(row)
    row.grade = grade
    if form:
        row.form = form
    row.updated_at = now
    row.deleted = (grade == "")
    row.student_id = stud.id        #этап 1 миграции — см. /web/teacher/grade
    db.commit()
    audit.log(db, actor=user.login, role=user.role, action="term_grade.set",
              target=f"{surname} {name}", detail=f"{subject} · {ty}·{ts} = {grade}")
    return {"ok": True, "id": gid, "grade": grade}


@router.get("/teacher/term-grades")
def teacher_term_grades(group: str = Query(...), subject: str = Query(...),
                        year: str = Query(""), semester: int = Query(0),
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Итоговые оценки группы по предмету за термин: {«surname|name»: {grade, form}}."""
    _require("teacher", user)
    ty, ts = _resolve_term(W.load_config(db), year, semester)
    _teacher_check_assignment(db, user, group, subject, ty, ts)
    rows = db.query(TermGrade).filter(
        TermGrade.subject == subject, TermGrade.year == ty,
        TermGrade.semester == ts, TermGrade.deleted == False).all()  # noqa: E712
    out = {f"{r.student_f}|{r.student_n}": {"grade": r.grade, "form": r.form} for r in rows}
    return {"group": group, "subject": subject, "term": {"year": ty, "semester": ts},
            "grades": out}


#Единый ответ-файл для xlsx/docx (Content-Disposition + правильный media-type).


@router.get("/teacher/vedomost")
def teacher_vedomost(group: str = Query(...), subject: str = Query(...),
                     form: str = Query(""), fmt: str = Query("xlsx"),
                     year: str = Query(""), semester: int = Query(0),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Экзаменационно-зачётная ведомость (fmt=xlsx|docx): студенты + итоговая оценка +
    форма + дата + строка подписи. Единый стиль TNR 14, ч/б. Итоговые — из TermGrade."""
    _require("teacher", user)
    ty, ts = _resolve_term(W.load_config(db), year, semester)
    _teacher_check_assignment(db, user, group, subject, ty, ts)
    tg = {f"{r.student_f}|{r.student_n}": r for r in db.query(TermGrade).filter(
        TermGrade.subject == subject, TermGrade.year == ty,
        TermGrade.semester == ts, TermGrade.deleted == False).all()}  # noqa: E712
    rows = []
    for s in W.students_in_group(db, group):
        r = tg.get(f"{s.surname}|{s.name}")
        rows.append({"surname": s.surname, "name": s.name,
                     "patronymic": W.patronymic_of(s), "grade": (r.grade if r else "")})
    term = {"year": ty, "semester": ts}
    teacher = W.display_name(user)
    if fmt == "docx":
        from ... import docx_export
        data = docx_export.build_vedomost_docx(group, subject, term, form, rows, teacher=teacher)
    else:
        from ... import xlsx_export
        data = xlsx_export.build_vedomost_xlsx(group, subject, term, form, rows, teacher=teacher)
    return _file_response(data, f"Ведомость_{group}_{subject}_{ty}_{ts}", fmt)
