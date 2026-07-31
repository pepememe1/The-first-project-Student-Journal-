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
import os
import re
from datetime import datetime, timezone, timedelta

from fastapi import (APIRouter, Body, Depends, HTTPException, Query, Request,
                     UploadFile, File, Form)
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import (User, Group, Subject, Lesson, Grade, RegistrationRequest,
                      AuthSession, ConfigKV, TermGrade, ScheduleOverride,
                      ScheduleJointMark, schedule_override_id, joint_mark_id,
                      SubjectHours, subject_hours_id, ZetThreshold, zet_threshold_id,
                      NotifyEvent)
from .. import webdata as W
from .. import schedule_web
from .. import reg_utils, mailer, gost, audit, vector_llm
from ..parsers import esstu_parser
import vector_nlu   # общий с десктопом лексикон/классификатор (корень в sys.path через webdata)
from schedule import parser as schedule_parser   # CATEGORIES — реестр категорий портала


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


def _resolve_term(cfg: dict, year: str = "", semester=None) -> tuple:
    """Термин запроса: явные year+semester (просмотр архива) или ТЕКУЩИЙ из config.
    Так журнал/статистика по умолчанию показывают активный семестр, а прошлые —
    по явному выбору."""
    year = (year or "").strip()
    if year and semester:
        try:
            return year, int(semester)
        except (TypeError, ValueError):
            pass
    return W.current_term(cfg)


def _ensure_current_term(cfg: dict, lesson):
    """Защита от правки АРХИВА: писать (оценки/занятия) можно только в ТЕКУЩИЙ термин.
    Прошлые семестры — только чтение (перевод на курс их «замораживает»). Занятие без
    периода (легаси/десктоп до штампа) считаем текущим — не блокируем."""
    if lesson is None:
        return
    ly = (getattr(lesson, "year", "") or "").strip()
    if not ly:
        return
    cy, cs = W.current_term(cfg)
    if ly != cy or int(getattr(lesson, "semester", 0) or 0) != cs:
        raise HTTPException(
            status_code=409,
            detail="Этот семестр уже в архиве (только чтение). Правки возможны только "
                   "в текущем учебном периоде.")


# СТУДЕНТ ──────────────────────────────────────────────────────────────────────
@router.get("/student/overview")
def student_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Витрина студента: средний балл, свежие оценки, счётчик задолженностей."""
    _require("student", user)
    cfg = W.load_config(db)
    lessons = W.group_lessons(db, user.group_name)
    by_id = {l.id: l for l in lessons}
    records = W.student_records(db, user.surname, user.name, user.group_name)
    scale_map = W.lesson_scale_map(db, lessons)

    #Свежие оценки — по серверной метке времени, только реальные занятия СВОЕЙ группы.
    #Скоуп по lesson_id группы нужен и здесь: иначе оценки тёзки из другой группы могли
    #бы вытеснить свои из окна limit(30) ещё до фильтра by_id ниже (защита от тёзок).
    own_ids = set(by_id.keys())
    recent_rows = db.query(Grade).filter(
        Grade.student_f == user.surname, Grade.student_n == user.name,
        Grade.deleted == False,
        Grade.lesson_id.in_(own_ids)).order_by(Grade.updated_at.desc()).limit(30).all()  # noqa: E712
    recent = []
    for g in recent_rows:
        l = by_id.get(g.lesson_id)
        if not l or not g.grade:
            continue
        recent.append({"subject": l.subject, "topic": l.topic, "date": l.date, "grade": g.grade})
        if len(recent) >= 6:
            break

    #Счётчик оценок за месяц — тоже строго по занятиям своей группы (без тёзок из чужих).
    #Считаем по БАЗОВОМУ lesson_id, чтобы не потерять свои пересдачи (<lid>_retake).
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    month_rows = db.query(Grade.lesson_id).filter(
        Grade.student_f == user.surname, Grade.student_n == user.name,
        Grade.deleted == False, Grade.updated_at >= cutoff).all()  # noqa: E712
    grades_month = sum(1 for (lid,) in month_rows if W.base_lesson_id(lid) in own_ids)

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
        "average": W.average(lessons, records, cfg, scale=scale_map),
        "grades_month": grades_month,
        "grades_total": grades_total,
        "subjects": subjects,
        "subjects_count": len(subjects),
        "attendance": attendance,
        "next_lesson": None,  # появится с интеграцией расписания
        "debts": len(W.debts(lessons, records, scale=scale_map)),
        "recent": recent,
    }


@router.get("/student/journal")
def student_journal(year: str = Query(""), semester: int = Query(0),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Журнал студента: занятия сгруппированы по предметам, у каждого — своя оценка.
    По умолчанию — ТЕКУЩИЙ семестр; year+semester открывают архив прошлого периода."""
    _require("student", user)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    lessons = W.group_lessons(db, user.group_name, year=ty, semester=ts)
    records = W.student_records(db, user.surname, user.name, user.group_name)
    scale_map = W.lesson_scale_map(db, lessons)

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
                         "average": W.average(ls, records, cfg, scale=scale_map),
                         #«Пройдено X из Y часов» по этому предмету (0 total — не задано).
                         "hours": W.hours_progress(db, user.group_name, subj, ls, ty, ts)})

    return {"group": user.group_name, "subjects": subjects, "term": {"year": ty, "semester": ts},
            "methodology": W.grading.methodology_text(cfg)}


