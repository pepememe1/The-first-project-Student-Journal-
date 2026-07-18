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

from fastapi import (APIRouter, Body, Depends, HTTPException, Query, Request,
                     UploadFile, File)
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import (User, Group, Subject, Lesson, Grade, RegistrationRequest,
                      AuthSession, ConfigKV, TermGrade)
from .. import webdata as W
from .. import schedule_web
from .. import reg_utils, mailer, gost, audit, vector_llm
import vector_nlu   # общий с десктопом лексикон/классификатор (корень в sys.path через webdata)


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
def student_journal(year: str = Query(""), semester: int = Query(0),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Журнал студента: занятия сгруппированы по предметам, у каждого — своя оценка.
    По умолчанию — ТЕКУЩИЙ семестр; year+semester открывают архив прошлого периода."""
    _require("student", user)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    lessons = W.group_lessons(db, user.group_name, year=ty, semester=ts)
    records = W.student_records(db, user.surname, user.name, user.group_name)

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
    lessons = W.group_lessons(db, user.group_name, year=ty, semester=ts)
    records = W.student_records(db, user.surname, user.name, user.group_name)
    return {
        "term": {"year": ty, "semester": ts},
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
    records = W.student_records(db, user.surname, user.name, user.group_name)
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
        recs = W.student_records(db, s.surname, s.name, group)
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
                    year: str = Query(""), semester: int = Query(0),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Журнал группы по одному предмету преподавателя: студенты × занятия × оценки.
    По умолчанию — текущий семестр; year+semester открывают архив."""
    _require("teacher", user)
    _teacher_check_subject(user, subject)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
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
                     "average": W.average(lessons, recs, cfg)})
    return {
        "group": group, "subject": subject, "term": {"year": ty, "semester": ts},
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
        recs = W.student_records(db, s.surname, s.name, group)
        out.append({"surname": s.surname, "name": s.name,
                    "average": W.average(lessons, recs, cfg)})
    return {"group": group, "students": out}


@router.get("/teacher/stats")
def teacher_stats(group: str = Query(...), subject: str = Query(...),
                  year: str = Query(""), semester: int = Query(0),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Средний по группе за предмет преподавателя (по умолчанию — текущий семестр)."""
    _require("teacher", user)
    _teacher_check_subject(user, subject)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    lessons = W.group_lessons(db, group, subject, year=ty, semester=ts)
    studs = W.students_in_group(db, group)
    vals = [W.average(lessons, W.student_records(db, s.surname, s.name, group), cfg) for s in studs]
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


@router.get("/curator/group/{group}/subjects")
def curator_group_subjects(group: str, year: str = Query(""), semester: int = Query(0),
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Предметы курируемой группы за термин (ВСЕ предметы группы, не только «свои»)."""
    _require("teacher", user)
    _curator_check(user, group)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    subs = sorted({l.subject for l in W.group_lessons(db, group, year=ty, semester=ts) if l.subject})
    return {"group": group, "term": {"year": ty, "semester": ts}, "subjects": subs}


@router.get("/curator/group/{group}/subject/{subject}")
def curator_group_subject(group: str, subject: str, year: str = Query(""), semester: int = Query(0),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Студенты курируемой группы + оценки/средний по ЛЮБОМУ предмету группы (read-only).
    Ключевой скоуп безопасности: доступ по КУРИРУЕМОЙ ГРУППЕ, а не по предметам препода;
    запись недоступна (куратор не ставит оценки — только смотрит ведение журнала)."""
    _require("teacher", user)
    _curator_check(user, group)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    lessons = W.group_lessons(db, group, subject, year=ty, semester=ts)
    studs = W.students_in_group(db, group)
    rows = []
    for s in studs:
        recs = W.student_records(db, s.surname, s.name, group)
        grades = {l.id: recs.get(l.id, "") for l in lessons}
        rows.append({"surname": s.surname, "name": s.name,
                     "first_name": W.first_name(s), "patronymic": W.patronymic_of(s),
                     "grades": grades, "average": W.average(lessons, recs, cfg)})
    return {
        "group": group, "subject": subject, "term": {"year": ty, "semester": ts},
        "lessons": [{"id": l.id, "type": l.type, "number": l.number,
                     "topic": l.topic, "date": l.date} for l in lessons],
        "students": rows,
    }


# ИТОГОВЫЕ ОЦЕНКИ ЗА СЕМЕСТР + ВЕДОМОСТИ (промежуточная аттестация) ────────────────
def _term_grade_id(surname, name, subject, year, semester):
    return f"{surname}|{name}|{subject}|{year}|{semester}"


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
    _teacher_check_subject(user, subject)
    ty, ts = W.current_term(W.load_config(db))
    stud = db.query(User).filter(
        User.role == "student", User.surname == surname, User.name == name,
        User.group_name == group, User.deleted == False).first()  # noqa: E712
    if not stud:
        raise HTTPException(status_code=400, detail="Студент не найден в группе")
    gid = _term_grade_id(surname, name, subject, ty, ts)
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
    _teacher_check_subject(user, subject)
    ty, ts = _resolve_term(W.load_config(db), year, semester)
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
    _teacher_check_subject(user, subject)
    ty, ts = _resolve_term(W.load_config(db), year, semester)
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
        {"login": u.login, "name": W.display_name(u), "subjects": list(u.subjects or []),
         "curated_groups": list(u.curated_groups or [])},
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
        {"login": u.login, "surname": u.surname, "name": u.name,
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
        out.append({"name": g.name, "subjects": list(g.subjects or []), "students": n})
    return {"groups": out}


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
        "version": "Pre-release 2.9",
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
_NO_VOICE_INTENTS = {"hello", "thanks", "help", "unknown",
                     "about_vsgutu", "about_college", "schedule"}


@router.post("/vector/ask")
def vector_ask(payload: dict = Body(...),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Серверный «Вектор». ПРИНЦИП тот же, что в десктопе: цифры берутся из реальных
    данных (SQL) — модель их НЕ выдумывает. Фактический текст собирает `_vector_facts`,
    затем LLM-провайдер (GigaChat/Ollama/оффлайн — из СИНХРОНИЗИРОВАННОГО конфига админа)
    лишь ПЕРЕФОРМУЛИРУЕТ его в стиле Вектора. Студент видит только свои данные."""
    question = (payload.get("message") or "").strip()
    cfg = W.load_config(db)
    result = _vector_facts(question.lower(), user, db, cfg)
    #Озвучка: числа уже посчитаны и верны, LLM их не трогает — только стиль. Оффлайн или
    #ошибка провайдера → вернётся исходный фактический текст (сайт не ломается).
    #Приветствие/справку/благодарность НЕ озвучиваем (см. _NO_VOICE_INTENTS) — там нет
    #цифр, и модель начинает дописывать шаблоны с плейсхолдерами вместо фактов.
    if result.get("intent") not in _NO_VOICE_INTENTS:
        result["text"] = vector_llm.voice(cfg, result.get("text", ""), user.role, question)
    return result


# ── Голосовой ввод (Speech-to-Text) — ЗАГОТОВКА, распознаёт на ХОСТЕ ────────────────
@router.get("/vector/stt/status")
def vector_stt_status(user: User = Depends(get_current_user)):
    """Доступен ли голосовой ввод на сервере-хосте (стоит ли faster-whisper). По этому
    флагу веб-клиент показывает/прячет кнопку микрофона."""
    from .. import stt_service
    return {"available": stt_service.is_available()}


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
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустой аудиофайл.")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Аудио слишком большое (макс 10 МБ).")
    cfg = W.load_config(db)
    res = stt_service.transcribe_bytes(
        data, filename=file.filename or "audio.webm",
        size=cfg.get("stt_model", "large-v3"), device=cfg.get("stt_device", "auto"))
    if not res["ok"]:
        raise HTTPException(status_code=500, detail=res["error"])
    return {"text": res["text"]}


#Слова-триггеры «что умеешь / помощь / кто ты» и приветствие — распознаём ПЕРВЫМИ,
#чтобы Вектор отвечал по делу, а не сваливался в статистику. Дефолт тоже = подсказка.
# Факты о заведении — источник правды, НЕ генерация (как vector/knowledge.py на десктопе).
_ABOUT_VSGUTU = ("ВСГУТУ — Восточно-Сибирский государственный университет технологий и "
                 "управления, ведущий технический вуз Республики Бурятия в Улан-Удэ. "
                 "Технологический колледж — его структурное подразделение среднего "
                 "профессионального образования.")
_ABOUT_COLLEGE = ("Технологический колледж ВСГУТУ готовит специалистов среднего звена в "
                  "Улан-Удэ: IT, экономика, техника и другие направления. Этот электронный "
                  "журнал сделан как раз для него.")

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
            return sorted(set(user.subjects or []))
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
            out = []
            for g in W.teacher_groups(db, set(user.subjects or [])):
                out += [s.surname for s in W.students_in_group(db, g)]
            return sorted(set(out))
        rows = db.query(User.surname).filter(User.role == "student",
                                             User.deleted == False).all()  # noqa: E712
        return sorted({r[0] for r in rows if r[0]})
    except Exception:
        return []


def _grade_breakdown(lessons, records) -> dict:
    """Счёт оценок студента: всего практических оценок (2–5) и разбивка по баллам."""
    counts = {"5": 0, "4": 0, "3": 0, "2": 0}
    ids = {l.id for l in lessons if l.type == "Практика"}
    for lid, v in (records or {}).items():
        if lid in ids and v in counts:
            counts[v] += 1
    counts["всего"] = sum(counts[k] for k in ("5", "4", "3", "2"))
    return counts


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


def _schedule_answer(group: str, msg: str, day) -> tuple:
    """Ответ по расписанию группы (данные — серверный парсер портала schedule_web).

    ПРЕДМЕТ ищем по предметам САМОГО расписания (портал называет их иначе, чем журнал),
    а не по журнальному списку — иначе «иностранный язык» не находился, а ложный матч по
    общему слову показывал чужой предмет. Приоритет: назван предмет → когда он; назван
    день/сегодня/завтра → пары этого дня; иначе — сегодня."""
    if not group:
        return ("Не вижу твоей группы — расписание привязано к ней. Уточни у администратора.", {})
    data = schedule_web.get_group(group)
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
    if intent == "about_vsgutu":
        return {"text": _ABOUT_VSGUTU, "mood": "neutral", "intent": "about_vsgutu", "facts": {}}
    if intent == "about_college":
        return {"text": _ABOUT_COLLEGE, "mood": "neutral", "intent": "about_college", "facts": {}}

    # ── СТУДЕНТ: только свои данные (privacy-by-design) ──────────────────────────────
    if role == "student":
        group = user.group_name
        lessons = W.group_lessons(db, group)
        records = W.student_records(db, user.surname, user.name, group)

        if intent == "schedule":
            text, facts = _schedule_answer(group, msg, day)
            return {"text": text, "mood": "neutral", "intent": "schedule", "facts": facts}
        if intent == "groups":
            return {"text": f"Твоя группа — {group}." if group else "Группа за тобой не закреплена.",
                    "mood": "neutral", "intent": "groups", "facts": {"group": group}}
        if intent == "debtors":
            d = W.debts(lessons, records)
            text = "Задолженностей нет — так держать! 🐯" if not d else \
                "Есть задолженности: " + "; ".join(d) + "."
            return {"text": text, "mood": "happy" if not d else "sad",
                    "intent": "debtors", "facts": {"debts": len(d)}}
        if intent == "absences":
            a = W.absences(lessons, records)
            return {"text": f"Пропусков всего: {a['всего']} (Н: {a['Н']}, Б: {a['Б']}, О: {a['О']}).",
                    "mood": "neutral" if a["всего"] else "happy", "intent": "absences", "facts": a}
        if intent == "grade_count":
            b = _grade_breakdown(lessons, records)
            if subject:
                subj_lessons = [l for l in lessons if l.subject == subject]
                bs = _grade_breakdown(subj_lessons, records)
                return {"text": f"Оценок по предмету «{subject}» — {bs['всего']} "
                                f"(5: {bs['5']}, 4: {bs['4']}, 3: {bs['3']}, 2: {bs['2']}).",
                        "mood": "neutral", "intent": "grade_count", "facts": bs}
            return {"text": f"Всего у тебя оценок — {b['всего']} "
                            f"(пятёрок: {b['5']}, четвёрок: {b['4']}, троек: {b['3']}, двоек: {b['2']}).",
                    "mood": "happy" if b["2"] == 0 else "neutral",
                    "intent": "grade_count", "facts": b}
        if intent == "subject_grades" and subject:
            per = [p for p in W.per_subject_averages(lessons, records, cfg)
                   if p["subject"] == subject]
            if not per:
                return {"text": f"По предмету «{subject}» у тебя пока нет занятий с оценками.",
                        "mood": "neutral", "intent": "subject_grades", "facts": {}}
            p = per[0]
            marks = [records.get(l.id) for l in lessons
                     if l.subject == subject and l.type == "Практика" and records.get(l.id) in ("2", "3", "4", "5")]
            avg_txt = f"средний {p['average']}" if p["average"] else "оценок ещё нет"
            body = (", ".join(marks)) if marks else "—"
            return {"text": f"По предмету «{subject}»: {avg_txt}. Оценки: {body}.",
                    "mood": _mood_by_avg(p["average"]), "intent": "subject_grades",
                    "facts": {"subject": subject, "average": p["average"]}}
        if intent == "grades" or intent == "subject_grades":
            per = W.per_subject_averages(lessons, records, cfg)
            graded = [p for p in per if p["average"]]
            if not graded:
                return {"text": "Оценок по практикам пока нет — как появятся, покажу. 🐯",
                        "mood": "neutral", "intent": "grades", "facts": {}}
            body = "; ".join(f"{p['subject']} — {p['average']}" for p in graded)
            return {"text": f"Твой средний по предметам: {body}.", "mood": "neutral",
                    "intent": "grades", "facts": {"subjects": len(graded)}}
        # average и всё остальное (at_risk/roster/teachers/group_stats недоступны студенту)
        avg = W.average(lessons, records, cfg)
        if intent in ("at_risk", "roster", "teachers", "group_stats"):
            return {"text": "Эти данные — для преподавателя. Я могу показать твой средний балл, "
                            "оценки, пропуски, долги и расписание. 🐯",
                    "mood": "neutral", "intent": "help", "facts": {}}
        return {"text": f"Твой средний балл — {avg}. " + W.grading.methodology_text(cfg),
                "mood": _mood_by_avg(avg), "intent": "average", "facts": {"average": avg}}

    # ── ПРЕПОДАВАТЕЛЬ: только свои группы/предметы ──────────────────────────────────
    if role == "teacher":
        tsubjects = set(user.subjects or [])
        groups = W.teacher_groups(db, tsubjects)
        if not groups:
            return {"text": "За вами пока нет групп с занятиями по вашим предметам. " + help_text,
                    "mood": "neutral", "intent": "help", "facts": {}}

        if intent == "schedule":
            text, facts = _schedule_answer(groups[0], msg, day)
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
        if intent in ("absences", "debtors") and surname:
            # пропуски/долги конкретного студента (по фамилии) в группах преподавателя
            for g in groups:
                for s in W.students_in_group(db, g):
                    if s.surname == surname:
                        gl = [l for l in W.group_lessons(db, g) if l.subject in tsubjects]
                        rec = W.student_records(db, s.surname, s.name, g)
                        if intent == "absences":
                            a = W.absences(gl, rec)
                            return {"text": f"{W.display_name(s)}: пропусков {a['всего']} "
                                            f"(Н: {a['Н']}, Б: {a['Б']}, О: {a['О']}).",
                                    "mood": "neutral", "intent": "absences", "facts": a}
                        d = W.debts(gl, rec)
                        txt = (f"У {W.display_name(s)} задолженностей нет." if not d
                               else f"{W.display_name(s)}: " + "; ".join(d) + ".")
                        return {"text": txt, "mood": "happy" if not d else "sad",
                                "intent": "debtors", "facts": {"debts": len(d)}}
            return {"text": f"Студента «{surname}» в ваших группах не нашёл.", "mood": "neutral",
                    "intent": "help", "facts": {}}

        # Агрегаты по группам (средний + зона риска)
        per, risk = [], 0
        for g in groups:
            gl = [l for l in W.group_lessons(db, g) if l.subject in tsubjects]
            vals = []
            for s in W.students_in_group(db, g):
                a = W.average(gl, W.student_records(db, s.surname, s.name, g), cfg)
                if 0 < a < 3:
                    risk += 1
                if a > 0:
                    vals.append(a)
            per.append((g, round(sum(vals) / len(vals), 2) if vals else 0.0))
        if intent in ("at_risk", "debtors"):
            return {"text": (f"В зоне риска (средний ниже 3) сейчас {risk} студ." if risk
                             else "Отстающих (средний ниже 3) нет — группы идут ровно."),
                    "mood": "sad" if risk else "happy", "intent": "at_risk",
                    "facts": {"at_risk": risk}}
        if intent in ("average", "group_stats", "grades"):
            body = "; ".join(f"{g}: {ga}" for g, ga in per)
            return {"text": f"Средний по вашим группам — {body}. Студентов в зоне риска: {risk}.",
                    "mood": "neutral", "intent": "group_stats",
                    "facts": {"groups": len(per), "at_risk": risk}}
        return {"text": help_text, "mood": "neutral", "intent": "help", "facts": {}}

    # ── АДМИН: агрегаты по заведению + справочники ─────────────────────────────────
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
    n_groups = db.query(Group).filter(Group.deleted == False).count()  # noqa: E712
    return {"text": f"В системе: студентов — {n_students}, преподавателей — {n_teachers}, "
                    f"групп — {n_groups}.",
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
    _ensure_current_term(W.load_config(db), lesson)   #архив прошлых семестров — read-only
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
    _teacher_check_subject(user, subject)
    number = payload.get("number")
    if not number:
        rows = db.query(Lesson.number).filter(
            Lesson.group_name == group, Lesson.subject == subject,
            Lesson.type == ltype, Lesson.deleted == False).all()  # noqa: E712
        number = (max((r[0] or 0) for r in rows) + 1) if rows else 1
    import uuid as _uuid
    lid = str(_uuid.uuid4())
    #Новое занятие всегда в ТЕКУЩЕМ учебном периоде (штампуем год+семестр).
    ty, ts = W.current_term(W.load_config(db))
    db.add(Lesson(id=lid, group_name=group, subject=subject, type=ltype,
                  number=int(number), topic=(payload.get("topic") or "").strip(),
                  date=(payload.get("date") or "").strip(),
                  retake_date=(payload.get("retake_date") or "").strip(),
                  hour=int(payload.get("hour") or 0), extra={},
                  year=ty, semester=ts,
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
    _teacher_check_subject(user, row.subject)
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
    _teacher_check_subject(user, subject)
    cfg = W.load_config(db)
    ty, ts = _resolve_term(cfg, year, semester)
    lessons = W.group_lessons(db, group, subject, year=ty, semester=ts)
    rows = []
    for s in W.students_in_group(db, group):
        recs = W.student_records(db, s.surname, s.name, group)
        rows.append({"surname": s.surname, "name": s.name, "records": recs,
                     "average": W.average(lessons, recs, cfg)})
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
    #Имя/отчество: пересобираем name-ключ из имени и отчества (отчество храним отдельно).
    #ВАЖНО: смена name — это смена КЛЮЧА оценок (как и раньше при правке имени), поэтому
    #трогаем только если пришло name или patronymic. Иначе оставляем как есть.
    if "name" in payload or "patronymic" in payload:
        name_in = (payload.get("name") if "name" in payload else W.first_name(row)) or ""
        patr_in = (payload.get("patronymic") if "patronymic" in payload
                   else (row.patronymic or ""))
        row.name, row.patronymic = _compose_name(name_in, patr_in)
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
    audit.log(db, actor=_admin.login, role="admin", action="group.create", target=name)
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
    audit.log(db, actor=_admin.login, role="admin", action="group.delete", target=name)
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
                "gigachat_model", "local_model")


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
