"""scale_conversion — смена шкалы оценивания преподавателя с переводом уже поставленных оценок.

━━ ЗАЧЕМ ━━
Шкала — личная настройка преподавателя (`User.prefs["grading_scale"]`), а оценка хранится
СЫРОЙ строкой и читается по ТЕКУЩЕЙ шкале того, кто ведёт пару (`webdata.lesson_scale_map`).
До 01.10.2026 смена шкалы была одной строкой в настройках, и живой прогон стенда показал
цену: прежние «5/4/3» стали «5 из 100», у всей группы средний 2.0, долгов втрое больше,
студент и родитель увидели двойки, а в буквенной шкале старые оценки пропали из журнала
вовсе. Теперь смена шкалы — это ПЕРЕВОД значений (правила — `grading.convert_scale_value`),
а спорные случаи (73 → «3 или 4») решает преподаватель в окне предпросмотра.

━━ ЧТО ПЕРЕВОДИТСЯ ━━
Ровно то, что читается шкалой этого преподавателя: оценки занятий «как практика»
(`grading.is_practice`) во ВСЕХ парах «группа + предмет + семестр», где он назначенный
преподаватель (`SubjectHours.teacher_id`) — включая архив прошлых семестров: архивную «5»
тоже читают по текущей шкале, и непереведённая она стала бы «5 из 100».
Посещаемость («Н», «Б», «О»), экзамены и чужие шкалы не трогаются.
⚠️ Список пар — та же связка, что у `lesson_scale_map`; разойдутся — перевод затронет не
те оценки, которые потом читаются новой шкалой.

━━ КАК ЗАПИСЫВАЕТСЯ ━━
Под замком записи (`_lock_for_write`): предпросмотр не доверяем — план пересчитывается
заново на момент записи. Метку `updated_at` ставит сервер (LWW), номер изменения ставят
триггеры базы — программы подтянут перевод обычным синком. Пушей студентам нет: это не
новые оценки, а те же самые в другой записи. В журнал аудита — одна строка с итогом.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm.attributes import flag_modified

from . import webdata as W
from .models import Grade, Lesson, SubjectHours, User

grading = W.grading
_CHUNK = 500


def _teacher_pairs(db, teacher_id: str) -> set:
    rows = (db.query(SubjectHours)
            .filter(SubjectHours.teacher_id == teacher_id,
                    SubjectHours.deleted == False).all())  # noqa: E712
    return {(r.group_name, r.subject, r.year or "", int(r.semester or 0)) for r in rows}


def _scaled_grades(db, teacher: User) -> list:
    """[(Grade, Lesson)] — оценки, которые читаются шкалой этого преподавателя."""
    pairs = _teacher_pairs(db, teacher.id)
    if not pairs:
        return []
    groups = sorted({p[0] for p in pairs})
    lessons = (db.query(Lesson).filter(Lesson.group_name.in_(groups),
                                       Lesson.deleted == False).all())  # noqa: E712
    by_id = {l.id: l for l in lessons
             if grading.is_practice(l.type)
             and (l.group_name, l.subject, l.year or "", int(l.semester or 0)) in pairs}
    ids = list(by_id)
    out = []
    for i in range(0, len(ids), _CHUNK):
        for g in (db.query(Grade).filter(Grade.lesson_id.in_(ids[i:i + _CHUNK]),
                                         Grade.deleted == False).all()):  # noqa: E712
            out.append((g, by_id[g.lesson_id]))
    return out


def plan(db, teacher: User, to_scale: str) -> dict:
    """Что станет с оценками при переходе на `to_scale`. Ничего не меняет.

    auto — переводятся однозначно (счётчик), disputed — спорные строки с вариантами,
    untouched — посещаемость и всё, что старой шкалой не распознано."""
    if to_scale not in grading.SCALES:
        raise ValueError("Неизвестная шкала")
    from_scale = W.teacher_scale(teacher)
    out = {"from": from_scale, "to": to_scale, "auto": 0, "untouched": 0, "disputed": [],
           "_auto_rows": []}
    if from_scale == to_scale:
        return out
    rows = _scaled_grades(db, teacher)
    names = {}
    sids = sorted({g.student_id for g, _l in rows if g.student_id})
    for i in range(0, len(sids), _CHUNK):
        for u in db.query(User).filter(User.id.in_(sids[i:i + _CHUNK])).all():
            names[u.id] = W.display_name(u)
    for g, l in rows:
        res = grading.convert_scale_value(g.grade, from_scale, to_scale)
        if res is None:
            out["untouched"] += 1
            continue
        options, default = res
        if len(options) == 1:
            out["auto"] += 1
            out["_auto_rows"].append((g, options[0]))
            continue
        out["disputed"].append({
            "id": g.id, "old": g.grade, "options": options, "default": default,
            "student": names.get(g.student_id) or f"{g.student_f} {g.student_n}".strip(),
            "group": l.group_name, "subject": l.subject,
            "lesson": f"{l.type} №{l.number}" if l.number else l.type,
            "date": l.date or "", "term": f"{l.year} · {l.semester}" if l.year else "",
        })
    out["disputed"].sort(key=lambda d: (d["group"], d["subject"], d["term"], d["student"],
                                        d["date"], d["lesson"]))
    return out


def public(p: dict) -> dict:
    """План без внутренних строк ORM — то, что уходит в ответ."""
    return {k: v for k, v in p.items() if not k.startswith("_")}


def apply(db, teacher: User, to_scale: str, choices: dict | None = None) -> dict:
    """Перейти на `to_scale` и перевести оценки. `choices` — {id оценки: выбранный вариант}
    для спорных строк; чего нет или что не из вариантов — по умолчанию (ближайшее).

    ⚠️ План считается ЗАНОВО под замком записи: между предпросмотром и нажатием «Применить»
    могли поставить новую оценку, и переводить надо то, что лежит в базе сейчас."""
    from .routers.web._common import _lock_for_write
    choices = choices or {}
    _lock_for_write(db)
    #🔒 ПРЕПОДАВАТЕЛЯ ПЕРЕЧИТЫВАЕМ ПОД ЗАМКОМ (02.10.2026). Его строка загружена ДО замка
    #(`get_current_user`), и при двух почти одновременных сменах шкалы (две вкладки, сайт
    #и старая программа через /me/prefs) вторая считала перевод ОТ УСТАРЕВШЕЙ шкалы:
    #оценки, уже лежащие в «100», разбирались как «5-балльные», не распознавались и
    #оставались в записи, которую новая шкала не читает, — журнал пустел.
    db.refresh(teacher)
    p = plan(db, teacher, to_scale)
    if p["from"] == to_scale:
        return {"ok": True, "from": p["from"], "to": to_scale, "converted": 0, "chosen": 0}
    now = datetime.now(timezone.utc).isoformat()
    by_id = {}
    for g, value in p["_auto_rows"]:
        by_id[g.id] = (g, value)
    disputed_ids = {d["id"]: d for d in p["disputed"]}
    if disputed_ids:
        rows = db.query(Grade).filter(Grade.id.in_(list(disputed_ids))).all()
        for g in rows:
            d = disputed_ids[g.id]
            pick = choices.get(g.id)
            by_id[g.id] = (g, pick if pick in d["options"] else d["default"])
    chosen = sum(1 for gid in disputed_ids if choices.get(gid) in disputed_ids[gid]["options"])
    for g, value in by_id.values():
        g.grade = value
        g.device = "web"
        g.updated_at = now
    prefs = dict(teacher.prefs or {})
    prefs["grading_scale"] = to_scale
    teacher.prefs = prefs
    flag_modified(teacher, "prefs")
    teacher.updated_at = now
    db.commit()
    from . import audit
    audit.log(db, actor=teacher.login, role=teacher.role, action="grading_scale.change",
              target=teacher.login,
              detail=(f"{p['from']} → {to_scale}: переведено {len(by_id)}, "
                      f"из них спорных {len(disputed_ids)} (выбрано вручную {chosen})"))
    return {"ok": True, "from": p["from"], "to": to_scale, "converted": len(by_id),
            "disputed": len(disputed_ids), "chosen": chosen, "untouched": p["untouched"]}