@router.get("/student/stats")
def student_stats(year: str = Query(""), semester: int = Query(0),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Статистика студента: общий средний, по предметам, пропуски, задолженности.
    По умолчанию — текущий семестр; year+semester — архив."""
    _require("student", user)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    is_archive = bool((year or "").strip() and semester)   #явно выбран прошлый семестр
    lessons = W.group_lessons(db, user.group_name, year=ty, semester=ts)
    records = W.student_records(db, user.surname, user.name, user.group_name)
    #Долги и пропуски в ДЕФОЛТНОМ виде считаем по ВСЕМ занятиям группы (как overview): иначе
    #легаси-занятия без штампа термина (десктоп до штампа) выпадают из фильтра текущего
    #термина, и реальные долги/пропуски «исчезают». В архиве — строго по выбранному термину.
    dl = lessons if is_archive else W.group_lessons(db, user.group_name)
    scale_map = W.lesson_scale_map(db, lessons if is_archive else lessons + dl)
    return {
        "term": {"year": ty, "semester": ts},
        "average": W.average(lessons, records, cfg, scale=scale_map),
        "per_subject": W.per_subject_averages(lessons, records, cfg, scale=scale_map),
        "absences": W.absences(dl, records),
        "debts": W.debts(dl, records, scale=scale_map),
    }


@router.get("/student/insights")
def student_insights(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Проактивные карточки Вектора для студента (порт vector/insights.py, личный
    скоуп): долги, ближайшие пересдачи, пропуски, средний. Все числа — из БД."""
    _require("student", user)
    cfg = W.load_config(db)
    lessons = W.group_lessons(db, user.group_name)
    records = W.student_records(db, user.surname, user.name, user.group_name)
    scale_map = W.lesson_scale_map(db, lessons)
    avg = W.average(lessons, records, cfg, scale=scale_map)
    cards = []

    d = W.debts(lessons, records, scale=scale_map)
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


@router.get("/student/zet")
def student_zet(year: str = Query(""), semester: int = Query(0),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ЗЕТ студента за термин (docs/PLAN-ZET.md). Пусто — ни один предмет группы ещё
    не получил ЗЕТ от администратора (интерфейс тогда не показывает строку вовсе).
    min_zet — порог перевода группы (для «до перевода: X ЗЕТ» в дашборде), null — куратор/
    админ его ещё не задавал."""
    _require("student", user)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    threshold = db.get(ZetThreshold, zet_threshold_id(user.group_name, ty, ts))
    min_zet = threshold.min_zet if (threshold and not threshold.deleted) else None
    return {"term": {"year": ty, "semester": ts}, "min_zet": min_zet,
            **W.zet_summary_for_student(db, user.surname, user.name, user.group_name, ty, ts)}


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
    tscale = W.teacher_scale(user)

    vals, debtors, risky, absc_total = [], 0, 0, 0
    for s in studs:
        recs = W.student_records(db, s.surname, s.name, group)
        a = W.average(lessons, recs, cfg, scale=tscale)
        if a > 0:
            vals.append(a)
        if W.debts(lessons, recs, scale=tscale):
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
    cfg = W.load_config(db)
    ty, ts = W.current_term(cfg)
    #assignments — ЯВНОЕ назначение (группа,предмет), выставленное админом в «часы по
    #предмету». groups/subjects — плоские уникальные списки для мест, которым пары не
    #нужны (Вектор-подсказки и т.п.). ⚠️ ЭТО НЕ user.subjects: препод может числиться
    #мастером пяти предметов, но видеть только те группы, что ему реально назначили —
    #баг 3.3.1, когда «предмет есть у препода» ошибочно значило «видны все группы предмета».
    pairs = W.teacher_assignments(db, user.id, ty, ts)
    return {"name": W.display_name(user),
            "assignments": [{"group": g, "subject": s} for g, s in pairs],
            "groups": sorted({g for g, _s in pairs}),
            "subjects": sorted({s for _g, s in pairs}),
            "term": {"year": ty, "semester": ts}}


def _teacher_check_assignment(db, user: User, group: str, subject: str, year: str, semester):
    """Преподаватель работает только со СВОИМИ назначениями (группа+предмет за термин),
    а не с любой группой, где просто числится его предмет — см. teacher_assignments."""
    pairs = W.teacher_assignments(db, user.id, year, semester)
    if (group, subject) not in pairs:
        raise HTTPException(status_code=403, detail="Эта группа/предмет вам не назначены")


@router.get("/teacher/journal")
def teacher_journal(group: str = Query(...), subject: str = Query(...),
                    year: str = Query(""), semester: int = Query(0),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Журнал группы по одному предмету преподавателя: студенты × занятия × оценки.
    По умолчанию — текущий семестр; year+semester открывают архив."""
    _require("teacher", user)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    _teacher_check_assignment(db, user, group, subject, ty, ts)
    tscale = W.teacher_scale(user)
    lessons = W.group_lessons(db, group, subject, year=ty, semester=ts)
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
        recs = W.student_records(db, s.surname, s.name, group)
        grades = {l.id: recs.get(l.id, "") for l in lessons}
        grades.update({k: recs.get(k, "") for k in retake_keys})
        rows.append({"surname": s.surname, "name": s.name, "grades": grades,
                     "average": W.average(lessons, recs, cfg, scale=tscale)})
    return {
        "group": group, "subject": subject, "term": {"year": ty, "semester": ts},
        #Шкала ЭТОГО преподавателя (§ролей, 3.3.1) — клиент строит из неё варианты
        #ввода оценки (grading.SCALES[scale]["values"] / scale_values(scale)).
        "scale": tscale, "scale_values": list(W.grading.scale_values(tscale)),
        "lessons": [{"id": l.id, "type": l.type, "number": l.number,
                     "topic": l.topic, "date": l.date, "hour": l.hour,
                     "retake_date": l.retake_date, "extra": l.extra or {}}
                    for l in lessons],
        "students": rows,
        #«Пройдено X из Y часов» — считается из тех же занятий, отдельный запрос не нужен.
        "hours": W.hours_progress(db, group, subject, lessons, ty, ts),
    }


@router.get("/teacher/students")
def teacher_students(group: str = Query(...),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Студенты группы со средним по предметам преподавателя (в этой группе)."""
    _require("teacher", user)
    cfg = W.load_config(db)
    ty, ts = W.current_term(cfg)
    #Средний считаем только по НАЗНАЧЕННЫМ этому преподу в ЭТОЙ группе предметам —
    #не по всем его предметам вообще (см. teacher_assignments).
    subjects = {s for g, s in W.teacher_assignments(db, user.id, ty, ts) if g == group}
    if not subjects:
        raise HTTPException(status_code=403, detail="Эта группа вам не назначена")
    lessons = [l for l in W.group_lessons(db, group) if l.subject in subjects]
    tscale = W.teacher_scale(user)
    out = []
    for s in W.students_in_group(db, group):
        recs = W.student_records(db, s.surname, s.name, group)
        out.append({"surname": s.surname, "name": s.name,
                    "average": W.average(lessons, recs, cfg, scale=tscale)})
    return {"group": group, "students": out}


@router.get("/teacher/stats")
def teacher_stats(group: str = Query(...), subject: str = Query(...),
                  year: str = Query(""), semester: int = Query(0),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Средний по группе за предмет преподавателя (по умолчанию — текущий семестр)."""
    _require("teacher", user)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    _teacher_check_assignment(db, user, group, subject, ty, ts)
    lessons = W.group_lessons(db, group, subject, year=ty, semester=ts)
    studs = W.students_in_group(db, group)
    tscale = W.teacher_scale(user)
    vals = [W.average(lessons, W.student_records(db, s.surname, s.name, group), cfg, scale=tscale)
            for s in studs]
    vals = [v for v in vals if v > 0]
    group_avg = round(sum(vals) / len(vals), 2) if vals else 0.0
    return {"group": group, "subject": subject, "term": {"year": ty, "semester": ts},
            "students": len(studs), "group_average": group_avg, "lessons": len(lessons)}


# УЧЕБНЫЙ ПЕРИОД (год/семестр) ───────────────────────────────────────────────────
@router.get("/terms")
def terms(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Доступные учебные периоды (для селектора/архива) + текущий термин."""
    cfg = W.load_config(db)
    cy, cs = W.current_term(cfg)
    return {"current": {"year": cy, "semester": cs}, "terms": W.list_terms(db)}


@router.post("/admin/term/rollover")
def admin_term_rollover(payload: dict = Body(default={}), request: Request = None,
                        _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Перевод на следующий учебный период (перевод на курс).

    Продвигает ТЕКУЩИЙ термин: семестр 1→2 (тот же год) или 2→1 (год +1). Прошлые
    занятия остаются в своём периоде и становятся read-only (архив, см. _ensure_current_term).
    Ростер/группы НЕ трогаем — новый семестр наполняется занятиями заново. Можно задать
    явные year+semester в теле. Текущий термин хранится в config (синкается на десктоп)."""
    cfg = W.load_config(db)
    cy, cs = W.current_term(cfg)
    ny = (payload.get("year") or "").strip()
    ns = payload.get("semester")
    if ny and ns:
        new_year, new_sem = ny, int(ns)
    elif cs == 1:
        new_year, new_sem = cy, 2                 #осень → весна того же года
    else:
        try:                                      #весна → осень следующего года
            a, b = cy.split("/")
            new_year = f"{int(a) + 1}/{int(b) + 1}"
        except Exception:
            new_year = cy
        new_sem = 1
    row = db.get(ConfigKV, "config")
    cur = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    cur["current_year"] = new_year
    cur["current_semester"] = new_sem
    now = _now_iso()
    if row is None:
        db.add(ConfigKV(key="config", value=cur, updated_at=now, deleted=False))
    else:
        row.value = cur
        row.updated_at = now
    db.commit()
    audit.log(db, request, actor=_admin.login, role="admin", action="term.rollover",
              detail=f"{cy}·{cs} → {new_year}·{new_sem}")
    #§12: отчёты куратора «вечны» (кнопки не удаляются), но после rollover'а старого
    #термина архивируются — новый /отчет уже не берёт значения из term'а, который
    #только что закрылся. Сбой этой пометки не должен ломать сам rollover.
    try:
        from ..models import CuratorReport
        (db.query(CuratorReport)
         .filter(CuratorReport.year == cy, CuratorReport.semester == cs,
                 CuratorReport.archived == False)  # noqa: E712
         .update({"archived": True}, synchronize_session=False))
        db.commit()
    except Exception as e:
        print(f"[curator_reports] не удалось архивировать отчёты term {cy}·{cs}: {e}")
    return {"ok": True, "previous": {"year": cy, "semester": cs},
            "current": {"year": new_year, "semester": new_sem}}


# КУРАТОР (только чтение по курируемым группам) ───────────────────────────────────
# Куратор — это teacher с непустым curated_groups. В отличие от журнала препода (только
# СВОИ предметы), куратор видит ВСЕ предметы курируемой группы, но ТОЛЬКО НА ЧТЕНИЕ.
def _curator_check(user: User, group: str):
    """Row-level: куратор видит только свои курируемые группы, иначе 403."""
    if group not in (user.curated_groups or []):
        raise HTTPException(status_code=403, detail="Группа вне вашего кураторства")


@router.get("/curator/groups")
def curator_groups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Группы, которые курирует преподаватель. Пусто → он не куратор (вкладка скрыта)."""
    _require("teacher", user)
    return {"groups": list(user.curated_groups or [])}


@router.get("/curator/subjects")
def curator_group_subjects(group: str = Query(...), year: str = Query(""), semester: int = Query(0),
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Предметы курируемой группы за термин (ВСЕ предметы группы, не только «свои»).

    group — QUERY-параметр, а НЕ path: имена групп колледжа содержат слэш («К75/1»), и в
    пути encodeURIComponent даёт «%2F», который Starlette декодирует обратно в «/» и роут
    `{group}/subjects` перестаёт матчиться — эндпоинт молча 404-ил, и вкладка куратора
    показывала «нет предметов». В query слэш проходит как обычное значение."""
    _require("teacher", user)
    _curator_check(user, group)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    subs = sorted({l.subject for l in W.group_lessons(db, group, year=ty, semester=ts) if l.subject})
    return {"group": group, "term": {"year": ty, "semester": ts}, "subjects": subs}


@router.get("/curator/group-subject")
def curator_group_subject(group: str = Query(...), subject: str = Query(...),
                          year: str = Query(""), semester: int = Query(0),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Студенты курируемой группы + оценки/средний по ЛЮБОМУ предмету группы (read-only).
    Ключевой скоуп безопасности: доступ по КУРИРУЕМОЙ ГРУППЕ, а не по предметам препода;
    запись недоступна (куратор не ставит оценки — только смотрит ведение журнала)."""
    _require("teacher", user)
    _curator_check(user, group)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    lessons = W.group_lessons(db, group, subject, year=ty, semester=ts)
    #Куратор смотрит ЧУЖОЙ предмет — шкала ведущего его преподавателя, не куратора.
    scale_map = W.lesson_scale_map(db, lessons)
    studs = W.students_in_group(db, group)
    rows = []
    for s in studs:
        recs = W.student_records(db, s.surname, s.name, group)
        grades = {l.id: recs.get(l.id, "") for l in lessons}
        rows.append({"surname": s.surname, "name": s.name,
                     "first_name": W.first_name(s), "patronymic": W.patronymic_of(s),
                     "grades": grades, "average": W.average(lessons, recs, cfg, scale=scale_map)})
    return {
        "group": group, "subject": subject, "term": {"year": ty, "semester": ts},
        "lessons": [{"id": l.id, "type": l.type, "number": l.number,
                     "topic": l.topic, "date": l.date} for l in lessons],
        "students": rows,
    }


@router.get("/curator/zet-report")
def curator_zet_report(group: str = Query(...), year: str = Query(""), semester: int = Query(0),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Таблица перевода на курс по ЗЕТ (docs/PLAN-ZET.md §7.4) — «главная фича» отчёта
    куратора. group — QUERY (не path): имена групп содержат слэш («К75/1»), см. урок
    у /curator/subjects. Порог — ZetThreshold этой группы/термина, если куратор/админ
    его ещё не задал — eligible получают все (см. study_hours.group_zet_report)."""
    _require("teacher", user)
    _curator_check(user, group)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    threshold = db.get(ZetThreshold, zet_threshold_id(group, ty, ts))
    min_zet = threshold.min_zet if (threshold and not threshold.deleted) else None
    return {"group": group, "term": {"year": ty, "semester": ts}, "min_zet": min_zet,
            "students": W.group_zet_report(db, group, ty, ts, min_zet)}


def _admin_or_curator_check(user: User, group: str):
    """Порог перевода и сама кнопка «Перевести» (docs/PLAN-ZET.md) — админ ИЛИ КУРАТОР
    именно этой группы. В отличие от журнала (куратор строго read-only), решение о
    переводе на курс — то, что куратор принимает по своим студентам каждый семестр;
    держать его только за админом означало бы гонять администратора за каждой группой."""
    if user.role == "admin":
        return
    if user.role == "teacher" and group in (user.curated_groups or []):
        return
    raise HTTPException(status_code=403, detail="Доступно администратору или куратору группы")


@router.get("/admin/zet-thresholds")
def admin_get_zet_threshold(group: str = Query(...), year: str = Query(""),
                            semester: int = Query(0),
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Порог перевода группы на курс (docs/PLAN-ZET.md §7.2). group — QUERY (слэш в имени
    группы, тот же урок, что и везде)."""
    _admin_or_curator_check(user, group)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    row = db.get(ZetThreshold, zet_threshold_id(group, ty, ts))
    min_zet = row.min_zet if (row and not row.deleted) else None
    return {"group": group, "term": {"year": ty, "semester": ts}, "min_zet": min_zet}


@router.post("/admin/zet-thresholds")
def admin_set_zet_threshold(payload: dict = Body(...),
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Сохранить (или снять — min_zet=null) порог перевода: {group, year, semester, min_zet}."""
    group = (payload.get("group") or "").strip()
    if not group:
        raise HTTPException(status_code=400, detail="Нужна group")
    _admin_or_curator_check(user, group)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, payload.get("year") or "", int(payload.get("semester") or 0))
    hid = zet_threshold_id(group, ty, ts)
    mz = payload.get("min_zet")
    row = db.get(ZetThreshold, hid)
    if mz is None or mz == "":
        if row is not None:
            row.deleted = True
            row.updated_at = _now_iso()
            db.commit()
        return {"ok": True, "min_zet": None, "term": {"year": ty, "semester": ts}}
    try:
        mz = float(mz)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="min_zet должен быть числом")
    if mz < 0:
        raise HTTPException(status_code=400, detail="min_zet не может быть отрицательным")
    if row is None:
        row = ZetThreshold(id=hid, group_name=group, year=ty, semester=ts)
        db.add(row)
    row.min_zet = mz
    row.updated_by = user.login
    row.updated_at = _now_iso()
    row.deleted = False
    db.commit()
    return {"ok": True, "min_zet": mz, "term": {"year": ty, "semester": ts}}


@router.post("/admin/groups/promote")
def admin_promote_group(payload: dict = Body(...), request: Request = None,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Перевод на следующий курс (docs/PLAN-ZET.md §7.4) — только явной кнопкой, только
    студентов с eligible=true (сервер САМ перепроверяет, клиентскому флагу не доверяет).
    group/year/semester/student_ids — В ТЕЛЕ (не в пути — слэш в имени группы)."""
    group = (payload.get("group") or "").strip()
    student_ids = payload.get("student_ids") or []
    if not group or not isinstance(student_ids, list) or not student_ids:
        raise HTTPException(status_code=400, detail="Нужны group и student_ids")
    _admin_or_curator_check(user, group)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, payload.get("year") or "", int(payload.get("semester") or 0))
    threshold = db.get(ZetThreshold, zet_threshold_id(group, ty, ts))
    min_zet = threshold.min_zet if (threshold and not threshold.deleted) else None
    report = {r["student_id"]: r for r in W.group_zet_report(db, group, ty, ts, min_zet)}
    promoted, rejected = [], []
    for sid in student_ids:
        r = report.get(sid)
        if r is None:
            rejected.append({"student_id": sid, "reason": "не в группе"})
        elif not r["eligible"]:
            rejected.append({"student_id": sid, "reason": f"не хватает {r['missing_zet']} ЗЕТ"})
        else:
            promoted.append(r)
    if promoted:
        names = ", ".join(r["display_name"] for r in promoted)
        audit.log(db, request, actor=user.login, role=user.role, action="group.promote",
                  target=group, detail=f"переведено: {len(promoted)} ({names})")
        try:
            from .messenger import _post_system_channel_message, _gtoken
            _post_system_channel_message(
                db, f"sys:announce:{_gtoken(group)}",
                f"Студенты переведены на следующий курс: {names}.")
        except Exception:
            pass
    return {"promoted": [{"student_id": r["student_id"], "display_name": r["display_name"]}
                         for r in promoted],
            "rejected": rejected}


@router.get("/curator/report")
def curator_report(groups: str = Query("all"), fmt: str = Query("xlsx"),
                   year: str = Query(""), semester: int = Query(0),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Сводный отчёт куратора по успеваемости (fmt=xlsx|docx).

    groups — «all» (все курируемые) ИЛИ список через запятую. КАЖДАЯ запрошенная группа
    проверяется на принадлежность к curated_groups: куратор не должен выгрузить чужую
    группу, подставив её в параметр. Пустой пересечённый список — 403 (нечего отдавать).

    В отчёте по каждой группе: список студентов, средние по предметам и общий, посещаемость
    (Н/Б/О) и число долгов — см. curator_report.collect_group."""
    from .. import curator_report as R
    _require("teacher", user)
    curated = list(user.curated_groups or [])
    if not curated:
        raise HTTPException(status_code=403, detail="Вы не куратор ни одной группы")

    if groups.strip().lower() == "all":
        chosen = curated
    else:
        asked = [g.strip() for g in groups.split(",") if g.strip()]
        #Строгий скоуп: оставляем только реально курируемые (порядок — как в curated).
        chosen = [g for g in curated if g in asked]
    if not chosen:
        raise HTTPException(status_code=403,
                            detail="Нет доступных для выгрузки групп из запрошенных")

    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    data = [R.collect_group(db, g, ty, ts, cfg) for g in chosen]
    term = {"year": ty, "semester": ts}
    blob = R.build_docx(data, term) if fmt == "docx" else R.build_xlsx(data, term)

    name = "Успеваемость_" + ("все_группы" if len(chosen) > 1 else chosen[0])
    audit.log(db, actor=user.login, role="teacher", action="curator.report",
              target=", ".join(chosen), detail=f"{fmt}, семестр {ty}/{ts}")
    return _file_response(blob, name, fmt)


# ИТОГОВЫЕ ОЦЕНКИ ЗА СЕМЕСТР + ВЕДОМОСТИ (промежуточная аттестация) ────────────────
def _term_grade_id(student_id, subject, year, semester):
    """ЭТАП 3: ключ считает models.term_grade_id — единый на обе платформы. Раньше
    формат собирался тут строкой из ФИО, и любое расхождение с десктопом плодило дубли."""
    from ..models import term_grade_id
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
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _file_response(data: bytes, base_name: str, fmt: str):
    from fastapi.responses import Response
    from urllib.parse import quote
    ext = "docx" if fmt == "docx" else "xlsx"
    media = _DOCX_MEDIA if fmt == "docx" else _XLSX_MEDIA
    fname = f"{base_name}.{ext}".replace(" ", "_").replace("/", "-")
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition":
                             f"attachment; filename=export.{ext}; filename*=UTF-8''{quote(fname)}"})


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
        from .. import docx_export
        data = docx_export.build_vedomost_docx(group, subject, term, form, rows, teacher=teacher)
    else:
        from .. import xlsx_export
        data = xlsx_export.build_vedomost_xlsx(group, subject, term, form, rows, teacher=teacher)
    return _file_response(data, f"Ведомость_{group}_{subject}_{ty}_{ts}", fmt)


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
        {"id": u.id, "login": u.login, "name": W.display_name(u),
         "subjects": list(u.subjects or []), "curated_groups": list(u.curated_groups or [])},
        **info.get(u.login, {})) for u in rows]}


