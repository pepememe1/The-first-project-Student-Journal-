"""Архив учебных групп: выпустилась или расформирована — но не удалена.

━━ ЗАЧЕМ ━━
Живая жалоба Влада (03.09.2026): «начался новый учебный год, набрали новые группы,
другие перешли на новый курс; если раньше группа была, но не перешла на следующий курс —
она идёт в архив, где видно предметы, студентов, закреплённых преподавателей и куратора».

━━ ПОЧЕМУ АРХИВ, А НЕ УДАЛЕНИЕ ━━
За группой стоят живые студенты, их оценки, посещаемость и история занятий. `deleted`
скрывает данные, архив — наоборот, оставляет их доступными для просмотра, убирая группу
лишь из рабочих списков. Ведомость выпускников должна открываться через год так же, как
вчера.

━━ ПОЧЕМУ ПРЕДЛОЖЕНИЕ, А НЕ АВТОМАТ ━━
🔥 Урок уже оплачен `stale_groups` (25.08.2026): группа пропадает из расписания и по
причине СБОЯ ПОРТАЛА, а не только потому, что выпустилась. Автоматический архив в такой
день унёс бы половину колледжа молча, и заметили бы это по жалобам студентов. Поэтому
здесь считаются КАНДИДАТЫ, а решение принимает администратор — тем же приёмом, что и со
`stale_groups`.

━━ С ЧЕМ СРАВНИВАЕМ ━━
⚠️ Курс приходит с портала ВСГУТУ и собственной истории не имеет: «третий курс» сегодня
и «третий курс» год назад выглядят одинаково. Поэтому у группы хранится последний
засвидетельствованный курс вместе с учебным годом (`last_course`, `last_course_year`) —
без этой пары сравнивать не с чем, и «не перешла» вычислить нельзя в принципе.

⚠️ Свидетельство обновляется на переводе периода и при явном пересчёте админом, но НЕ
при чтении списка. Иначе первый же показ списка стирал бы основание, по которому группа
в него попала, и второй показ выдавал бы пустоту — дефект, который выглядит как «само
починилось».
"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import Group, Lesson, SubjectHours, User

#Причины попадания в кандидаты. Строки короткие и человеческие: они уезжают в
#`archived_reason` и показываются администратору как есть.
REASON_NOT_ADVANCED = "не перешла на следующий курс"
REASON_NO_COURSE = "курс не определяется"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def witness(db, group_row, course) -> bool:
    """Запомнить текущий курс группы как свидетельство. True — если что-то изменилось.

    Зовётся из перевода периода и из явного пересчёта. Разделено с чтением намеренно
    (см. предупреждение в шапке модуля).
    """
    from . import webdata as W
    year = W.current_term(W.load_config(db))[0]
    if course is None:
        return False
    if group_row.last_course == course and group_row.last_course_year == year:
        return False
    group_row.last_course = int(course)
    group_row.last_course_year = year
    return True


def candidates(db) -> list[dict]:
    """Группы, похожие на выпустившиеся. Ничего не меняет — только считает.

    ПРИЗНАКА ДВА, и они независимы. Одного не хватает по существу:

    1. **Календарь ушёл вперёд, а портал — нет.** Ожидаемый курс считается формулой от
       года поступления (`study_hours.course_and_semester`), фактический берётся у
       портала. Факт МЕНЬШЕ ожидания — значит новый учебный год наступил, а группу на
       следующий курс не перевели. Этот признак работает СЕГОДНЯ, без накопленной
       истории, и ради него он и заведён: жалоба была про уже случившийся сентябрь, а
       не про будущий.
    2. **Свидетельство прошлого года.** У групп без `enrollment_year` формулы нет вовсе
       (поле заполняет импорт учебного плана, у части групп его никто не делал). Для них
       сравниваем с `last_course`, снятым на прошлом переводе периода.

    ⚠️ Группа, про которую не известно НИЧЕГО (ни года поступления, ни свидетельства),
    кандидатом не становится никогда. «Не знаю» — это не «выпустилась», и молча
    предлагать убрать живую группу на таком основании нельзя.
    """
    from . import webdata as W
    from study_hours import course_and_semester
    cfg = W.load_config(db)
    cur_year, cur_sem = W.current_term(cfg)
    out: list[dict] = []
    rows = (db.query(Group)
            .filter(Group.deleted == False, Group.archived == False)  # noqa: E712
            .all())
    for row in rows:
        actual = W.group_course(db, row.name)
        expected = None
        if row.enrollment_year:
            try:
                expected = course_and_semester(row.enrollment_year, cur_year, cur_sem)[0]
            except Exception:
                expected = None

        reason = ""
        if expected is not None and actual is not None and actual < expected:
            reason = f"{REASON_NOT_ADVANCED}: портал показывает {actual}, ожидался {expected}"
        elif (row.last_course and row.last_course_year
                and row.last_course_year != cur_year):
            if actual is None:
                reason = REASON_NO_COURSE
            elif actual <= row.last_course:
                reason = (f"{REASON_NOT_ADVANCED}: был {row.last_course} "
                          f"в {row.last_course_year}, сейчас {actual}")
        if not reason:
            continue

        out.append({
            "group": row.name,
            "course": actual,
            "expected_course": expected,
            "last_course": row.last_course,
            "last_course_year": row.last_course_year or "",
            "students": db.query(User).filter(User.group_name == row.name,
                                              User.role == "student",
                                              User.deleted == False).count(),  # noqa: E712
            "reason": reason,
        })
    out.sort(key=lambda r: r["group"])
    return out


def archive(db, name: str, reason: str = "") -> Group:
    """Убрать группу из рабочих списков, сохранив всё её содержимое."""
    row = db.get(Group, f"grp:{name}")
    if row is None or row.deleted:
        return None
    row.archived = True
    row.archived_at = _now_iso()
    row.archived_reason = reason or REASON_NOT_ADVANCED
    row.updated_at = _now_iso()
    return row


def unarchive(db, name: str) -> Group:
    """Вернуть группу в работу.

    ⚠️ Дверь наружу обязательна. Архив по ошибке без неё означал бы, что группу
    восстанавливает только правка базы руками — тем же правилом живёт снятие итоговой
    оценки, открывающее закрытый семестр.
    """
    row = db.get(Group, f"grp:{name}")
    if row is None or row.deleted:
        return None
    row.archived = False
    row.archived_reason = ""
    row.archived_at = ""
    row.updated_at = _now_iso()
    return row


def detail(db, name: str) -> dict | None:
    """Что показать по архивной группе: предметы, студенты, преподаватели, кураторы.

    Ровно то, что просили. Ничего не пересчитываем и не досоздаём — только читаем уже
    лежащее, потому что архив по определению не должен менять историю.
    """
    from . import webdata as W
    row = db.get(Group, f"grp:{name}")
    if row is None or row.deleted:
        return None

    hours = db.query(SubjectHours).filter(SubjectHours.group_name == name).all()
    tids = {h.teacher_id for h in hours if h.teacher_id}
    tids |= {h.teacher_id_2 for h in hours if getattr(h, "teacher_id_2", "")}
    tnames = ({u.id: W.display_name(u)
               for u in db.query(User).filter(User.id.in_(tids)).all()} if tids else {})

    #Предметы: и справочник группы, и то, по чему реально были часы. Объединяем, иначе
    #предмет без плана часов выпал бы из архива, хотя занятия по нему шли.
    subject_names = sorted({*(row.subjects or []), *(h.subject for h in hours if h.subject)})
    subjects = []
    for subj in subject_names:
        rows = [h for h in hours if h.subject == subj]
        subjects.append({
            "subject": subj,
            "teachers": sorted({tnames.get(h.teacher_id, "") for h in rows if h.teacher_id}
                               | {tnames.get(getattr(h, "teacher_id_2", ""), "")
                                  for h in rows if getattr(h, "teacher_id_2", "")} - {""}),
            "terms": sorted({f"{h.year} · {h.semester}" for h in rows if h.year}, reverse=True),
            "lessons": db.query(Lesson).filter(Lesson.group_name == name,
                                               Lesson.subject == subj,
                                               Lesson.deleted == False).count(),  # noqa: E712
        })

    students = [{"id": u.id, "name": W.display_name(u), "login": u.login}
                for u in db.query(User).filter(User.group_name == name,
                                               User.role == "student",
                                               User.deleted == False)  # noqa: E712
                .order_by(User.surname, User.name).all()]

    #Кураторы: группа лежит в списке curated_groups преподавателя (отдельного тумблера
    #«куратор» в продукте нет — это тот же список, который назначает админ).
    curators = [W.display_name(u)
                for u in db.query(User).filter(User.role == "teacher",
                                               User.deleted == False).all()  # noqa: E712
                if name in (u.curated_groups or [])]

    return {
        "group": row.name,
        "archived": bool(row.archived),
        "archived_at": row.archived_at or "",
        "archived_reason": row.archived_reason or "",
        "course": W.group_course(db, row.name),
        "last_course": row.last_course,
        "last_course_year": row.last_course_year or "",
        "specialty_code": row.specialty_code or "",
        "enrollment_year": row.enrollment_year,
        "subjects": subjects,
        "students": students,
        "curators": sorted(curators),
        "teachers": sorted({v for v in tnames.values() if v}),
    }


def archived_list(db) -> list[dict]:
    """Список уже отправленных в архив — с числом студентов, чтобы было видно объём."""
    rows = (db.query(Group)
            .filter(Group.deleted == False, Group.archived == True)  # noqa: E712
            .order_by(Group.name).all())
    return [{
        "group": r.name,
        "archived_at": r.archived_at or "",
        "archived_reason": r.archived_reason or "",
        "last_course": r.last_course,
        "last_course_year": r.last_course_year or "",
        "students": db.query(User).filter(User.group_name == r.name,
                                          User.role == "student",
                                          User.deleted == False).count(),  # noqa: E712
    } for r in rows]
