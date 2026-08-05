"""
teacher.py — Кабинет преподавателя (чтение): назначения, журнал, студенты, средние, сводка.

Часть пакета `routers/web` (разрезан в 3.6: один файл на 4288 строк правили
62 коммита за полгода — он и был главным источником конфликтов при
одновременной работе). Общий роутер и хелперы — в `_common.py`; порядок
регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — общий router, модели, хелперы


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
    """Студенты группы со средним по предметам преподавателя (в этой группе).

    С 3.6 к каждому студенту прикладывается РИСК ОТЧИСЛЕНИЯ (`dropout_risk.py`) —
    преподаватель обязан видеть в своём списке тех, кто реально на грани. Риск считается
    ТОЛЬКО по предметам этого преподавателя в этой группе: судить по чужим он всё равно
    не вправе, а показать ему цифру, собранную из невидимых для него данных, значит
    показать необъяснимое число. Целостную картину по всем предметам видит куратор
    (`/curator/risk`)."""
    _require("teacher", user)
    cfg = W.load_config(db)
    ty, ts = W.current_term(cfg)
    #Средний считаем только по НАЗНАЧЕННЫМ этому преподу в ЭТОЙ группе предметам —
    #не по всем его предметам вообще (см. teacher_assignments).
    subjects = {s for g, s in W.teacher_assignments(db, user.id, ty, ts) if g == group}
    if not subjects:
        raise HTTPException(status_code=403, detail="Эта группа вам не назначена")
    #Только ТЕКУЩИЙ термин — иначе повторяющийся предмет (напр. «Физическая культура»)
    #тянул бы средний/риск из прошлых курсов той же группы.
    lessons = W.current_term_lessons(
        db, group, [l for l in W.group_lessons(db, group) if l.subject in subjects], cfg)
    tscale = W.teacher_scale(user)
    out = []
    for s in W.students_in_group(db, group):
        recs = W.student_records(db, s.surname, s.name, group)
        risk = W.dropout_risk_for_student(db, s.surname, s.name, group,
                                          cfg=cfg, lessons=lessons, records=recs)
        out.append({"surname": s.surname, "name": s.name,
                    "average": W.average(lessons, recs, cfg, scale=tscale),
                    #Ниже порога видимости риска нет вовсе — отдаём null, чтобы клиент
                    #не решал этот вопрос второй раз своим порогом.
                    "risk": risk if risk["visible"] else None})
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


@router.get("/teacher/subjects-overview")
def teacher_subjects_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Диаграммы вкладки «ИИ Помощник» (3.6.1): общая категоризация студентов
    (отличники/хорошисты/успевающие/неуспевающие) по ВСЕЙ нагрузке преподавателя +
    та же категоризация ПО КАЖДОМУ ПРЕДМЕТУ (агрегат по всем его группам). Второй
    уровень (по группам внутри предмета) — GET /teacher/subjects-overview/groups."""
    _require("teacher", user)
    cfg = W.load_config(db)
    ty, ts = W.current_term(cfg)
    return W.teacher_subjects_overview(db, user, ty, ts)


@router.get("/teacher/subjects-overview/groups")
def teacher_subjects_overview_groups(subject: str = Query(...),
                                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Drill-down по предмету: категоризация ОТДЕЛЬНО по каждой группе, где
    преподаватель ведёт этот предмет (§/teacher/subjects-overview)."""
    _require("teacher", user)
    cfg = W.load_config(db)
    ty, ts = W.current_term(cfg)
    return W.teacher_subject_groups(db, user, ty, ts, subject)


@router.get("/teacher/summary")
def teacher_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Сводка преподавателя для вкладки «ИИ Помощник» (3.6): его группы, в каждой —
    его предметы со средним, плюс сколько студентов в зоне риска.

    ОДИН запрос вместо N. Раньше такую картину можно было собрать только перебором
    `/teacher/stats` по каждой паре (группа, предмет) — на пяти группах это полтора
    десятка запросов при открытии страницы, причём каждый заново поднимал бы одни и те
    же занятия и ведомости из базы. Здесь занятия и записи студентов читаются по РАЗУ
    на группу и переиспользуются и для средних, и для риска."""
    _require("teacher", user)
    cfg = W.load_config(db)
    ty, ts = W.current_term(cfg)
    tscale = W.teacher_scale(user)
    pairs = W.teacher_assignments(db, user.id, ty, ts)

    by_group = {}
    for g, s in pairs:
        by_group.setdefault(g, set()).add(s)

    groups = []
    for group in sorted(by_group):
        subjects = by_group[group]
        #Только ТЕКУЩИЙ термин — иначе повторяющийся предмет (напр. «Физическая культура»)
        #тянул бы средний/риск из прошлых курсов той же группы в «сейчас».
        lessons = W.current_term_lessons(
            db, group, [l for l in W.group_lessons(db, group) if l.subject in subjects], cfg)
        studs = W.students_in_group(db, group)
        recs = {s.id: W.student_records(db, s.surname, s.name, group) for s in studs}

        subj_rows = []
        for subject in sorted(subjects):
            sl = [l for l in lessons if l.subject == subject]
            vals = [v for v in (W.average(sl, recs[s.id], cfg, scale=tscale) for s in studs) if v > 0]
            subj_rows.append({
                "subject": subject,
                "average": round(sum(vals) / len(vals), 2) if vals else 0.0,
                #«По скольким студентам посчитано» — средний по трём из двадцати пяти и
                #по всем двадцати пяти выглядит одинаково, а значит разное.
                "graded_students": len(vals),
                "lessons": len(sl),
            })

        all_vals = [v for v in (W.average(lessons, recs[s.id], cfg, scale=tscale) for s in studs) if v > 0]
        at_risk = 0
        for s in studs:
            r = W.dropout_risk_for_student(db, s.surname, s.name, group,
                                           cfg=cfg, lessons=lessons, records=recs[s.id])
            if r["visible"] and r["level"] in ("medium", "high", "critical"):
                at_risk += 1
        groups.append({"group": group, "students": len(studs),
                       "average": round(sum(all_vals) / len(all_vals), 2) if all_vals else 0.0,
                       "at_risk": at_risk, "subjects": subj_rows})

    #Куратор (§role — teacher с непустым curated_groups) видит ЕЩЁ и курируемые группы,
    #но СО ВСЕМИ их предметами (не только своими) — живой отзыв: «курируемые группы со
    #всеми предметами» не показывались вовсе, панель знала только про explicit-назначения.
    #Та же форма ответа, что у groups[] выше, — TeacherOverview.vue рисует вторым разделом.
    curator_groups = W.curator_summary_groups(db, user, ty, ts) if user.curated_groups else []

    return {"term": {"year": ty, "semester": ts}, "groups": groups,
            "subjects": sorted({s for _g, s in pairs}), "curator_groups": curator_groups}