@router.get("/admin/students")
def admin_students(group: str = Query(""),
                   _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(User).filter(User.role == "student", User.deleted == False)  # noqa: E712
    if group:
        q = q.filter(User.group_name == group)
    rows = q.order_by(User.group_name, User.surname, User.name).all()
    info = _contact_info(db, [u.login for u in rows])
    #name отдаём как есть (полная форма — совместимость), плюс имя и отчество РАЗДЕЛЬНО.
    return {"students": [dict(
        #id нужен для привязки родителя: связь ведётся по НЕИЗМЕНЯЕМОМУ users.id, а не по
        #ФИО (фамилия меняется — см. §12 миграции оценок, там это уже стоило истории).
        {"id": u.id, "login": u.login, "surname": u.surname, "name": u.name,
         "first_name": W.first_name(u), "patronymic": W.patronymic_of(u),
         "group": u.group_name},
        **info.get(u.login, {})) for u in rows]}


@router.get("/admin/groups")
def admin_groups(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(Group).filter(Group.deleted == False).order_by(Group.name).all()  # noqa: E712
    out = []
    for g in rows:
        n = db.query(User).filter(User.role == "student", User.group_name == g.name,
                                  User.deleted == False).count()  # noqa: E712
        out.append({"name": g.name, "subjects": list(g.subjects or []), "students": n,
                    "category": g.category or "college"})
    return {"groups": out}


# --- Учебные часы группы (план на семестр) ------------------------------------------
@router.get("/admin/group-hours")
def admin_group_hours(group: str = Query(...), year: str = Query(""), semester: int = Query(0),
                      _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Предметы группы с плановыми и уже пройденными часами за семестр.

    Пройденные показываем и админу: без них поле «часов на семестр» заполняется вслепую,
    а «занятий уже 30, а план 24» — единственный способ заметить опечатку сразу."""
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    grp = db.get(Group, f"grp:{group}")
    if grp is None or grp.deleted:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    lessons = W.group_lessons(db, group, year=ty, semester=ts)
    by_subject = {}
    for l in lessons:
        by_subject.setdefault(l.subject, []).append(l)
    #Назначения преподов на эту группу за термин — одним запросом, не по одному на предмет.
    hrows = {r.subject: r for r in db.query(SubjectHours).filter(
        SubjectHours.group_name == group, SubjectHours.year == ty,
        SubjectHours.semester == ts, SubjectHours.deleted == False).all()}  # noqa: E712
    tids = {r.teacher_id for r in hrows.values() if r.teacher_id}
    tnames = {u.id: W.display_name(u) for u in db.query(User).filter(User.id.in_(tids)).all()} if tids else {}
    out = []
    for subj in list(grp.subjects or []):
        tid = (hrows.get(subj).teacher_id if subj in hrows else "") or ""
        hrs = W.hours_plan(db, group, subj, ty, ts)
        zet = hrows.get(subj).zet if subj in hrows else None
        out.append({"subject": subj, "hours_total": hrs,
                    "hours_done": W.hours_done(by_subject.get(subj, [])),
                    "teacher_id": tid, "teacher_name": tnames.get(tid, ""),
                    #ЗЕТ (docs/PLAN-ZET.md): zet — уже подтверждённое администратором
                    #значение (None — не задано, тогда интерфейс строку не показывает);
                    #zet_hint — ТОЛЬКО подсказка по формуле, никогда не подставляется сама.
                    "zet": zet, "zet_hint": W.study_hours.zet_hint(hrs)})
    return {"group": group, "term": {"year": ty, "semester": ts}, "subjects": out}


@router.post("/admin/group-hours")
def admin_set_group_hours(payload: dict = Body(...),
                          _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Сохранить часы + назначение препода + ЗЕТ по предметам группы:
    {group, year, semester, hours: {предмет: N}, teachers: {предмет: teacher_id | ""},
    zet: {предмет: float | null}}.

    Пишем ПАЧКОЙ (кнопка «Сохранить» в админке правит сразу несколько предметов) — иначе
    полтора десятка запросов на одно нажатие и половинчатое состояние при обрыве связи.
    `teachers` — §ролей препод↔предмет↔группа: единственный источник правды «кто ведёт
    какую группу по какому предмету», см. webdata.teacher_assignments. `zet` —
    docs/PLAN-ZET.md: null (или ключ отсутствует) — не трогать/не задано, число —
    подтверждённое администратором значение (подсказка zet_hint сюда НЕ подставляется
    автоматически, только человеком)."""
    group = (payload.get("group") or "").strip()
    hours = payload.get("hours") or {}
    teachers = payload.get("teachers") or {}
    zets = payload.get("zet") or {}
    if not group or not isinstance(hours, dict) or not isinstance(teachers, dict) \
            or not isinstance(zets, dict):
        raise HTTPException(status_code=400, detail="Нужны group и hours")
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, payload.get("year") or "", int(payload.get("semester") or 0))
    #Пустая строка teacher_id / null ЗЕТ = «снять назначение»/«снять ЗЕТ» — ЗНАЧИМОЕ
    #намерение, поэтому обходим объединение ключей hours∪teachers∪zet, а не только те,
    #где задано число часов.
    subjects_touched = ({(s or "").strip() for s in hours}
                        | {(s or "").strip() for s in teachers}
                        | {(s or "").strip() for s in zets})
    subjects_touched.discard("")
    saved = 0
    for subject in subjects_touched:
        hid = subject_hours_id(group, subject, ty, ts)
        row = db.get(SubjectHours, hid)
        if row is None:
            row = SubjectHours(id=hid, group_name=group, subject=subject, year=ty, semester=ts)
            db.add(row)
        if subject in hours:
            try:
                row.hours_total = max(0, int(hours[subject] or 0))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400,
                                    detail=f"Часы по предмету «{subject}» должны быть числом")
        if subject in teachers:
            tid = (teachers[subject] or "").strip()
            if tid:
                t = db.query(User).filter(User.id == tid, User.role == "teacher",
                                          User.deleted == False).first()  # noqa: E712
                if t is None:
                    raise HTTPException(status_code=404, detail="Преподаватель не найден")
                if subject not in (t.subjects or []):
                    raise HTTPException(
                        status_code=400,
                        detail=f"У преподавателя «{W.display_name(t)}» нет предмета «{subject}»")
            row.teacher_id = tid
        if subject in zets:
            zv = zets[subject]
            if zv is None or zv == "":
                row.zet = None
            else:
                try:
                    row.zet = float(zv)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400,
                                        detail=f"ЗЕТ по предмету «{subject}» должен быть числом")
                if row.zet < 0:
                    raise HTTPException(status_code=400, detail="ЗЕТ не может быть отрицательным")
        row.updated_at = _now_iso()
        #Ноль часов — это «план снят», а не удаление строки: надгробие уехало бы на десктоп и
        #там часы просто исчезли бы, вместо того чтобы показать «не задано». Та же логика
        #для назначения — снятие препода (tid="") не трогает саму строку часов.
        row.deleted = False
        saved += 1
    db.commit()
    audit.log(db, actor=_admin.login, role="admin", action="group.hours",
              target=group, detail=f"предметов: {saved}")
    return {"ok": True, "saved": saved, "term": {"year": ty, "semester": ts}}


