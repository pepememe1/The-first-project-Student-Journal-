"""
web.py — READ-представления для веб-версии (SPA). Всё СТРОГО по роли.

Зачем отдельно от /sync: pull отдаёт все строки всех таблиц (включая password_hash и
чужие оценки) — в браузер это выгружать нельзя. Здесь сервер отдаёт только то, что
роль вправе видеть, уже в готовом для UI виде. Средний балл считается через grading.py
(единый источник), поэтому цифры совпадают с десктопом.

Пишущих операций тут нет — оценки по-прежнему ставит десктоп через /sync/push.
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User, Group, Subject, Lesson, Grade
from .. import webdata as W

router = APIRouter(prefix="/web", tags=["web"])


def _require(role: str, user: User):
    if user.role != role:
        raise HTTPException(status_code=403, detail=f"Доступно только для роли «{role}»")


def _mood_by_avg(avg: float) -> str:
    #Настроение маскота по среднему баллу (как эмоции Вектора в десктопе).
    if avg <= 0:
        return "neutral"
    if avg < 3:
        return "sad"
    if avg < 4:
        return "neutral"
    return "happy"


# СТУДЕНТ ──────────────────────────────────────────────────────────────────────
@router.get("/student/overview")
def student_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Витрина студента: средний балл, свежие оценки, счётчик задолженностей."""
    _require("student", user)
    cfg = W.load_config(db)
    lessons = W.group_lessons(db, user.group_name)
    by_id = {l.id: l for l in lessons}
    records = W.student_records(db, user.surname, user.name)

    #Свежие оценки — по серверной метке времени, только реальные занятия своей группы.
    recent_rows = db.query(Grade).filter(
        Grade.student_f == user.surname, Grade.student_n == user.name,
        Grade.deleted == False).order_by(Grade.updated_at.desc()).limit(30).all()  # noqa: E712
    recent = []
    for g in recent_rows:
        l = by_id.get(g.lesson_id)
        if not l or not g.grade:
            continue
        recent.append({"subject": l.subject, "topic": l.topic, "date": l.date, "grade": g.grade})
        if len(recent) >= 6:
            break

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    grades_month = db.query(Grade).filter(
        Grade.student_f == user.surname, Grade.student_n == user.name,
        Grade.deleted == False, Grade.updated_at >= cutoff).count()  # noqa: E712

    return {
        "name": W.display_name(user),
        "group": user.group_name,
        "average": W.average(lessons, records, cfg),
        "grades_month": grades_month,
        "next_lesson": None,  # появится с интеграцией расписания
        "debts": len(W.debts(lessons, records)),
        "recent": recent,
    }


