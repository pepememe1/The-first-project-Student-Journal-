"""
web.py — READ-представления для веб-версии (SPA). Всё СТРОГО по роли.

Зачем отдельно от /sync: pull отдаёт все строки всех таблиц (включая password_hash и
чужие оценки) — в браузер это выгружать нельзя. Здесь сервер отдаёт только то, что
роль вправе видеть, уже в готовом для UI виде. Средний балл считается через grading.py
(единый источник), поэтому цифры совпадают с десктопом.

Есть и ЗАПИСЬ (Phase B, в конце файла): преподаватель ставит оценки, админ ведёт CRUD
студентов. Пишем в те же таблицы и в том же формате id, что и синк десктопа — правки
подхватываются десктопом обычным pull; метку LWW ставит сервер (инвариант §3).
"""
import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User, Group, Subject, Lesson, Grade, RegistrationRequest, AuthSession
from .. import webdata as W
from .. import schedule_web
from .. import reg_utils, mailer, gost


def _contact_info(db: Session, logins: list) -> dict:
    """Для админ-списков: по логинам собираем телефон (из заявки на регистрацию) и данные
    последнего входа (время/IP/устройство из AuthSession). Возвращает {login: {...}}."""
    logins = [x for x in logins if x]
    if not logins:
        return {}
    out = {x: {"phone": "", "last_login": "", "ip": "", "device": ""} for x in logins}
    #последняя по времени сессия каждого логина
    for s in (db.query(AuthSession).filter(AuthSession.login.in_(logins))
              .order_by(AuthSession.issued_at.desc()).all()):
        rec = out.get(s.login)
        if rec is not None and not rec["last_login"]:
            rec["last_login"] = s.issued_at or ""
            rec["ip"] = s.ip or ""
            rec["device"] = (s.device_id or "")[:8]
    #телефон из заявки (у самостоятельно зарегистрированных студентов логин = email)
    for r in db.query(RegistrationRequest).filter(RegistrationRequest.email.in_(logins)).all():
        if r.phone and r.email in out and not out[r.email]["phone"]:
            out[r.email]["phone"] = gost.decrypt(r.phone)   # телефон хранится в ГОСТ-шифре
    return out

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

    # «Мои предметы» + счётчики + посещаемость (как на главной десктопа).
    from collections import OrderedDict
    subj_lessons = OrderedDict()
    for l in lessons:
        subj_lessons.setdefault(l.subject, []).append(l)
    subjects = []
    grades_total = 0
    lec_total = lec_present = 0
    for subj, ls in subj_lessons.items():
        cnt = 0
        for l in ls:
            v = (records.get(l.id) or "").strip()
            if l.type in ("Практика", "Экзамен") and v:
                cnt += 1
            elif l.type == "Лекция":
                lec_total += 1
                if v not in ("Н", "Б", "О"):
                    lec_present += 1
        grades_total += cnt
        subjects.append({"subject": subj, "grades": cnt})
    attendance = round(100 * lec_present / lec_total) if lec_total else 100

    return {
        "name": W.display_name(user),
        "group": user.group_name,
        "average": W.average(lessons, records, cfg),
        "grades_month": grades_month,
        "grades_total": grades_total,
        "subjects": subjects,
        "subjects_count": len(subjects),
        "attendance": attendance,
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


@router.get("/student/insights")
def student_insights(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Проактивные карточки Вектора для студента (порт vector/insights.py, личный
    скоуп): долги, ближайшие пересдачи, пропуски, средний. Все числа — из БД."""
    _require("student", user)
    cfg = W.load_config(db)
    lessons = W.group_lessons(db, user.group_name)
    records = W.student_records(db, user.surname, user.name)
    avg = W.average(lessons, records, cfg)
    cards = []

    d = W.debts(lessons, records)
    if d:
        cards.append({"severity": "warn", "icon": "⚠️", "title": "Незакрытые задолженности",
                      "detail": "; ".join(d[:3]) + ("…" if len(d) > 3 else "") + ".",
                      "action": "Уточните у преподавателя дату пересдачи"})

    #Назначенные пересдачи экзаменов, которые студент ещё не закрыл.
    for l in lessons:
        if l.type == "Экзамен" and l.retake_date:
            base = (records.get(l.id) or "").strip()
            retake = (records.get(l.id + "_retake") or "").strip()
            failed = base.startswith(("2", "Н")) or "Не зачтено" in base
            if failed and not retake:
                cards.append({"severity": "alert", "icon": "📅",
                              "title": f"Пересдача: {l.subject}",
                              "detail": f"Назначена на {l.retake_date} (экзамен №{l.number}).",
                              "action": "Подготовьтесь заранее"})

    a = W.absences(lessons, records)
    if a["всего"] >= 10:
        cards.append({"severity": "warn", "icon": "🕒", "title": "Много пропусков",
                      "detail": f"Всего {a['всего']} ч (Н: {a['Н']}, Б: {a['Б']}, О: {a['О']}).",
                      "action": "Не пропускайте ближайшие пары"})

    if avg >= 4.5:
        cards.append({"severity": "info", "icon": "🎉", "title": "Отличная успеваемость",
                      "detail": f"Средний балл {avg} — так держать!"})
    elif 0 < avg < 3:
        cards.append({"severity": "alert", "icon": "🚨", "title": "Средний ниже 3",
                      "detail": f"Сейчас {avg}. Есть риск задолженностей по итогам.",
                      "action": "Разберите сложные темы с Вектором"})

    if not cards:
        cards.append({"severity": "info", "icon": "✅", "title": "Всё в порядке",
                      "detail": "Долгов и тревожных сигналов нет — так держать!"})
    return {"cards": cards, "mood": _mood_by_avg(avg)}


@router.get("/teacher/insights")
def teacher_insights(group: str = Query(...),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Карточки по группе для преподавателя (порт vector/insights.compute_insights):
    средний группы, должники, зона риска, доля пропусков — по СВОИМ предметам."""
    _require("teacher", user)
    cfg = W.load_config(db)
    subjects = set(user.subjects or [])
    lessons = [l for l in W.group_lessons(db, group) if l.subject in subjects]
    studs = W.students_in_group(db, group)
    cards = []

    vals, debtors, risky, absc_total = [], 0, 0, 0
    for s in studs:
        recs = W.student_records(db, s.surname, s.name)
        a = W.average(lessons, recs, cfg)
        if a > 0:
            vals.append(a)
        if W.debts(lessons, recs):
            debtors += 1
        if 0 < a < 3:
            risky += 1
        absc_total += W.absences(lessons, recs)["всего"]

    if vals:
        gavg = round(sum(vals) / len(vals), 2)
        level = "хороший уровень" if gavg >= 4 else ("средний уровень" if gavg >= 3
                                                     else "ниже нормы, стоит подтянуть")
        cards.append({"severity": "info" if gavg >= 3 else "warn", "icon": "📊",
                      "title": f"Средний балл группы {group}",
                      "detail": f"{gavg} — {level}."})
    if debtors:
        cards.append({"severity": "warn", "icon": "⚠️", "title": "Незакрытые задолженности",
                      "detail": f"Должников: {debtors}. Стоит назначить пересдачи.",
                      "action": "Проверьте журнал"})
    if risky:
        cards.append({"severity": "alert", "icon": "🚨", "title": "Студенты в зоне риска",
                      "detail": f"{risky} студ. со средним < 3.",
                      "action": "Связаться с куратором группы"})
    if studs and absc_total and round(absc_total / len(studs), 1) >= 5:
        cards.append({"severity": "warn", "icon": "🕒", "title": "Высокая доля пропусков",
                      "detail": f"В среднем {round(absc_total / len(studs), 1)} ч на студента."})
    if not cards:
        cards.append({"severity": "info", "icon": "✅", "title": "Всё спокойно",
                      "detail": f"По группе {group} тревожных сигналов нет."})
    return {"cards": cards}


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
    #Ключи пересдач экзаменов (как в десктопе: <id>_retake, дальше — _retake_N по extra).
    retake_keys = []
    for l in lessons:
        if l.type == "Экзамен" and l.retake_date:
            retake_keys.append(l.id + "_retake")
            for n in range(2, 6):
                if (l.extra or {}).get(f"retake_date_{n}"):
                    retake_keys.append(f"{l.id}_retake_{n}")
    rows = []
    for s in studs:
        recs = W.student_records(db, s.surname, s.name)
        grades = {l.id: recs.get(l.id, "") for l in lessons}
        grades.update({k: recs.get(k, "") for k in retake_keys})
        rows.append({"surname": s.surname, "name": s.name, "grades": grades,
                     "average": W.average(lessons, recs, cfg)})
    return {
        "group": group, "subject": subject,
        "lessons": [{"id": l.id, "type": l.type, "number": l.number,
                     "topic": l.topic, "date": l.date, "hour": l.hour,
                     "retake_date": l.retake_date, "extra": l.extra or {}}
                    for l in lessons],
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
    info = _contact_info(db, [u.login for u in rows])
    return {"teachers": [dict(
        {"login": u.login, "name": W.display_name(u), "subjects": list(u.subjects or [])},
        **info.get(u.login, {})) for u in rows]}


@router.get("/admin/students")
def admin_students(group: str = Query(""),
                   _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(User).filter(User.role == "student", User.deleted == False)  # noqa: E712
    if group:
        q = q.filter(User.group_name == group)
    rows = q.order_by(User.group_name, User.surname, User.name).all()
    info = _contact_info(db, [u.login for u in rows])
    return {"students": [dict(
        {"login": u.login, "surname": u.surname, "name": u.name, "group": u.group_name},
        **info.get(u.login, {})) for u in rows]}


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
# Снимок тянется с portal.esstu.ru серверным парсером (schedule_web, TTL-кэш). Данные
# публичные, ПДн не участвуют. Оффлайн/ошибка → пустой снимок (200), SPA покажет заглушку.
@router.get("/schedule/groups")
def schedule_groups(user: User = Depends(get_current_user)):
    return {"groups": schedule_web.list_groups()}


@router.get("/schedule/teacher")
def schedule_teacher(name: str = Query(""), user: User = Depends(get_current_user)):
    """Расписание ПРЕПОДАВАТЕЛЯ (пункт 2). Без name — пробуем сматчить ФИО текущего
    пользователя со спарсенными преподавателями (фамилия+инициалы). Полный снимок
    строится лениво в фоне: пока он готовится — {building: true}, клиент подождёт."""
    snap, building = schedule_web.full_state()
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


@router.get("/schedule")
def schedule_get(group: str = Query(""), user: User = Depends(get_current_user)):
    g = (group or user.group_name or "").strip()
    data = schedule_web.get_group(g) if g else None
    return {
        "group": g,
        "week": schedule_web.current_week_parity(),
        "schedule": data,           # dict GroupSchedule.to_dict() или null
        "available": data is not None,
    }


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

    def has(*keys):
        return any(k in msg for k in keys)

    #В ответе ВСЕГДА возвращаем intent — по нему клиент выбирает эмоцию маскота ровно как
    #emotes.pick() в десктопе (задействуются все 30 спрайтов: debtors/absences → предупреж,
    #hello → радость+поздрав, sad → грусть+подбадрив и т.д.).
    if user.role == "student":
        lessons = W.group_lessons(db, user.group_name)
        records = W.student_records(db, user.surname, user.name)
        avg = W.average(lessons, records, cfg)
        if has("долг", "задолж", "хвост", "не сдал"):
            d = W.debts(lessons, records)
            text = "Задолженностей нет — так держать!" if not d else \
                "Есть задолженности: " + "; ".join(d) + "."
            return {"text": text, "mood": "happy" if not d else "sad",
                    "intent": "debtors", "facts": {"debts": len(d)}}
        if has("пропуск", "прогул", "посещ", "отсутств"):
            a = W.absences(lessons, records)
            return {"text": f"Пропусков всего: {a['всего']} (Н: {a['Н']}, Б: {a['Б']}, О: {a['О']}).",
                    "mood": "neutral" if a["всего"] else "happy",
                    "intent": "absences", "facts": a}
        if has("средн", "балл", "оцен", "успеваем"):
            return {"text": f"Ваш средний балл — {avg}. " + W.grading.methodology_text(cfg),
                    "mood": _mood_by_avg(avg), "intent": "average", "facts": {"average": avg}}
        if has("привет", "здравств", "хай", "добр день", "добрый"):
            return {"text": f"Привет! Ваш средний балл — {avg}. "
                            "Спросите про оценки, задолженности или пропуски.",
                    "mood": _mood_by_avg(avg), "intent": "hello", "facts": {"average": avg}}
        if has("спасиб", "благодар"):
            return {"text": "Всегда рад помочь! 🐯", "mood": "happy", "intent": "thanks", "facts": {}}
        return {"text": "Я беру цифры из ваших реальных данных. Спросите: «какой мой средний "
                        "балл», «есть ли задолженности», «сколько пропусков».",
                "mood": "neutral", "intent": "help", "facts": {}}

    if user.role == "teacher":
        subjects = set(user.subjects or [])
        groups = W.teacher_groups(db, subjects)
        per, risk = [], 0
        for g in groups:
            gl = [l for l in W.group_lessons(db, g) if l.subject in subjects]
            vals = []
            for s in W.students_in_group(db, g):
                a = W.average(gl, W.student_records(db, s.surname, s.name), cfg)
                if 0 < a < 3:
                    risk += 1
                if a > 0:
                    vals.append(a)
            per.append((g, round(sum(vals) / len(vals), 2) if vals else 0.0))
        if has("риск", "должник", "долг", "отстаю", "слаб", "двоеч", "хвост"):
            return {"text": (f"В зоне риска (средний ниже 3) сейчас {risk} студ." if risk
                             else "Отстающих (средний ниже 3) нет — группы идут ровно."),
                    "mood": "sad" if risk else "happy",
                    "intent": "at_risk", "facts": {"at_risk": risk}}
        if per:
            body = "; ".join(f"{g}: {ga}" for g, ga in per)
            return {"text": f"Средний по вашим группам — {body}. Студентов в зоне риска: {risk}.",
                    "mood": "neutral", "intent": "group_stats",
                    "facts": {"groups": len(per), "at_risk": risk}}
        return {"text": "За вами пока нет групп с занятиями по вашим предметам.",
                "mood": "neutral", "intent": "help", "facts": {}}

    #admin — агрегаты по заведению (только счётчики, без чужих ПДн в тексте).
    n_students = db.query(User).filter(User.role == "student", User.deleted == False).count()  # noqa: E712
    n_teachers = db.query(User).filter(User.role == "teacher", User.deleted == False).count()  # noqa: E712
    n_groups = db.query(Group).filter(Group.deleted == False).count()  # noqa: E712
    return {"text": f"В системе: студентов — {n_students}, преподавателей — {n_teachers}, "
                    f"групп — {n_groups}. Спросите про мониторинг или конкретную группу.",
            "mood": "neutral", "intent": "group_stats",
            "facts": {"students": n_students, "teachers": n_teachers, "groups": n_groups}}


# ЗАПИСЬ (Phase B) ─────────────────────────────────────────────────────────────────
# Веб теперь не только читает. Пишем в ТЕ ЖЕ таблицы (grades/users/groups) и в ТОМ ЖЕ
# формате id, что и синк десктопа (sync_engine), поэтому десктоп подхватывает правки
# обычным pull. Метку времени для LWW ставит СЕРВЕР (инвариант §3), а не часы клиента.
def _now_iso() -> str:
    """Серверная UTC-метка updated_at для LWW (как в /sync/push)."""
    return datetime.now(timezone.utc).isoformat()


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
    _teacher_check_subject(user, lesson.subject)   #только свой предмет
    stud = db.query(User).filter(
        User.role == "student", User.surname == surname, User.name == name,
        User.group_name == lesson.group_name, User.deleted == False).first()  # noqa: E712
    if not stud:
        raise HTTPException(status_code=400, detail="Студент не найден в группе занятия")
    gid = f"{surname}|{name}|{lesson_id}"
    now = _now_iso()
    cleared = (value == "")
    row = db.get(Grade, gid)
    if row is None:
        row = Grade(id=gid, student_f=surname, student_n=name, lesson_id=lesson_id)
        db.add(row)
    row.grade = value
    row.device = "web"
    row.updated_at = now
    row.deleted = cleared
    db.commit()
    return {"ok": True, "id": gid, "grade": value, "deleted": cleared, "updated_at": now}


# --- Занятия (CRUD) --- id = str(uuid4), как создаёт десктоп (core.GradeBook) →
# десктоп подхватывает занятия pull'ом. Преподаватель ведёт только СВОИ предметы.
@router.post("/teacher/lesson")
def teacher_create_lesson(payload: dict = Body(...),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Создать занятие (пару). Номер, если не передан, — следующий по типу в этом
    журнале (как авто-нумерация в десктопе)."""
    _require("teacher", user)
    group = (payload.get("group") or "").strip()
    subject = (payload.get("subject") or "").strip()
    ltype = (payload.get("type") or "").strip()
    if not (group and subject and ltype):
        raise HTTPException(status_code=400, detail="Нужны group, subject и type")
    _teacher_check_subject(user, subject)
    number = payload.get("number")
    if not number:
        rows = db.query(Lesson.number).filter(
            Lesson.group_name == group, Lesson.subject == subject,
            Lesson.type == ltype, Lesson.deleted == False).all()  # noqa: E712
        number = (max((r[0] or 0) for r in rows) + 1) if rows else 1
    import uuid as _uuid
    lid = str(_uuid.uuid4())
    db.add(Lesson(id=lid, group_name=group, subject=subject, type=ltype,
                  number=int(number), topic=(payload.get("topic") or "").strip(),
                  date=(payload.get("date") or "").strip(),
                  retake_date=(payload.get("retake_date") or "").strip(),
                  hour=int(payload.get("hour") or 0), extra={},
                  updated_at=_now_iso(), deleted=False))
    db.commit()
    return {"ok": True, "id": lid, "number": int(number)}


@router.put("/teacher/lesson/{lesson_id}")
def teacher_update_lesson(lesson_id: str, payload: dict = Body(...),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require("teacher", user)
    row = db.get(Lesson, lesson_id)
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    _teacher_check_subject(user, row.subject)
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
    _teacher_check_subject(user, row.subject)
    row.deleted = True
    row.updated_at = _now_iso()
    db.commit()
    return {"ok": True, "id": lesson_id}


@router.get("/teacher/journal.xlsx")
def teacher_journal_xlsx(group: str = Query(...), subject: str = Query(...),
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Экспорт журнала в xlsx прямо с сайта (тот же аккуратный стиль, что в десктопе:
    Times New Roman 14, титульная шапка, цвет оценок, средний по группе)."""
    _require("teacher", user)
    _teacher_check_subject(user, subject)
    try:
        from .. import xlsx_export
    except ImportError:
        raise HTTPException(status_code=501, detail="На сервере не установлен openpyxl")
    cfg = W.load_config(db)
    lessons = W.group_lessons(db, group, subject)
    studs = W.students_in_group(db, group)
    rows = []
    for s in studs:
        recs = W.student_records(db, s.surname, s.name)
        rows.append({"surname": s.surname, "name": s.name, "records": recs,
                     "average": W.average(lessons, recs, cfg)})
    data = xlsx_export.build_journal_xlsx(group, subject, lessons, rows)
    from fastapi.responses import Response
    from urllib.parse import quote
    #HTTP-заголовки — только latin-1: кириллицу в имени файла percent-кодируем
    #(RFC 5987), иначе UnicodeEncodeError и 500. Слэши из имени группы убираем.
    fname = f"Журнал_{group}_{subject}.xlsx".replace(" ", "_").replace("/", "-")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename=journal.xlsx; filename*=UTF-8''{quote(fname)}"})


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
    name = (payload.get("name") or "").strip()
    login = (payload.get("login") or "").strip()
    group = (payload.get("group") or "").strip()
    password = payload.get("password") or ""
    if not (surname and name):
        raise HTTPException(status_code=400, detail="Нужны фамилия и имя")
    if not login:
        raise HTTPException(status_code=400, detail="Нужен логин")
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
    row.name = name
    row.group_name = group
    row.full_name = ""
    row.subjects = []
    row.group_assignments = {}
    if password:
        from ..security import hash_password
        row.password_hash = hash_password(password)
    row.updated_at = _now_iso()
    row.deleted = False
    db.commit()
    return {"ok": True, "login": login, "id": sid}


@router.put("/admin/students/{login}")
def admin_update_student(login: str, payload: dict = Body(...),
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Правка студента. Логин — ключ (id=stud:login), его не меняем: смена логина = это
    другой студент (создайте нового). Меняем ФИО/группу/пароль. Пустой пароль —
    оставляем прежний хеш."""
    sid = f"stud:{login}"
    row = db.get(User, sid)
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Студент не найден")
    if "surname" in payload:
        row.surname = (payload.get("surname") or "").strip()
    if "name" in payload:
        row.name = (payload.get("name") or "").strip()
    if "group" in payload:
        group = (payload.get("group") or "").strip()
        _ensure_group_row(db, group)
        row.group_name = group
    password = payload.get("password") or ""
    if password:
        from ..security import hash_password
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
    return {"ok": True, "login": login}


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
    row.updated_at = _now_iso()
    row.deleted = False
    db.commit()
    return {"ok": True, "name": name}


@router.put("/admin/groups/{name:path}")
def admin_update_group(name: str, payload: dict = Body(...),
                       _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Правка группы (название — ключ, не меняем). Меняем список предметов группы."""
    row = db.get(Group, f"grp:{name}")
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    if "subjects" in payload:
        row.subjects = payload.get("subjects") or []
    row.updated_at = _now_iso()
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
    return {"ok": True, "name": name}


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
            merged = sorted(set(row.subjects or []) | set(subs))
            if merged != list(row.subjects or []) or row.deleted:
                row.subjects = merged
                row.deleted = False
                row.updated_at = now
                bound += 1
    for s in all_subjects:                                   #пополняем каталог предметов
        sid = f"subj:{s}"
        if db.get(Subject, sid) is None:
            db.add(Subject(id=sid, name=s, updated_at=now, deleted=False))
    db.commit()
    return {"ok": True, "building": building, "bound": bound, "subjects": len(all_subjects)}


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
    return {"ok": True, "name": name}


@router.delete("/admin/subjects/{name:path}")
def admin_delete_subject(name: str,
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(Subject, f"subj:{name}")
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    row.deleted = True
    row.updated_at = _now_iso()
    db.commit()
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
    row.group_assignments = {}
    password = payload.get("password") or ""
    if password:
        from ..security import hash_password
        row.password_hash = hash_password(password)
    row.updated_at = _now_iso()
    row.deleted = False
    db.commit()
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
    password = payload.get("password") or ""
    if password:
        from ..security import hash_password
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
    parts = req.full_name.split()
    surname = parts[0] if parts else ""
    name = " ".join(parts[1:]) if len(parts) > 1 else ""
    from ..security import hash_password
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
    row.group_name = req.group_name
    row.subjects = []
    row.group_assignments = {}
    row.updated_at = _now_iso()
    row.deleted = False
    req.status = "approved"
    db.commit()

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
    return {"ok": True}


# --- Занятия/пары (CRUD) --- преподаватель наполняет журнал: создаёт/правит/удаляет
# пары по СВОЕМУ предмету. id — uuid (как в десктопе), пишется в таблицу lessons →
# десктоп получает через pull (_merge_lessons). Оценки цепляются к lesson_id.
def _as_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@router.post("/teacher/lesson")
def teacher_create_lesson(payload: dict = Body(...),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require("teacher", user)
    group = (payload.get("group") or "").strip()
    subject = (payload.get("subject") or "").strip()
    if not group or not subject:
        raise HTTPException(status_code=400, detail="Нужны группа и предмет")
    _teacher_check_subject(user, subject)   # только свой предмет
    import uuid
    lid = uuid.uuid4().hex
    row = Lesson(
        id=lid, group_name=group, subject=subject,
        type=(payload.get("type") or "Практика").strip(),
        number=_as_int(payload.get("number")),
        topic=(payload.get("topic") or "").strip(),
        date=(payload.get("date") or "").strip(),
        retake_date="", hour=_as_int(payload.get("hour")),
        extra={}, updated_at=_now_iso(), deleted=False)
    db.add(row)
    db.commit()
    return {"ok": True, "id": lid}


@router.put("/teacher/lesson/{lesson_id}")
def teacher_update_lesson(lesson_id: str, payload: dict = Body(...),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require("teacher", user)
    row = db.get(Lesson, lesson_id)
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    _teacher_check_subject(user, row.subject)
    if "type" in payload:
        row.type = (payload.get("type") or "").strip()
    if "number" in payload:
        row.number = _as_int(payload.get("number"))
    if "topic" in payload:
        row.topic = (payload.get("topic") or "").strip()
    if "date" in payload:
        row.date = (payload.get("date") or "").strip()
    if "hour" in payload:
        row.hour = _as_int(payload.get("hour"))
    row.updated_at = _now_iso()
    db.commit()
    return {"ok": True, "id": lesson_id}


@router.delete("/teacher/lesson/{lesson_id}")
def teacher_delete_lesson(lesson_id: str,
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require("teacher", user)
    row = db.get(Lesson, lesson_id)
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    _teacher_check_subject(user, row.subject)
    #Мягкое удаление (надгробие) → уедет в десктоп; оценки этой пары останутся в БД, но
    #в журнале не показываются (фильтр deleted). Так удаление не «воскресает» на синке.
    row.deleted = True
    row.updated_at = _now_iso()
    db.commit()
    return {"ok": True, "id": lesson_id}