@router.get("/admin/subjects")
def admin_subjects(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(Subject).filter(Subject.deleted == False).order_by(Subject.name).all()  # noqa: E712
    return {"subjects": [{"name": s.name} for s in rows]}


# СЕРВЕР И САЙТ (инфо-панель, только чтение) ──────────────────────────────────────
import time as _time                                                    # noqa: E402
_SERVER_START_TS = _time.time()   #≈ старт процесса (web.py грузится при старте)


@router.get("/admin/server-info")
def admin_server_info(request: Request = None,
                      _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Статус сервера/сайта для веб-вкладки «Сервер»: адрес, версия, тип БД, шифрование
    ПДн (152-ФЗ), ГОСТ-бэкенд, кто онлайн, учебный период, аптайм. Только чтение —
    хостингом управляют на ХОСТЕ (десктоп server_control), из браузера это не трогаем."""
    import os
    from ..config import DATABASE_URL, ALLOWED_ORIGINS
    from .. import gost, security, events as _events
    is_sqlite = DATABASE_URL.startswith("sqlite")
    db_key = os.environ.get("GRADEBOOK_DB_KEY", "").strip()
    sqlcipher = False
    if is_sqlite and db_key:
        try:
            import sqlcipher3  # noqa: F401
            sqlcipher = True
        except ImportError:
            sqlcipher = False
    bi = gost.backend_info()
    domain = (os.environ.get("GRADEBOOK_DOMAIN", "").strip()
              or (ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS and ALLOWED_ORIGINS != ["*"] else ""))
    if domain and not domain.startswith("http"):
        domain = "https://" + domain
    cfg = W.load_config(db)
    cy, cs = W.current_term(cfg)
    gost_hash = security._openssl_gost_name()
    return {
        "address": domain or (str(request.base_url).rstrip("/") if request else ""),
        "version": "Release 3.0",
        "status": "работает",
        "uptime_sec": int(_time.time() - _SERVER_START_TS),
        "db_kind": "PostgreSQL" if not is_sqlite else "SQLite",
        "db_file_encrypted": sqlcipher,          # файл БД шифруется целиком (SQLCipher AES-256)
        "pdn_field_encrypted": gost.enabled(),   # поля ПДн (телефон) шифруются «Кузнечик»
        "crypto_backend": bi.get("backend", ""),
        "crypto_algorithm": bi.get("algorithm", ""),
        "crypto_certified": bi.get("certified", False),
        "gost_hash_backend": gost_hash or "gostcrypto (pure-python)",
        "online_count": len(_events.online()),
        "term": {"year": cy, "semester": cs},
        "counts": {
            "students": db.query(User).filter(User.role == "student", User.deleted == False).count(),  # noqa: E712
            "teachers": db.query(User).filter(User.role == "teacher", User.deleted == False).count(),  # noqa: E712
            "groups": db.query(Group).filter(Group.deleted == False).count(),  # noqa: E712
        },
    }


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
    return {"groups": schedule_web.list_groups(category)}


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
        daylist = weeks.setdefault(wk, {}).setdefault(day, [])
        daylist[:] = [x for x in daylist if x.get("pair_no") != ov.pair_no]   # убрать старую
        if ov.action == "set":
            daylist.append({"pair_no": ov.pair_no, "time": ov.time, "kind": ov.kind,
                            "subject": ov.subject, "teacher": ov.teacher, "room": ov.room,
                            "raw": ov.subject, "extra": "", "_override": True})
        daylist.sort(key=lambda x: x.get("pair_no") or 0)
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
    g = (group or user.group_name or "").strip()
    data = _group_schedule(db, g, category) if g else None
    return {
        "group": g,
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
        from .. import docx_export
        payload = docx_export.build_schedule_docx(g, weeks, pair_times)
    else:
        from .. import xlsx_export
        payload = xlsx_export.build_schedule_xlsx(g, weeks, pair_times)
    return _file_response(payload, f"Расписание_{g}", fmt)


# ── Редактор расписания в админке (правки ПОВЕРХ портала) ────────────────────────────
@router.get("/admin/schedule")
def admin_schedule_get(group: str = Query(...), user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    """Слитое расписание группы (портал + правки) + сырой список правок для редактора."""
    g = (group or "").strip()
    merged = _group_schedule(db, g)
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
                       "room": o.room, "teacher": o.teacher, "kind": o.kind} for o in ovs],
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
    except (TypeError, ValueError):
        raise HTTPException(400, "week и pair_no должны быть числами")
    if not g or day not in _OV_DAYS or week not in (1, 2) or pair_no < 1:
        raise HTTPException(400, "Проверьте группу, неделю (1/2), день и номер пары")
    if action not in ("set", "remove"):
        raise HTTPException(400, "action: set | remove")
    #Детерминированный id ячейки — один и тот же на вебе и десктопе (ключ синка): повторная
    #правка той же ячейки ЗАМЕНЯЕТ прежнюю на обеих платформах.
    oid = schedule_override_id(g, week, day, pair_no)
    row = db.get(ScheduleOverride, oid)
    #Снимок ДО правки. Нужен, чтобы НЕ двигать updated_at, когда ничего не изменилось:
    #админ часто открывает ячейку и сохраняет её не тронув, а лишний бамп метки отправил
    #бы строку в дельту синка на все ПК без единой реальной правки.
    #(Уведомления здесь ни при чём — они уходят одной пачкой по кнопке «Опубликовать».)
    before = None if row is None else (row.action, row.subject, row.time, row.room,
                                       row.teacher, row.kind, bool(row.deleted))
    if row is None:
        row = ScheduleOverride(id=oid, group_name=g, week=week, day=day, pair_no=pair_no)
        db.add(row)
    row.action = action
    row.subject = (payload.get("subject") or "").strip()
    row.time = (payload.get("time") or "").strip()
    row.room = (payload.get("room") or "").strip()
    row.teacher = (payload.get("teacher") or "").strip()
    row.kind = (payload.get("kind") or "").strip()
    row.deleted = False
    after = (row.action, row.subject, row.time, row.room, row.teacher, row.kind, False)
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
        from .messenger import notify_substitution
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
        from .messenger import notify_substitution
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
    from .. import schedule_web
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
    from .. import schedule_conflicts
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
    from .. import schedule_conflicts
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

    from .. import rustore_push
    sent = 0
    for person, role in ([(s, "student") for s in students]
                         + [(t, "teacher") for t in teachers]):
        if not person.login:
            continue        #без логина уведомлять некого (внешний ростер преподавателя)
        rustore_push.notify_schedule_changed(db, person.login, role=role, group=group)
        sent += 1
    #§D12: тот же факт — постом в канал «Расписание · Группа» (мессенджер). Изолировано
    #try/except: сбой мессенджера не должен мешать основной рассылке пушей выше.
    try:
        from .messenger import ensure_group_schedule_channel, _post_system_channel_message
        conv_id = ensure_group_schedule_channel(db, group, [s.id for s in students])
        _post_system_channel_message(
            db, conv_id, f"⚠️ Расписание группы **{group}** изменилось — проверьте актуальные пары.")
    except Exception:
        pass
    audit.log(db, actor=user.login, role="admin", action="schedule.publish",
              target=group, detail=f"уведомлено: {sent}")
    return {"ok": True, "notified": sent,
            "students": len(students), "teachers": len(teachers)}


# «ВЕКТОР» ─────────────────────────────────────────────────────────────────────────
#Интенты со СТАТИЧНЫМ текстом (приветствие/справка/благодарность/факты о ВСГУТУ). Их
#НЕЛЬЗЯ гонять через LLM: там нечего переформулировать — это готовая справка, а не данные.
#Модель видит в ней НАЗВАНИЯ метрик («средний балл», «должники», «зона риска») без цифр и
#дописывает шаблон с плейсхолдерами («Средний балл по группам: [укажите средние баллы]») —
#ровно та выдумка, которую продукт обещает не делать (§5). LLM озвучивает ТОЛЬКО ответы с
#РЕАЛЬНЫМИ числами.
#ВАЖНО: набор ДОЛЖЕН совпадать с десктопным guard'ом в vector/engine.py::ask — при
#портировании веба его забыли перенести, отсюда и был баг с плейсхолдерами на сайте.
#intent → LLM НЕ вызываем (нет цифр для переформулировки ИЛИ формат нельзя ломать):
#  hello/thanks/help/unknown — текст-справка без чисел (иначе модель дописывает
#    плейсхолдеры «[укажите средние баллы]» вместо фактов, см. §5);
#  about_* — статичные факты о заведении;
#  schedule — структурный список пар: LLM мог бы добавить/выкинуть занятие.
#  weather — реальные показания метеослужбы: модель, «озвучивая данные», охотно
#            меняет числа, а неверная температура в продукте, обещающем не врать,
#            дороже красивой формулировки.
#  homework — текст задания написал ПРЕПОДАВАТЕЛЬ, и человек должен прочитать его
#             дословно; перефразированная домашка это уже другая домашка.
#  server_state — одни числа (диск, память, размер базы): модель их округляет и меняет
#             единицы, а по этим цифрам принимают решения.
_NO_VOICE_INTENTS = {"hello", "thanks", "help", "unknown",
                     "about_vsgutu", "about_college", "schedule", "weather", "howto",
                     "homework", "server_state"}


def answer_vector_question(question: str, user: User, db: Session, context: str = "",
                           voice_role: str = "") -> dict:
    """Общая логика ответа Вектора (вынесена из `vector_ask`, чтобы её мог переиспользовать
    мессенджер — команда `/vector <вопрос>` в любом чате, см. `routers/messenger.py`).
    Тот же принцип, что в десктопе: цифры берутся из реальных данных (SQL) — модель их НЕ
    выдумывает. Фактический текст собирает `_vector_facts`, затем LLM-провайдер
    (GigaChat/Ollama/оффлайн — из СИНХРОНИЗИРОВАННОГО конфига админа) лишь ПЕРЕФОРМУЛИРУЕТ
    его в стиле Вектора. Роль вызывающего (`user.role`) скоупит данные, как и в дедике."""
    cfg = W.load_config(db)
    result = _vector_facts(question.lower(), user, db, cfg)
    intent = result.get("intent")
    #voice_role меняет ТОЛЬКО тон обращения, но не скоуп данных. Нужен кабинету родителя:
    #факты там собираются от лица РЕБЁНКА (иначе пришлось бы дублировать весь студенческий
    #скоуп и однажды разойтись с ним), а говорить «твой средний балл» родителю — странно.
    role = voice_role or user.role
    #Вопрос НЕ из пула (unknown) — свободный small-talk: пара фраз + мягкий возврат к учёбе,
    #без решения задач (см. vector_llm.free_chat). Данные журнала тут не выдумываем.
    if intent == "unknown":
        #context — обезличенные заметки из «Избранного» (пусто для обычного /web/vector/ask):
        #помогает понять «а это когда?», но цифры успеваемости из него брать запрещено.
        result["text"] = vector_llm.free_chat(cfg, question, role, context)
    #Озвучка: числа уже посчитаны и верны, LLM их не трогает — только стиль. Оффлайн или
    #ошибка провайдера → вернётся исходный фактический текст (сайт не ломается).
    #Приветствие/справку/благодарность/расписание НЕ озвучиваем (см. _NO_VOICE_INTENTS).
    elif intent not in _NO_VOICE_INTENTS and not result.get("no_voice"):
        #no_voice — ответ содержит фактический список (имена, причины), который LLM исказил
        #бы или отказался озвучивать. Отдаём как есть.
        result["text"] = vector_llm.voice(cfg, result.get("text", ""), role, question)
    result.pop("no_voice", None)   #внутренний флаг наружу не отдаём
    return result


@router.post("/vector/ask")
def vector_ask(payload: dict = Body(...),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Серверный «Вектор» — см. `answer_vector_question`. Студент видит только свои данные."""
    question = (payload.get("message") or "").strip()
    return answer_vector_question(question, user, db)


# ── Голосовой ввод (Speech-to-Text) — ЗАГОТОВКА, распознаёт на ХОСТЕ ────────────────
def _stt_installed() -> bool:
    """Стоит ли движок распознавания на ЭТОМ хосте (faster-whisper)."""
    try:
        from .. import stt_service
        return bool(stt_service.is_available())
    except Exception:
        return False


#Режимы голосового ввода (настройка админа `stt_mode`):
#  auto    — Whisper, если он есть на хосте; иначе распознаёт сам браузер. По умолчанию:
#            у кого локально стоит — тот и получает Whisper, никого не заставляя качать.
#  server  — ТОЛЬКО Whisper на сервере. Это «задел на продажу»: на боевом VPS движка нет
#            (1 ядро, 960 МБ — модель туда не влезает), поэтому режим честно отвечает
#            «недоступно», пока у колледжа не появится машина с видеокартой.
#  browser — ТОЛЬКО встроенное распознавание браузера, даже если Whisper установлен.
_STT_MODES = ("auto", "server", "browser")


@router.get("/vector/stt/status")
def vector_stt_status(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Каким движком распознавать речь и доступен ли он.

    Решение принимает СЕРВЕР, а не клиент: иначе десктоп и сайт разошлись бы в поведении,
    а админ не смог бы включить Whisper «для всех» одним переключателем.

    `engine`: 'whisper' — шлём аудио на `/web/vector/stt`; 'browser' — клиент распознаёт
    сам; '' — голосовой ввод недоступен, и тогда `reason` объясняет, почему именно."""
    installed = _stt_installed()
    mode = (W.load_config(db).get("stt_mode") or "auto").strip()
    if mode not in _STT_MODES:
        mode = "auto"
    if mode == "browser":
        return {"available": True, "mode": mode, "engine": "browser",
                "installed": installed, "reason": ""}
    if installed:
        return {"available": True, "mode": mode, "engine": "whisper",
                "installed": True, "reason": ""}
    if mode == "server":
        #Жёстко выбран Whisper, а его нет — молча подменять браузерным нельзя: админ
        #включил распознавание НА СЕРВЕРЕ осознанно (ПДн не должны уходить в облако
        #браузера), и тихая подмена нарушила бы именно это решение.
        return {"available": False, "mode": mode, "engine": "",
                "installed": False,
                "reason": "Распознавание на сервере включено, но движок на нём не установлен."}
    return {"available": True, "mode": mode, "engine": "browser",
            "installed": False, "reason": ""}


def _stt_context(db: Session, user: User) -> str:
    """Слова, которые модель должна ожидать: имя маскота, предметы, фамилии своих студентов.

    Это не «улучшение по вкусу»: без такой подсказки Whisper уверенно подменяет редкие
    имена похожими обычными словами, и распознанное выглядит правдоподобно — а значит
    ошибку легко не заметить. Ограничиваем список: слишком длинная подсказка размывает
    внимание модели и начинает мешать."""
    words = ["Вектор", "ВСГУТУ"]
    try:
        cfg = W.load_config(db)
        ty, ts = W.current_term(cfg)
        if user.role == "teacher":
            pairs = W.teacher_assignments(db, user.id, ty, ts)
            words += sorted({s for _g, s in pairs})[:12]
            for group in sorted({g for g, _s in pairs})[:4]:
                words += [st.surname for st in W.students_in_group(db, group)][:30]
        elif user.role == "student" and hasattr(W, "_group_subject_list"):
            words += sorted(W._group_subject_list(db, user.group_name or ""))[:12]
    except Exception:
        pass
    #Уникальные, порядок сохраняем: первым идёт то, что важнее узнать.
    seen, out = set(), []
    for w in words:
        w = (w or "").strip()
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return ", ".join(out[:60])


@router.post("/vector/voice/command")
def vector_voice_command(payload: dict = Body(...),
                         user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Разобрать РАСПОЗНАННУЮ фразу преподавателя в НАМЕРЕНИЕ (оценки / занятие / вопрос).

    ⚠️ ЭТОТ ЭНДПОИНТ НИЧЕГО НЕ ПИШЕТ. Он только предлагает — запись выполняет уже
    существующий `POST /web/teacher/grade` после того, как преподаватель подтвердил
    список в диалоге. Отдельного «голосового» пути записи НЕТ намеренно: второй путь
    означал бы вторую проверку прав и второй формат ключа оценки, а именно из-за
    расползания таких копий ключи оценок когда-то собирались в семи местах.

    LLM в цепочке НЕ участвует: разбор детерминированный (общий модуль `voice_command.py`,
    тот же, что на десктопе). Модель ошибается молча, а оценка не тому студенту — худшее,
    что может сделать журнал.

    Роль-скоуп обычный: только преподаватель и только своя группа+предмет.
    """
    _require("teacher", user)
    text = (payload.get("text") or "").strip()
    group = (payload.get("group") or "").strip()
    subject = (payload.get("subject") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустая фраза")
    if not (group and subject):
        raise HTTPException(status_code=400, detail="Нужны группа и предмет")

    cfg = W.load_config(db)
    ty, ts = W.current_term(cfg)
    #Право на ЭТУ группу и ЭТОТ предмет — до любого разбора: подсказывать состав чужой
    #группы (а ростер уходит в подсказку распознавателя) мы не имеем права.
    _teacher_check_assignment(db, user, group, subject, ty, ts)

    students = W.students_in_group(db, group)
    roster = [(st.surname or "", st.name or "") for st in students]

    #Занятия ЗА СЕГОДНЯ по этому предмету — к ним привяжутся оценки. Дата в базе хранится
    #как ДД.ММ.ГГГГ (формат десктопа), поэтому сравниваем строкой в том же виде.
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y")
    todays = [{"id": l.id, "label": f"{l.type} №{l.number}"}
              for l in db.query(Lesson).filter(
                  Lesson.group_name == group, Lesson.subject == subject,
                  Lesson.date == today, Lesson.year == ty, Lesson.semester == ts,
                  Lesson.deleted == False).all()]      # noqa: E712

    import voice_command
    res = voice_command.parse_batch(text, roster, todays)
    return {
        "kind": res.kind,
        "is_question": bool(res.is_question),
        "heard": res.heard,
        "error": res.error,
        "warnings": list(res.warnings),
        "lesson_id": res.lesson_id,
        "lesson_label": res.lesson_label,
        #Плоский список правок — ровно в том виде, в котором клиент затем отправит их в
        #`/web/teacher/grade` (surname/name/grade). Ничего додумывать ему не придётся.
        "items": [{"surname": i.surname, "name": i.name, "who": i.who,
                   "action": i.action, "grade": i.value} for i in res.items],
        "lesson": ({"type": res.lesson.type, "topic": res.lesson.topic,
                    "number": res.lesson.number} if res.lesson else None),
    }


@router.post("/vector/stt")
async def vector_stt(file: UploadFile = File(...),
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Принимает аудио (getUserMedia/MediaRecorder из браузера), распознаёт на ХОСТЕ и
    возвращает текст. Клиент дальше сам решает: вопрос → /web/vector/ask, а команду
    записи (для преподавателя) — через подтверждение (как в десктопе). Здесь только STT."""
    from .. import stt_service
    if not stt_service.is_available():
        raise HTTPException(status_code=503,
                            detail="Голосовой ввод не настроен на сервере.")
    #Уважаем выбор админа: при режиме «распознаёт браузер» серверный движок не работает,
    #даже если установлен. Иначе настройка была бы декоративной — устаревший клиент
    #продолжал бы грузить хост, хотя администратор это запретил.
    if (W.load_config(db).get("stt_mode") or "auto").strip() == "browser":
        raise HTTPException(status_code=503,
                            detail="Распознавание на сервере отключено администратором.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустой аудиофайл.")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Аудио слишком большое (макс 10 МБ).")
    cfg = W.load_config(db)
    #🎯 ПОДСКАЗКА МОДЕЛИ — то, чего здесь не хватало, и из-за чего «Вектор» слышался как
    #«Виктор», а фамилии студентов превращались в похожие русские слова. Нативная версия
    #подсказку давала, серверная — нет, поэтому качество на вебе было заметно хуже при
    #той же модели. Whisper опирается на контекст: список ожидаемых слов резко поднимает
    #узнавание редких имён (бурятские ФИО — Самбуева, Гындынова, Баянжаргал).
    #Скоуп ролевой, как везде: студент подсказывает свои предметы, преподаватель — ещё и
    #фамилии своих студентов. Чужих ФИО в подсказку не попадает.
    res = stt_service.transcribe_bytes(
        data, filename=file.filename or "audio.webm",
        size=cfg.get("stt_model", "large-v3"), device=cfg.get("stt_device", "auto"),
        context=_stt_context(db, user))
    if not res["ok"]:
        raise HTTPException(status_code=500, detail=res["error"])
    return {"text": res["text"]}


# ── Голосовая ОЗВУЧКА (Text-to-Speech) — синтез на ХОСТЕ (Silero), см. tts_service ──
@router.get("/vector/tts/status")
def vector_tts_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Доступна ли озвучка: движок стоит на хосте И админ её не выключил. По этому флагу
    и списку голосов веб-клиент решает, показывать ли кнопку динамика и выбор голоса."""
    from .. import tts_service
    cfg = W.load_config(db)
    enabled = cfg.get("tts_enabled", True)
    return {"available": bool(enabled) and tts_service.is_available(),
            "voices": tts_service.voices()}


@router.post("/vector/tts")
def vector_tts(payload: dict = Body(...),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Синтезирует переданный текст (уже готовый ответ Вектора, без ПДн) в WAV. Голос
    (male/female) выбирает пользователь в настройках. Кэш — внутри tts_service."""
    from fastapi.responses import Response
    from .. import tts_service
    cfg = W.load_config(db)
    if not cfg.get("tts_enabled", True):
        raise HTTPException(status_code=503, detail="Озвучка отключена администратором.")
    text = (payload.get("text") or "").strip()
    voice = (payload.get("voice") or "male").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустой текст.")
    #Движок синтеза выбирается конфигом (silero сейчас; клон-голос на GPU — потом).
    res = tts_service.synthesize(text, voice, engine=cfg.get("tts_engine", "silero"))
    if not res["ok"]:
        #Движок не поднялся / нет модели — 503: клиент откатится на speechSynthesis.
        raise HTTPException(status_code=503, detail=res["error"])
    return Response(content=res["audio"], media_type=res["mime"],
                   headers={"Cache-Control": "no-store"})


#Слова-триггеры «что умеешь / помощь / кто ты» и приветствие — распознаём ПЕРВЫМИ,
#чтобы Вектор отвечал по делу, а не сваливался в статистику. Дефолт тоже = подсказка.
# Факты о заведении — источник правды, НЕ генерация (как vector/knowledge.py на десктопе).
#Факты о заведении. Держать СИНХРОННО с vector/knowledge.py (ANSWER_VSGUTU/ANSWER_COLLEGE)
#— это источник правды десктопа (§12). Импортировать оттуда напрямую нельзя: vector/__init__
#тянет десктопные engine/intents, и на сервере это падает. Поэтому — копия с пометкой,
#как и другие «обязаны совпадать» дубли (_NO_VOICE_INTENTS, grade_id). Раньше сервер нёс
#УРЕЗАННУЮ версию (без истории и масштаба) и расходился с десктопом.
_ABOUT_VSGUTU = (
    "ВСГУТУ — это Восточно-Сибирский государственный университет технологий и "
    "управления в Улан-Удэ (Республика Бурятия). Основан 19 июня 1962 года как "
    "Восточно-Сибирский технологический институт (ВСТИ); в 1994 году получил статус "
    "университета, а в 2011-м переименован во ВСГУТУ. Сегодня это один из крупнейших "
    "вузов Сибири и Дальнего Востока — свыше 15 тысяч студентов и более 1900 "
    "преподавателей и сотрудников. Основной адрес — ул. Ключевская, 40В."
)
_ABOUT_COLLEGE = (
    "Технологический колледж ВСГУТУ — структурное подразделение университета в "
    "Улан-Удэ, которое даёт среднее профессиональное образование (СПО) и готовит "
    "специалистов среднего звена. После колледжа можно продолжить учёбу в самом "
    "ВСГУТУ. Группы колледжа обозначаются буквой «К» (например, К75/1). Этот "
    "электронный журнал — внутренняя система колледжа: оценки, посещаемость, "
    "пересдачи и успеваемость по группам."
)

_HOWTO = (
    "Как всё устроено в журнале:\n"
    "• Средний балл считается по практикам и экзаменам (лекции в него не входят); "
    "пересдача заменяет прежнюю попытку — учитывается последняя.\n"
    "• Задолженность — несданная практика (2 или Н) либо незачтённый экзамен.\n"
    "• Посещаемость: Н — неявка, Б — по болезни, О — по уважительной причине.\n"
    "• Зона риска — студенты со средним баллом ниже 3.\n"
    "Спроси про свои цифры словами — я беру их из реальных данных, а не выдумываю.")


_HELP_BY_ROLE = {
    "student": ("Я — Вектор 🐯, помогаю с учёбой по твоим РЕАЛЬНЫМ данным (цифры не выдумываю). "
                "Спроси словами: «мой средний балл», «сколько у меня оценок», «оценки по "
                "информатике», «есть ли долги», «сколько пропусков», «когда математика», "
                "«что завтра». Или жми кнопки под чатом."),
    "teacher": ("Я — Вектор 🐯 для преподавателя, считаю строго по журналу твоих групп. Умею: "
                "«средний по группам», «кто в зоне риска», «у кого долги», «список студентов», "
                "«пропуски у <фамилия>», «какие группы», «расписание группы». Спрашивай как удобно."),
    "admin":   ("Я — Вектор 🐯 для администратора. Умею сводку по колледжу: «сколько студентов», "
                "«сколько преподавателей», «какие группы», «список преподавателей», «сводка по "
                "группе <название>». Спрашивай словами или жми кнопки."),
}
_HELLO_PREFIX = {"student": "Привет!", "teacher": "Здравствуйте!", "admin": "Здравствуйте!"}
_SCHED_DAYS = ["Пнд", "Втр", "Срд", "Чтв", "Птн", "Сбт"]


def _known_subjects(user: User, db: Session) -> list:
    """Предметы в области видимости пользователя (для распознавания «по информатике»).
    Студент — предметы занятий своей группы; преподаватель — свои; админ — все."""
    try:
        if user.role == "student":
            return sorted({l.subject for l in W.group_lessons(db, user.group_name) if l.subject})
        if user.role == "teacher":
            ty, ts = W.current_term(W.load_config(db))
            return sorted({s for _g, s in W.teacher_assignments(db, user.id, ty, ts)})
        rows = db.query(Subject.name).filter(Subject.deleted == False).all()  # noqa: E712
        return sorted({r[0] for r in rows if r[0]})
    except Exception:
        return []


def _known_surnames(user: User, db: Session) -> list:
    """Фамилии студентов в области видимости (для «пропуски у Иванова»). Студенту —
    пусто (только о себе); преподавателю — студенты его групп; админу — все студенты."""
    if user.role == "student":
        return []
    try:
        if user.role == "teacher":
            ty, ts = W.current_term(W.load_config(db))
            out = []
            for g in W.teacher_group_names(db, user.id, ty, ts):
                out += [s.surname for s in W.students_in_group(db, g)]
            return sorted(set(out))
        rows = db.query(User.surname).filter(User.role == "student",
                                             User.deleted == False).all()  # noqa: E712
        return sorted({r[0] for r in rows if r[0]})
    except Exception:
        return []


def _grade_breakdown(lessons, records, scale=None) -> dict:
    """Счёт оценок студента: всего практических оценок (2–5) и разбивка по баллам.
    scale — {lesson_id: шкала}/строка/None (§ролей, 3.3.1): сырое значение переводится
    в 5-балльное ПЕРЕД подсчётом, поэтому «пятёрка» на 100-балльной (90+) тоже считается."""
    counts = {"5": 0, "4": 0, "3": 0, "2": 0}
    ids = {l.id for l in lessons if l.type == "Практика"}
    scale_map = scale if isinstance(scale, dict) else None
    for lid, v in (records or {}).items():
        if lid not in ids or not v:
            continue
        lscale = scale_map.get(lid, W.grading.DEFAULT_SCALE) if scale_map is not None else (scale or W.grading.DEFAULT_SCALE)
        num = W.grading.to_five_point(v, lscale)
        key = str(int(num)) if num is not None else None
        if key in counts:
            counts[key] += 1
    counts["всего"] = sum(counts[k] for k in ("5", "4", "3", "2"))
    return counts


def _zet_facts(db, surname: str, name: str, group: str, cfg: dict) -> dict:
    """Вектор: «Сколько у меня ЗЕТ / хватит ли для перевода» (docs/PLAN-ZET.md §6).
    Факты — из того же расчёта, что и /web/student/zet; LLM (если подключена) только
    переформулирует, порог и цифры не выдумывает."""
    ty, ts = W.current_term(cfg)
    summ = W.zet_summary_for_student(db, surname, name, group, ty, ts)
    if not summ["subjects"]:
        return {"text": "ЗЕТ по твоим предметам пока не заданы администрацией.",
                "mood": "neutral", "intent": "zet", "facts": {}}
    threshold = db.get(ZetThreshold, zet_threshold_id(group, ty, ts))
    min_zet = threshold.min_zet if (threshold and not threshold.deleted) else None
    unsatisfied = [s["subject"] for s in summ["subjects"] if not s["passed"]]
    parts = [f"У тебя {summ['earned']} из {summ['total']} ЗЕТ за семестр ({summ['pct']}%)."]
    if min_zet is not None:
        if summ["earned"] >= min_zet:
            parts.append(f"Порог для перевода — {min_zet} ЗЕТ, он уже набран.")
        else:
            parts.append(f"Порог для перевода — {min_zet} ЗЕТ, не хватает "
                         f"{round(min_zet - summ['earned'], 1)}.")
    if unsatisfied:
        parts.append("Ещё не сдано: " + ", ".join(unsatisfied) + ".")
    mood = "happy" if (min_zet is None or summ["earned"] >= min_zet) else \
        ("neutral" if summ["pct"] >= 80 else "sad")
    return {"text": " ".join(parts), "mood": mood, "intent": "zet",
            "facts": {"earned": summ["earned"], "total": summ["total"], "pct": summ["pct"],
                     "min_zet": min_zet, "unsatisfied": unsatisfied}}


def _subj_match(detected: str, lesson_subject: str) -> bool:
    """Совпадает ли распознанный предмет с названием из расписания (разные написания).

    Строго: ПЕРВОЕ значимое слово должно совпасть по основе + не меньше половины значимых
    слов. Иначе «коммуник» из ИКТ ложно матчит «коммуникации» в «Иностр. язык в проф.
    коммуникации» — и Вектор показывал расписание чужого предмета."""
    a, b = vector_nlu.normalize(detected), vector_nlu.normalize(lesson_subject)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    aw = [w for w in a.split() if len(w) >= 5]
    bw = [w for w in b.split() if len(w) >= 5]
    if not aw or not bw:
        return False
    first = aw[0][:6]
    if not any(w.startswith(first) for w in bw):     # первое слово обязано совпасть
        return False
    hits = sum(1 for w in aw if any(x.startswith(w[:6]) for x in bw))
    return hits >= max(1, len(aw) // 2)


def _schedule_answer(db: Session, group: str, msg: str, day) -> tuple:
    """Ответ по расписанию группы (данные — серверный парсер портала schedule_web).

    ПРЕДМЕТ ищем по предметам САМОГО расписания (портал называет их иначе, чем журнал),
    а не по журнальному списку — иначе «иностранный язык» не находился, а ложный матч по
    общему слову показывал чужой предмет. Приоритет: назван предмет → когда он; назван
    день/сегодня/завтра → пары этого дня; иначе — сегодня."""
    if not group:
        return ("Не вижу твоей группы — расписание привязано к ней. Уточни у администратора.", {})
    data = _group_schedule(db, group)   #портал + админ-правки (overlay)
    if not data or not data.get("weeks"):
        return (f"Расписание группы {group} пока не загрузилось с портала — попробуй чуть позже.", {})
    weeks = data["weeks"]
    cur_week = str(schedule_web.current_week_parity() or 1)

    def fmt(l):
        s = l.get("subject") or l.get("raw") or "занятие"
        room = f", ауд. {l['room']}" if l.get("room") else ""
        return f"{l.get('pair_no', '?')} пара ({l.get('time', '')}) — {s}{room}"

    # Все предметы, реально присутствующие в расписании этой группы (для матча запроса).
    sched_subjects = sorted({(l.get("subject") or "").strip()
                             for wk in ("1", "2")
                             for dn in _SCHED_DAYS
                             for l in weeks.get(wk, {}).get(dn, [])
                             if (l.get("subject") or "").strip()})
    subject = vector_nlu.match_subject(msg, sched_subjects) if day == "" else ""

    # A) «когда <предмет>» — ищем предмет по обеим неделям
    if subject:
        found = []
        for wk in ("1", "2"):
            for di, dname in enumerate(_SCHED_DAYS):
                for l in weeks.get(wk, {}).get(dname, []):
                    if _subj_match(subject, l.get("subject", "")):
                        wl = "" if wk == cur_week else f" ({'II' if wk == '2' else 'I'} неделя)"
                        found.append(f"{dname}, {fmt(l)}{wl}")
        if not found:
            return (f"«{subject}» в расписании группы {group} не нашёл. Возможно, предмет "
                    "называется иначе — посмотри вкладку «Расписание».", {})
        return (f"Расписание «{subject}» (группа {group}):\n• " + "\n• ".join(found),
                {"subject": subject, "count": len(found)})

    # Спросили «когда <предмет>», но предмет в расписании не опознан и день не назван —
    # не подсовываем расписание на сегодня (это ввело бы в заблуждение), а честно уточняем.
    if day == "" and "когда" in vector_nlu.normalize(msg):
        return ("Не понял, какой предмет — назови точнее (как во вкладке «Расписание»), "
                "или спроси «что сегодня» / «что завтра». 🐯", {})

    # B) конкретный день / сегодня / завтра. Берём ДАТУ целевого дня и чётность ИМЕННО
    # ЕЁ, а не сегодняшнюю: спрошенный «понедельник» в субботу — это уже СЛЕДУЮЩАЯ неделя
    # (другая чётность). Раньше брали cur_week (сегодня) → выдавали пары не той недели.
    import datetime as _dt
    today = _dt.date.today()
    today_idx = today.weekday()                # 0=Пн..6=Вс
    if day == "today":
        target = today
    elif day == "tomorrow":
        target = today + _dt.timedelta(days=1)
    elif isinstance(day, int):
        target = today + _dt.timedelta(days=(day - today_idx) % 7)   # ближайший этот день
    else:
        target = today
    idx = target.weekday()
    if idx > 5:
        return (f"В этот день у группы {group} занятий нет — выходной. 🐯", {})
    week = str(schedule_web.current_week_parity(target) or 1)         # чётность ЦЕЛЕВОГО дня
    dname = _SCHED_DAYS[idx]
    label = {"today": "Сегодня", "tomorrow": "Завтра"}.get(day, dname)
    lessons_day = weeks.get(week, {}).get(dname, [])
    if not lessons_day:
        return (f"{label} ({dname}, {'II' if week == '2' else 'I'} неделя) у группы {group} "
                f"пар нет. 🐯", {"day": dname, "count": 0})
    body = "\n• ".join(fmt(l) for l in lessons_day)
    return (f"{label} ({dname}), {'II' if week == '2' else 'I'} неделя — группа {group}:\n• "
            + body, {"day": dname, "count": len(lessons_day)})


#Сколько домашних заданий показываем в ответе. Больше — это уже не ответ, а простыня:
#человек спрашивает «что задали», имея в виду ближайшее, а не всю историю за семестр.
_HOMEWORK_LIMIT = 5


def _homework_answer(lessons, records: dict, subject: str = "") -> dict:
    """Ответ про домашние задания. Общий для студента, преподавателя и родителя.

    ДЗ — обычный тип занятия (`Lesson.type == "ДЗ"`, §14), текст задания лежит в поле
    «тема». Раньше на этот вопрос отвечать было нечем: своего интента не существовало, и
    «что задали по физике» уходило в оценки — то есть Вектор уверенно отвечал НЕ НА ТОТ
    вопрос. Здесь же показываем и статус («сдано»/«не сдано»), потому что второй вопрос
    после «что задали» всегда «а я сдал?».

    `records` пуст → статус не показываем (преподаватель спрашивает про группу целиком,
    и «сдано» относилось бы непонятно к кому)."""
    hw = [l for l in lessons if (l.type or "").strip().upper() == "ДЗ"]
    if subject:
        hw = [l for l in hw if l.subject == subject]
    if not hw:
        where = f" по предмету «{subject}»" if subject else ""
        return {"text": f"Домашних заданий{where} пока нет. 🐯", "mood": "happy",
                "intent": "homework", "facts": {"count": 0}}

    #Свежие сверху: спрашивают про то, что задали недавно. Дата в формате ДД.ММ.ГГГГ,
    #поэтому сортируем по перевёрнутому виду, а не по строке как есть.
    def _key(lesson):
        parts = (lesson.date or "").split(".")
        return "".join(reversed(parts)) if len(parts) == 3 else ""

    hw.sort(key=_key, reverse=True)
    shown, lines = hw[:_HOMEWORK_LIMIT], []
    for lesson in shown:
        task = (lesson.topic or "").strip() or "без описания"
        head = f"{lesson.subject} №{lesson.number}" if lesson.number else lesson.subject
        when = f" от {lesson.date}" if lesson.date else ""
        mark = records.get(lesson.id) if records else None
        status = ""
        if records:
            #«Н» на домашней работе значит «не сдал», а не «не был» (§14) — так и пишем.
            status = " — не сдано" if mark == "Н" else (f" — оценка {mark}" if mark else " — ждёт сдачи")
        lines.append(f"{head}{when}: {task}{status}")
    tail = f" Показал последние {len(shown)} из {len(hw)}." if len(hw) > len(shown) else ""
    return {"text": "Домашние задания:\n• " + "\n• ".join(lines) + "." + tail,
            "mood": "neutral", "intent": "homework",
            #no_voice: список заданий содержит формулировки преподавателя, и LLM их
            #перепишет — а это ровно то, что человек должен прочитать дословно.
            "no_voice": True, "facts": {"count": len(hw)}}


def _human_bytes(n) -> str:
    """Байты человеку: «1.3 ГБ». Вектор говорит словами, а не числами со степенями."""
    if not n:
        return "—"
    units, value, i = ("Б", "КБ", "МБ", "ГБ", "ТБ"), float(n), 0
    while value >= 1024 and i < len(units) - 1:
        value, i = value / 1024, i + 1
    return f"{round(value)} {units[i]}" if value >= 10 or i == 0 else f"{value:.1f} {units[i]}"


def _server_state_facts(db: Session) -> dict:
    """Состояние машины для администратора: диск, память, база, резервные копии.

    Цифры берутся у самой машины (`hostinfo`) — тем же способом, что их показывает
    раздел «Сервер». Второго источника не заводим: разойдутся, и человек получит два
    разных ответа на один вопрос в зависимости от того, где спросил.

    ⚠️ ОТВЕТ НЕ ОЗВУЧИВАЕТСЯ (`no_voice`). Здесь одни числа, а LLM их «оживляет» —
    округляет, меняет единицы, добавляет несуществующее. Для успеваемости это правило
    у нас давно, и к состоянию сервера оно относится ровно так же."""
    from .. import hostinfo
    from ..routers.serverinfo import _db_file, _deploy_root

    info = hostinfo.summary(_deploy_root())
    disk, mem = info.get("disk") or {}, info.get("memory") or {}
    parts = []
    if disk.get("total"):
        used = round(disk["used"] / disk["total"] * 100)
        parts.append(f"диск занят на {used}% ({_human_bytes(disk['free'])} свободно)")
    if mem.get("total"):
        used = round(mem["used"] / mem["total"] * 100)
        parts.append(f"память — {used}% из {_human_bytes(mem['total'])}")
    days = int((info.get("uptime") or 0) // 86400)
    hours = int(((info.get("uptime") or 0) % 86400) // 3600)
    if days or hours:
        parts.append(f"работает {days} д {hours} ч")

    path, size, encrypted = _db_file(), 0, False
    try:
        from ..db import DB_KEY
        encrypted = bool(DB_KEY)
        if path and os.path.isfile(path):
            size = os.path.getsize(path)
    except Exception:      # noqa: BLE001 — сведения о базе не повод ронять ответ
        pass
    if size:
        parts.append(f"база — {_human_bytes(size)}"
                     + (", зашифрована" if encrypted else ", БЕЗ шифрования"))

    #Свежесть копий — первое, что админ хочет знать про сервер, и первое, о чём забывают.
    backup_dir = os.environ.get("GRADEBOOK_BACKUP_DIR") or "/root/gb-backups"
    latest = ""
    if os.path.isdir(backup_dir):
        items = hostinfo.listdir(backup_dir, backup_dir)
        if items:
            latest = max(i["mtime"] for i in items)
    parts.append(f"последняя резервная копия — {latest}" if latest
                 else "резервных копий НЕ НАЙДЕНО")

    #Тревожное состояние Вектор обязан назвать тревогой, а не спрятать в перечисление.
    alarm = (not latest) or (disk.get("total") and disk["used"] / disk["total"] > 0.9)
    return {"text": "Сервер: " + "; ".join(parts) + ".",
            "mood": "sad" if alarm else "neutral", "intent": "server_state",
            "no_voice": True,
            "facts": {"disk": disk, "memory": mem, "db_size": size,
                      "db_encrypted": encrypted, "latest_backup": latest}}


def _admin_risk_facts(db: Session, cfg: dict, intent: str) -> dict:
    """Кто в зоне риска / у кого долги — по ВСЕМУ колледжу.

    Считаем через те же `webdata`, что и кабинет преподавателя: своя формула здесь
    означала бы, что у админа и у преподавателя разные списки должников по одному и тому
    же студенту (инвариант §4.8 — расчёт живёт в одном месте)."""
    rows = (db.query(User).filter(User.role == "student", User.deleted == False)  # noqa: E712
            .all())
    lessons_by_group: dict = {}
    risky, debtors = [], []
    for stud in rows:
        group = stud.group_name or ""
        if not group:
            continue
        if group not in lessons_by_group:
            lessons_by_group[group] = W.group_lessons(db, group)
        lessons = lessons_by_group[group]
        records = W.student_records(db, stud.surname, stud.name, group)
        if intent == "debtors":
            if W.debts(lessons, records, scale=W.lesson_scale_map(db, lessons)):
                debtors.append(f"{W.display_name(stud)} ({group})")
            continue
        avg = W.average(lessons, records, cfg, scale=W.lesson_scale_map(db, lessons))
        #Порог тот же, что красит дашборды (2.5) — свой не придумываем.
        if avg and avg < 2.5:
            risky.append(f"{W.display_name(stud)} ({group}) — {avg}")

    found = debtors if intent == "debtors" else risky
    what = "с задолженностями" if intent == "debtors" else "в зоне риска"
    if not found:
        return {"text": f"Студентов {what} нет — по всему колледжу чисто. 🐯",
                "mood": "happy", "intent": intent, "facts": {"count": 0}}
    #Список фамилий LLM переписывать не должен — это факты о людях.
    shown = found[:15]
    tail = f" И ещё {len(found) - len(shown)}." if len(found) > len(shown) else ""
    return {"text": f"Студентов {what}: {len(found)}. " + "; ".join(shown) + "." + tail,
            "mood": "sad", "intent": intent, "no_voice": True,
            "facts": {"count": len(found)}}


def _vector_facts(msg: str, user: User, db: Session, cfg: dict) -> dict:
    """Фактический ответ (text/mood/intent/facts) по роли из РЕАЛЬНЫХ данных.

    Единый разбор запроса — vector_nlu.classify (тот же лексикон, что у десктопа). intent
    ВСЕГДА в ответе: по нему клиент выбирает эмоцию/анимацию маскота. Числа — только из SQL."""
    role = user.role if user.role in ("student", "teacher", "admin") else "student"
    subjects = _known_subjects(user, db)
    surnames = _known_surnames(user, db)
    nlu = vector_nlu.classify(msg, surnames=surnames, subjects=subjects)
    intent, subject, surname, day = nlu["intent"], nlu["subject"], nlu["surname"], nlu["day"]
    help_text = _HELP_BY_ROLE[role]

    # Общие для всех ролей: приветствие / помощь / благодарность / факты о заведении.
    if intent == "hello":
        return {"text": f"{_HELLO_PREFIX[role]} {help_text}", "mood": "happy",
                "intent": "hello", "facts": {}}
    if intent in ("help", "unknown"):
        return {"text": help_text, "mood": "happy" if intent == "help" else "neutral",
                "intent": "help" if intent == "help" else "unknown", "facts": {}}
    if intent == "thanks":
        return {"text": "Всегда рад помочь! 🐯", "mood": "happy", "intent": "thanks", "facts": {}}
    if intent == "weather":
        #Погода — такой же факт, как средний балл: берём у метеослужбы, не сочиняем.
        #Нет связи — честное «не знаю» (weather.answer сам это учитывает).
        import weather as _w
        data = _w.current()
        return {"text": _w.answer(),
                "mood": "happy" if data else "neutral",
                "intent": "weather",
                "facts": {"weather": data or {}}}
    if intent == "about_vsgutu":
        return {"text": _ABOUT_VSGUTU, "mood": "neutral", "intent": "about_vsgutu", "facts": {}}
    if intent == "about_college":
        return {"text": _ABOUT_COLLEGE, "mood": "neutral", "intent": "about_college", "facts": {}}
    if intent == "howto":
        return {"text": _HOWTO, "mood": "happy", "intent": "howto", "facts": {}}

    # ── СТУДЕНТ: только свои данные (privacy-by-design) ──────────────────────────────
    if role == "student":
        group = user.group_name
        lessons = W.group_lessons(db, group)
        records = W.student_records(db, user.surname, user.name, group)
        scale_map = W.lesson_scale_map(db, lessons)

        if intent == "schedule":
            text, facts = _schedule_answer(db, group, msg, day)
            return {"text": text, "mood": "neutral", "intent": "schedule", "facts": facts}
        if intent == "groups":
            return {"text": f"Твоя группа — {group}." if group else "Группа за тобой не закреплена.",
                    "mood": "neutral", "intent": "groups", "facts": {"group": group}}
        if intent == "debtors":
            d = W.debts(lessons, records, scale=scale_map)
            text = "Задолженностей нет — так держать! 🐯" if not d else \
                "Есть задолженности: " + "; ".join(d) + "."
            return {"text": text, "mood": "happy" if not d else "sad",
                    "intent": "debtors", "facts": {"debts": len(d)}}
        if intent == "absences":
            a = W.absences(lessons, records)
            return {"text": f"Пропусков всего: {a['всего']} (Н: {a['Н']}, Б: {a['Б']}, О: {a['О']}).",
                    "mood": "neutral" if a["всего"] else "happy", "intent": "absences", "facts": a}
        if intent == "homework":
            return _homework_answer(lessons, records, subject)
        if intent == "grade_count":
            b = _grade_breakdown(lessons, records, scale=scale_map)
            if subject:
                subj_lessons = [l for l in lessons if l.subject == subject]
                bs = _grade_breakdown(subj_lessons, records, scale=scale_map)
                return {"text": f"Оценок по предмету «{subject}» — {bs['всего']} "
                                f"(5: {bs['5']}, 4: {bs['4']}, 3: {bs['3']}, 2: {bs['2']}).",
                        "mood": "neutral", "intent": "grade_count", "facts": bs}
            return {"text": f"Всего у тебя оценок — {b['всего']} "
                            f"(пятёрок: {b['5']}, четвёрок: {b['4']}, троек: {b['3']}, двоек: {b['2']}).",
                    "mood": "happy" if b["2"] == 0 else "neutral",
                    "intent": "grade_count", "facts": b}
        if intent == "subject_grades" and subject:
            per = [p for p in W.per_subject_averages(lessons, records, cfg, scale=scale_map)
                   if p["subject"] == subject]
            if not per:
                return {"text": f"По предмету «{subject}» у тебя пока нет занятий с оценками.",
                        "mood": "neutral", "intent": "subject_grades", "facts": {}}
            p = per[0]
            marks = [records.get(l.id) for l in lessons
                     if l.subject == subject and l.type == "Практика"
                     and W.grading.to_five_point(records.get(l.id), scale_map.get(l.id, W.grading.DEFAULT_SCALE)) is not None]
            avg_txt = f"средний {p['average']}" if p["average"] else "оценок ещё нет"
            body = (", ".join(marks)) if marks else "—"
            return {"text": f"По предмету «{subject}»: {avg_txt}. Оценки: {body}.",
                    "mood": _mood_by_avg(p["average"]), "intent": "subject_grades",
                    "facts": {"subject": subject, "average": p["average"]}}
        if intent == "grades" or intent == "subject_grades":
            per = W.per_subject_averages(lessons, records, cfg, scale=scale_map)
            graded = [p for p in per if p["average"]]
            if not graded:
                return {"text": "Оценок по практикам пока нет — как появятся, покажу. 🐯",
                        "mood": "neutral", "intent": "grades", "facts": {}}
            body = "; ".join(f"{p['subject']} — {p['average']}" for p in graded)
            return {"text": f"Твой средний по предметам: {body}.", "mood": "neutral",
                    "intent": "grades", "facts": {"subjects": len(graded)}}
        if intent == "zet":
            return _zet_facts(db, user.surname, user.name, group, cfg)
        # average и всё остальное (at_risk/roster/teachers/group_stats недоступны студенту)
        avg = W.average(lessons, records, cfg, scale=scale_map)
        if intent == "server_state":
            #Состояние сервера — не учебные данные, и студенту их знать незачем. Молчать
            #нельзя: без явной ветки вопрос про диск проваливался бы в средний балл, то
            #есть Вектор отвечал бы уверенно и не на тот вопрос.
            return {"text": "Про сервер знает администратор — это не учебные данные. "
                            "Я могу показать твой средний балл, оценки, пропуски, долги, "
                            "домашние задания и расписание. 🐯",
                    "mood": "neutral", "intent": "help", "facts": {}}
        if intent in ("at_risk", "roster", "teachers", "group_stats"):
            return {"text": "Эти данные — для преподавателя. Я могу показать твой средний балл, "
                            "оценки, пропуски, долги, домашние задания и расписание. 🐯",
                    "mood": "neutral", "intent": "help", "facts": {}}
        return {"text": f"Твой средний балл — {avg}. " + W.grading.methodology_text(cfg),
                "mood": _mood_by_avg(avg), "intent": "average", "facts": {"average": avg}}

    # ── ПРЕПОДАВАТЕЛЬ: только свои группы/предметы ──────────────────────────────────
    if role == "teacher":
        ty0, ts0 = W.current_term(cfg)
        pairs = W.teacher_assignments(db, user.id, ty0, ts0)
        groups = sorted({g for g, _s in pairs})
        #Предметы ЭТОГО препода В ЭТОЙ КОНКРЕТНОЙ группе — не весь его набор предметов
        #(баг 3.3.1: раньше фильтровали занятия группы по ВСЕМ предметам препода, из-за
        #чего в чужой группе с совпавшим названием предмета тоже что-то находилось).
        subjects_by_group: dict = {}
        for g, s in pairs:
            subjects_by_group.setdefault(g, set()).add(s)
        if not groups:
            return {"text": "За вами пока нет групп с занятиями по вашим предметам. " + help_text,
                    "mood": "neutral", "intent": "help", "facts": {}}
        tscale = W.teacher_scale(user)

        if intent == "schedule":
            text, facts = _schedule_answer(db, groups[0], msg, day)
            return {"text": text, "mood": "neutral", "intent": "schedule", "facts": facts}
        if intent == "groups":
            return {"text": "Ваши группы: " + ", ".join(groups) + ".", "mood": "neutral",
                    "intent": "groups", "facts": {"groups": len(groups)}}
        if intent == "roster":
            g = groups[0]
            names = [W.display_name(s) for s in W.students_in_group(db, g)]
            body = ", ".join(names) if names else "список пуст"
            return {"text": f"Студенты группы {g} ({len(names)}): {body}.", "mood": "neutral",
                    "intent": "roster", "facts": {"group": g, "count": len(names)}}
        if intent == "homework":
            #Что ЗАДАЛ САМ преподаватель: занятия его групп по его же предметам.
            #Статуса сдачи нет — вопрос про группу целиком, и «сдано» относилось бы
            #непонятно к кому; за конкретным студентом идут в журнал.
            own = []
            for g in groups:
                allowed = subjects_by_group.get(g, set())
                own += [l for l in W.group_lessons(db, g) if l.subject in allowed]
            return _homework_answer(own, {}, subject)
        if intent in ("absences", "debtors") and surname:
            # пропуски/долги конкретного студента (по фамилии) в группах преподавателя
            for g in groups:
                for s in W.students_in_group(db, g):
                    if s.surname == surname:
                        gl = [l for l in W.group_lessons(db, g) if l.subject in subjects_by_group.get(g, set())]
                        rec = W.student_records(db, s.surname, s.name, g)
                        if intent == "absences":
                            a = W.absences(gl, rec)
                            return {"text": f"{W.display_name(s)}: пропусков {a['всего']} "
                                            f"(Н: {a['Н']}, Б: {a['Б']}, О: {a['О']}).",
                                    "mood": "neutral", "intent": "absences", "facts": a}
                        d = W.debts(gl, rec, scale=tscale)
                        txt = (f"У {W.display_name(s)} задолженностей нет." if not d
                               else f"{W.display_name(s)}: " + "; ".join(d) + ".")
                        return {"text": txt, "mood": "happy" if not d else "sad",
                                "intent": "debtors", "facts": {"debts": len(d)}}
            return {"text": f"Студента «{surname}» в ваших группах не нашёл.", "mood": "neutral",
                    "intent": "help", "facts": {}}

        # Агрегаты по группам (средний + зона риска) + ПОИМЁННЫЙ список отстающих.
        # Преподаватель видит своих студентов в журнале, поэтому назвать их долги — не
        # раскрытие ПДн, а прямой ответ на «у кого долги». Раньше отдавался только счётчик,
        # и Вектор честно не мог назвать фамилии.
        per, risky = [], []
        for g in groups:
            gl = [l for l in W.group_lessons(db, g) if l.subject in subjects_by_group.get(g, set())]
            vals = []
            for s in W.students_in_group(db, g):
                rec = W.student_records(db, s.surname, s.name, g)
                a = W.average(gl, rec, cfg, scale=tscale)
                dbts = W.debts(gl, rec, scale=tscale)
                if dbts or (0 < a < 3):
                    risky.append((W.display_name(s), g, a, dbts))
                if a > 0:
                    vals.append(a)
            per.append((g, round(sum(vals) / len(vals), 2) if vals else 0.0))
        if intent in ("at_risk", "debtors"):
            if not risky:
                return {"text": "Должников и отстающих сейчас нет — группы идут ровно.",
                        "mood": "happy", "intent": "at_risk",
                        "facts": {"at_risk": 0}, "no_voice": True}
            #no_voice: имена и причины отдаём ДОСЛОВНО, мимо LLM — иначе он их исказит
            #(серверная озвучка фамилии не обезличивает) или, как в жалобе, откажется
            #называть. Это фактический список, переформулировать нечего.
            lines = []
            for nm, g, a, dbts in risky:
                reason = "; ".join(dbts) if dbts else f"средний балл {a}"
                lines.append(f"• {nm} ({g}): {reason}")
            head = ("Задолженности есть у одного студента:" if len(risky) == 1
                    else f"Задолженности есть у {len(risky)} студентов:")
            return {"text": head + "\n" + "\n".join(lines),
                    "mood": "sad", "intent": "at_risk",
                    "facts": {"at_risk": len(risky)}, "no_voice": True}
        if intent in ("average", "group_stats", "grades"):
            body = "; ".join(f"{g}: {ga}" for g, ga in per)
            #len(risky), а не «risk»: такой переменной здесь нет и никогда не было —
            #вопрос преподавателя про средний балл/статистику падал с NameError в 500,
            #и Вектор выглядел «не видящим базу». Держит test_vector_teacher_group_stats.
            n_risky = len(risky)
            #Сколько СТУДЕНТОВ в группах преподавателя — прямой ответ на «сколько
            #студентов»: раньше на этот вопрос отдавались только средние по группам.
            n_students = sum(len(W.students_in_group(db, g)) for g in groups)
            return {"text": f"Средний по вашим группам — {body}. "
                            f"Всего студентов: {n_students}. В зоне риска: {n_risky}.",
                    "mood": "neutral", "intent": "group_stats",
                    "facts": {"groups": len(per), "students": n_students, "at_risk": n_risky}}
        if intent == "server_state":
            #Сервером занимается администратор. Отвечаем прямо, а не общей справкой:
            #иначе преподаватель решит, что Вектор просто не понял вопрос.
            return {"text": "Состояние сервера — к администратору, это не учебные данные. "
                            "Я могу показать ваши группы, оценки, долги, пропуски, "
                            "домашние задания и расписание. 🐯",
                    "mood": "neutral", "intent": "help", "facts": {}}
        return {"text": help_text, "mood": "neutral", "intent": "help", "facts": {}}

    # ── АДМИН: агрегаты по заведению, справочники и состояние сервера ──────────────
    #Вопросы, на которые у администратора ответа нет по существу. Раньше они молча
    #проваливались в счётчики: на «что задали» приходило «студентов — 47», то есть
    #уверенный ответ не на тот вопрос.
    if intent in ("homework", "zet", "subject_grades", "grade_count"):
        return {"text": "Это данные учебного процесса — их видят студент и его "
                        "преподаватель. Я могу показать справочники, сводку по колледжу "
                        "и состояние сервера. 🐯",
                "mood": "neutral", "intent": "help", "facts": {}}
    if intent == "server_state":
        return _server_state_facts(db)
    if intent in ("at_risk", "debtors"):
        #Общеколледжный срез: раньше эти вопросы у админа падали в счётчики, хотя
        #«кто в зоне риска» — ровно тот вопрос, ради которого админ и заходит.
        return _admin_risk_facts(db, cfg, intent)
    if intent == "teachers":
        rows = db.query(User).filter(User.role == "teacher", User.deleted == False).all()  # noqa: E712
        names = [W.display_name(t) for t in rows]
        body = ", ".join(names) if names else "список пуст"
        return {"text": f"Преподаватели колледжа ({len(names)}): {body}.", "mood": "neutral",
                "intent": "teachers", "facts": {"count": len(names)}}
    if intent == "groups":
        rows = db.query(Group).filter(Group.deleted == False).all()  # noqa: E712
        names = [g.name for g in rows]
        body = ", ".join(names) if names else "групп нет"
        return {"text": f"Группы колледжа ({len(names)}): {body}.", "mood": "neutral",
                "intent": "groups", "facts": {"count": len(names)}}
    n_students = db.query(User).filter(User.role == "student", User.deleted == False).count()  # noqa: E712
    n_teachers = db.query(User).filter(User.role == "teacher", User.deleted == False).count()  # noqa: E712
    n_parents = db.query(User).filter(User.role == "parent", User.deleted == False).count()  # noqa: E712
    n_groups = db.query(Group).filter(Group.deleted == False).count()  # noqa: E712
    n_subjects = db.query(Subject).filter(Subject.deleted == False).count()  # noqa: E712
    #Заявки на регистрацию — то, что ТРЕБУЕТ ДЕЙСТВИЯ, а не просто цифра в сводке.
    #Раньше о них можно было узнать, только зайдя на страницу заявок и вспомнив о ней.
    pending = 0
    try:
        pending = db.query(RegistrationRequest).filter(
            RegistrationRequest.status == "pending").count()
    except Exception:      # noqa: BLE001 — сводка не повод ронять ответ
        pending = 0
    text = (f"В системе: студентов — {n_students}, преподавателей — {n_teachers}, "
            f"родителей — {n_parents}, групп — {n_groups}, предметов — {n_subjects}.")
    if pending:
        text += f" ⚠️ Ждут одобрения заявки на регистрацию: {pending}."
    return {"text": text,
            "mood": "neutral" if not pending else "surprised", "intent": "group_stats",
            "facts": {"students": n_students, "teachers": n_teachers,
                      "parents": n_parents, "groups": n_groups,
                      "subjects": n_subjects, "pending_registrations": pending}}


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
    _teacher_check_assignment(db, user, lesson.group_name, lesson.subject,
                              lesson.year, lesson.semester)   #только своё назначение
    _ensure_current_term(W.load_config(db), lesson)   #архив прошлых семестров — read-only
    stud = db.query(User).filter(
        User.role == "student", User.surname == surname, User.name == name,
        User.group_name == lesson.group_name, User.deleted == False).first()  # noqa: E712
    if not stud:
        raise HTTPException(status_code=400, detail="Студент не найден в группе занятия")
    from ..models import grade_id as _grade_key
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
        from .. import rustore_push
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
            from .messenger import notify_grade_posted
            notify_grade_posted(db, stud.id, user.full_name or user.name or user.login,
                               lesson.subject, value)
        except Exception:
            pass
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
    журнале (как авто-нумерация в десктопе)."""
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
    number = payload.get("number")
    if not number:
        rows = db.query(Lesson.number).filter(
            Lesson.group_name == group, Lesson.subject == subject,
            Lesson.type == ltype, Lesson.deleted == False).all()  # noqa: E712
        number = (max((r[0] or 0) for r in rows) + 1) if rows else 1
    import uuid as _uuid
    lid = str(_uuid.uuid4())
    topic = (payload.get("topic") or "").strip()
    db.add(Lesson(id=lid, group_name=group, subject=subject, type=ltype,
                  number=int(number), topic=topic,
                  date=(payload.get("date") or "").strip(),
                  retake_date=(payload.get("retake_date") or "").strip(),
                  hour=int(payload.get("hour") or 0), extra={},
                  year=ty, semester=ts,
                  updated_at=_now_iso(), deleted=False))
    db.commit()
    if ltype == "ДЗ":
        _notify_homework(db, group, subject, lid, topic, int(number),
                         author_login=user.login)
    return {"ok": True, "id": lid, "number": int(number)}


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
            from .. import rustore_push
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
        from .. import rustore_push
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
        from .. import docx_export
        data = docx_export.build_journal_docx(group, subject, lessons, rows)
    else:
        from .. import xlsx_export
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
        from ..security import hash_password
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


@router.put("/admin/groups/{name:path}")
def admin_update_group(name: str, payload: dict = Body(...),
                       _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Правка группы (название — ключ, не меняем). Меняем список предметов/категорию."""
    row = db.get(Group, f"grp:{name}")
    if row is None or row.deleted:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    if "subjects" in payload:
        row.subjects = payload.get("subjects") or []
    if "category" in payload:
        row.category = _norm_category(payload.get("category"))
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
        from ..security import hash_password
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


# ── Выгрузка/загрузка данных и резервные копии (админка) ────────────────────────────
@router.get("/admin/data/datasets")
def admin_data_datasets(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Какие наборы данных есть и сколько в каждом записей — для галочек в интерфейсе.

    Считаем ЗДЕСЬ, а не на клиенте: администратор должен видеть объём до выгрузки («0
    родителей» объясняет, почему файл пустой, лучше, чем сам пустой файл)."""
    from .. import data_transfer as DT
    out = []
    for name, _f, model, label in DT.DATASETS:
        out.append({"name": name, "label": label,
                    "count": len(DT._query(db, name, model))})
    return {"datasets": out}


@router.get("/admin/data/export")
def admin_data_export(sets: str = "", request: Request = None,
                      _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """ZIP со всеми (или отмеченными) наборами данных — он же резервная копия.

    `sets` — имена через запятую; пусто = всё. Пароли в архив не попадают никогда
    (см. `data_transfer._SECRET_FIELDS`), поэтому выгрузка не является способом увести
    учётные записи. Действие аудируется: скачивание справочников с ПДн — событие, о
    котором должна остаться запись."""
    from .. import data_transfer as DT
    picked = [s.strip() for s in (sets or "").split(",") if s.strip()]
    from fastapi.responses import Response
    blob = DT.export_zip(db, picked or None)
    audit.log(db, request, actor=_admin.login, role="admin", action="data.export",
              detail=",".join(picked) if picked else "all")
    stamp = _now_iso()[:10]
    return Response(content=blob, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="gradebook-data-{stamp}.zip"'})


@router.post("/admin/data/inspect")
async def admin_data_inspect(file: UploadFile = File(...),
                             _admin: User = Depends(require_admin)):
    """Что лежит в присланном архиве — БЕЗ записи в базу.

    Обязательный шаг перед импортом: сначала показать состав, потом дать отметить, что
    вливать. Импорт «сразу при выборе файла» перезаписал бы боевые данные одним кликом."""
    from .. import data_transfer as DT
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Пустой файл")
    try:
        return DT.inspect_zip(blob)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/data/import")
async def admin_data_import(file: UploadFile = File(...), sets: str = Form(""),
                            request: Request = None,
                            _admin: User = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Влить ОТМЕЧЕННЫЕ наборы из архива (слияние по id, без очистки существующего).

    `sets` обязателен: импорт без явного выбора — это «залить всё, что было в файле», а
    такого умолчания у операции, меняющей боевые данные, быть не должно."""
    from .. import data_transfer as DT
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Пустой файл")
    picked = [s.strip() for s in (sets or "").split(",") if s.strip()]
    if not picked:
        raise HTTPException(status_code=400, detail="Не выбрано ни одного набора данных")
    try:
        result = DT.import_zip(db, blob, picked, _now_iso())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:      # noqa: BLE001 — битый архив не должен ронять сервер 500-кой
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать архив: {e}")
    audit.log(db, request, actor=_admin.login, role="admin", action="data.import",
              detail=",".join(f"{k}={v}" for k, v in result["written"].items()))
    return {"ok": True, **result}


@router.get("/admin/ai-config")
def admin_get_ai_config(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Текущие настройки ИИ (провайдер, ключ/скоуп GigaChat, модель Ollama)."""
    cfg = W.load_config(db)
    return {
        "vector_llm": cfg.get("vector_llm", "offline"),
        "gigachat_credentials": cfg.get("gigachat_credentials", ""),
        "gigachat_scope": cfg.get("gigachat_scope", "GIGACHAT_API_B2B"),
        "gigachat_model": cfg.get("gigachat_model", "GigaChat"),
        "local_model": cfg.get("local_model", "qwen2.5:3b"),
        "tts_enabled": cfg.get("tts_enabled", True),
        "tts_engine": cfg.get("tts_engine", "silero"),
        "stt_mode": cfg.get("stt_mode", "auto"),
        #Что реально стоит НА ЭТОМ хосте — чтобы админ выбирал, видя правду, а не
        #включал распознавание на машине, где движка нет.
        "stt_installed": _stt_installed(),
    }


@router.post("/admin/ai-config")
def admin_set_ai_config(payload: dict = Body(...), request: Request = None,
                        _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Сохранить настройки ИИ. Мержим В строку config (не затирая методику оценок и пр.),
    ставим серверную метку времени → синхронизируется на десктоп."""
    row = db.get(ConfigKV, "config")
    cur = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    for k in _AI_CFG_KEYS:
        if k in payload:
            cur[k] = payload[k]
    now = _now_iso()
    if row is None:
        db.add(ConfigKV(key="config", value=cur, updated_at=now, deleted=False))
    else:
        row.value = cur            #переприсваиваем dict — JSON-колонка увидит изменение
        row.updated_at = now
    db.commit()
    audit.log(db, request, actor=_admin.login, role="admin", action="ai.config")
    return {"ok": True}


@router.post("/admin/ai-config/test")
def admin_test_ai_config(payload: dict = Body(...),
                         _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Проверка провайдера: пробуем реально озвучить короткий факт. Ошибку НЕ глушим
    (в отличие от боевого voice), чтобы админ увидел причину. {ok, message}."""
    cfg = dict(W.load_config(db))
    for k in _AI_CFG_KEYS:      #проверяем с ПЕРЕДАННЫМИ (ещё не сохранёнными) значениями
        if k in payload:
            cfg[k] = payload[k]
    kind = (cfg.get("vector_llm") or "offline").strip()
    if kind == "offline":
        return {"ok": True, "message": "Оффлайн-режим: LLM не используется, ответы по фактам."}
    facts = "Средний балл — 4.5. Задолженностей нет."
    try:
        if kind == "gigachat":
            out = vector_llm._voice_gigachat(cfg, facts, "student", "как у меня дела")
        else:
            out = vector_llm._voice_ollama(cfg, facts, "student", "как у меня дела")
        return {"ok": True, "message": (out or "")[:200]}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}


# ПРИМЕЧАНИЕ: канонический CRUD занятий (create/update/delete) определён ВЫШЕ
# (teacher_create_lesson и др. ~строка 993) — с учебным периодом и защитой архива.
# Здесь раньше был дублирующий, устаревший набор тех же роутов (без термина и без
# read-only архива). FastAPI брал первый зарегистрированный, поэтому дубль был мёртвым
# кодом-миной (ruff F811) и удалён.