@router.get("/student/journal")
def student_journal(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Журнал студента: занятия сгруппированы по предметам, у каждого — своя оценка."""
    _require("student", user)
    cfg = W.load_config(db)
    lessons = W.group_lessons(db, user.group_name)
    records = W.student_records(db, user.surname, user.name)

    from collections import OrderedDict
    buckets = OrderedDict()
    for l in lessons:
        buckets.setdefault(l.subject, []).append(l)

    subjects = []
    for subj, ls in buckets.items():
        items = []
        for l in ls:
            entry = {"id": l.id, "type": l.type, "number": l.number,
                     "topic": l.topic, "date": l.date, "grade": records.get(l.id, "")}
            if l.type == "Экзамен":
                entry["latest"] = W.grading.latest_exam_value(l.id, records)
            items.append(entry)
        subjects.append({"subject": subj, "lessons": items,
                         "average": W.average(ls, records, cfg)})

    return {"group": user.group_name, "subjects": subjects,
            "methodology": W.grading.methodology_text(cfg)}


@router.get("/student/stats")
def student_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Статистика студента: общий средний, по предметам, пропуски, задолженности."""
    _require("student", user)
    cfg = W.load_config(db)
    lessons = W.group_lessons(db, user.group_name)
    records = W.student_records(db, user.surname, user.name)
    return {
        "average": W.average(lessons, records, cfg),
        "per_subject": W.per_subject_averages(lessons, records, cfg),
        "absences": W.absences(lessons, records),
        "debts": W.debts(lessons, records),
    }


# ПРЕПОДАВАТЕЛЬ ──────────────────────────────────────────────────────────────────
@router.get("/teacher/overview")
def teacher_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require("teacher", user)
    subjects = list(user.subjects or [])
    return {"name": W.display_name(user), "subjects": subjects,
            "groups": W.teacher_groups(db, subjects)}


def _teacher_check_subject(user: User, subject: str):
    """Преподаватель работает только со СВОИМИ предметами (row-level scope, как в push)."""
    if subject not in (user.subjects or []):
        raise HTTPException(status_code=403, detail="Предмет вне вашей нагрузки")


@router.get("/teacher/journal")
def teacher_journal(group: str = Query(...), subject: str = Query(...),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Журнал группы по одному предмету преподавателя: студенты × занятия × оценки."""
    _require("teacher", user)
    _teacher_check_subject(user, subject)
    cfg = W.load_config(db)
    lessons = W.group_lessons(db, group, subject)
    studs = W.students_in_group(db, group)
    rows = []
    for s in studs:
        recs = W.student_records(db, s.surname, s.name)
        rows.append({"surname": s.surname, "name": s.name,
                     "grades": {l.id: recs.get(l.id, "") for l in lessons},
                     "average": W.average(lessons, recs, cfg)})
    return {
        "group": group, "subject": subject,
        "lessons": [{"id": l.id, "type": l.type, "number": l.number,
                     "topic": l.topic, "date": l.date} for l in lessons],
        "students": rows,
    }


@router.get("/teacher/students")
def teacher_students(group: str = Query(...),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Студенты группы со средним по предметам преподавателя (в этой группе)."""
    _require("teacher", user)
    cfg = W.load_config(db)
    subjects = set(user.subjects or [])
    #Средний считаем только по занятиям СВОИХ предметов — чужие данные не раскрываем.
    lessons = [l for l in W.group_lessons(db, group) if l.subject in subjects]
    out = []
    for s in W.students_in_group(db, group):
        recs = W.student_records(db, s.surname, s.name)
        out.append({"surname": s.surname, "name": s.name,
                    "average": W.average(lessons, recs, cfg)})
    return {"group": group, "students": out}


@router.get("/teacher/stats")
def teacher_stats(group: str = Query(...), subject: str = Query(...),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Средний по группе за предмет преподавателя."""
    _require("teacher", user)
    _teacher_check_subject(user, subject)
    cfg = W.load_config(db)
    lessons = W.group_lessons(db, group, subject)
    studs = W.students_in_group(db, group)
    vals = [W.average(lessons, W.student_records(db, s.surname, s.name), cfg) for s in studs]
    vals = [v for v in vals if v > 0]
    group_avg = round(sum(vals) / len(vals), 2) if vals else 0.0
    return {"group": group, "subject": subject, "students": len(studs),
            "group_average": group_avg, "lessons": len(lessons)}


# АДМИНИСТРАТОР ───────────────────────────────────────────────────────────────────
@router.get("/admin/overview")
def admin_overview(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Сводка по учреждению — счётчики сущностей."""
    def count(model, **flt):
        q = db.query(model).filter(model.deleted == False)  # noqa: E712
        for k, v in flt.items():
            q = q.filter(getattr(model, k) == v)
        return q.count()
    return {
        "teachers": count(User, role="teacher"),
        "students": count(User, role="student"),
        "admins": count(User, role="admin"),
        "groups": count(Group),
        "subjects": count(Subject),
        "lessons": count(Lesson),
        "grades": count(Grade),
    }


@router.get("/admin/teachers")
def admin_teachers(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(User).filter(
        User.role == "teacher", User.deleted == False).order_by(User.full_name).all()  # noqa: E712
    return {"teachers": [{"login": u.login, "name": W.display_name(u),
                          "subjects": list(u.subjects or [])} for u in rows]}


@router.get("/admin/students")
def admin_students(group: str = Query(""),
                   _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(User).filter(User.role == "student", User.deleted == False)  # noqa: E712
    if group:
        q = q.filter(User.group_name == group)
    rows = q.order_by(User.group_name, User.surname, User.name).all()
    return {"students": [{"login": u.login, "surname": u.surname, "name": u.name,
                          "group": u.group_name} for u in rows]}


@router.get("/admin/groups")
def admin_groups(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(Group).filter(Group.deleted == False).order_by(Group.name).all()  # noqa: E712
    out = []
    for g in rows:
        n = db.query(User).filter(User.role == "student", User.group_name == g.name,
                                  User.deleted == False).count()  # noqa: E712
        out.append({"name": g.name, "subjects": list(g.subjects or []), "students": n})
    return {"groups": out}


@router.get("/admin/subjects")
def admin_subjects(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(Subject).filter(Subject.deleted == False).order_by(Subject.name).all()  # noqa: E712
    return {"subjects": [{"name": s.name} for s in rows]}


# РАСПИСАНИЕ ──────────────────────────────────────────────────────────────────────
# Заглушка: снимок расписания тянется с portal.esstu.ru. Серверная интеграция парсера
# (schedule/) — следующий шаг; сейчас отдаём валидный пустой ответ, чтобы SPA не падал.
@router.get("/schedule/groups")
def schedule_groups(user: User = Depends(get_current_user)):
    return {"groups": [], "note": "Интеграция расписания ВСГУТУ подключается на сервере."}


@router.get("/schedule")
def schedule_get(group: str = Query(""), user: User = Depends(get_current_user)):
    return {"group": group, "days": [],
            "note": "Интеграция расписания ВСГУТУ подключается на сервере."}


# «ВЕКТОР» ─────────────────────────────────────────────────────────────────────────
@router.post("/vector/ask")
def vector_ask(payload: dict = Body(...),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Серверный «Вектор». ПРИНЦИП тот же, что в десктопе: цифры берутся из реальных
    данных (SQL), модель их НЕ выдумывает. Пока без LLM-переформулировки — ответ
    собирает локальный шаблонизатор по фактам (LLM-озвучка через privacy→GigaChat —
    следующий шаг). Студент видит только свои данные (privacy)."""
    msg = (payload.get("message") or "").strip().lower()
    cfg = W.load_config(db)

    if user.role == "student":
        lessons = W.group_lessons(db, user.group_name)
        records = W.student_records(db, user.surname, user.name)
        avg = W.average(lessons, records, cfg)

        if any(k in msg for k in ("долг", "задолж", "хвост", "не сдал")):
            d = W.debts(lessons, records)
            text = "Задолженностей нет — так держать!" if not d else \
                "Есть задолженности: " + "; ".join(d) + "."
            mood = "happy" if not d else "sad"
        elif any(k in msg for k in ("пропуск", "прогул", "посещ", "отсутств")):
            a = W.absences(lessons, records)
            text = (f"Пропусков всего: {a['всего']} "
                    f"(Н: {a['Н']}, Б: {a['Б']}, О: {a['О']}).")
            mood = "neutral" if a["всего"] else "happy"
        elif any(k in msg for k in ("средн", "балл", "оцен", "успеваем")):
            text = f"Ваш средний балл — {avg}. " + W.grading.methodology_text(cfg)
            mood = _mood_by_avg(avg)
        elif any(k in msg for k in ("привет", "здравств", "хай", "добр день", "добрый")):
            text = (f"Привет! Ваш средний балл — {avg}. "
                    "Спросите про оценки, задолженности или пропуски.")
            mood = _mood_by_avg(avg)
        else:
            text = ("Я беру цифры из ваших реальных данных. Спросите: «какой мой "
                    "средний балл», «есть ли задолженности», «сколько пропусков».")
            mood = "neutral"
        return {"text": text, "mood": mood, "facts": {"average": avg}}

    #teacher/admin — безопасная заглушка (полный конвейер аналитики — следующий шаг).
    return {"text": "Аналитика по группам и студентам для персонала подключается на "
                    "сервере (анти-галлюцинационный конвейер).",
            "mood": "neutral", "facts": {}}
