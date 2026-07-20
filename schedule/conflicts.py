"""
conflicts.py — клиентская (десктоп) сверка расписаний ОДНОГО слота при переносе пары.

Зеркало серверного schedule_conflicts.slot_conflicts, но на локальных данных: снимок
портала из кэша (store.load_cached) + локальные правки (overrides). Чистый stdlib, без
Qt и сети — вызывается прямо при drag-drop, работает офлайн.

⚠️ Ручных отметок «совместная пара» (ScheduleJointMark) на десктопе НЕТ: это серверная
деталь, в синк она не входит. Поэтому суппресс здесь держится только на правиле «одна и
та же пара у нескольких групп — норма»: совпадение считается накладкой, лишь когда
занятие РАЗНОЕ. Редкий случай «две разные пары намеренно в одной аудитории» десктоп
покажет как накладку — на сервере его можно погасить отметкой, здесь нельзя.
"""


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def slot_conflicts(editing_group: str, week, day: str, pair_no,
                   room: str = "", teacher: str = "", subject: str = "") -> dict:
    """{"room": [...], "teacher": [...]} — занятость аудитории/преподавателя у ДРУГИХ
    групп в этом слоте предложенными значениями. Пустые списки — накладок нет."""
    from schedule import store as sched_store
    try:
        week, pair_no = int(week), int(pair_no)
    except (TypeError, ValueError):
        return {"room": [], "teacher": []}

    names = set()
    snap = sched_store.load_cached()
    if snap:
        names |= set(snap.group_names())
    try:
        from schedule.overrides import list_overrides
        for o in list_overrides():
            if o.get("group_name"):
                names.add(o["group_name"])
    except Exception:
        pass

    room_n, teacher_n, subject_n = _norm(room), _norm(teacher), _norm(subject)
    room_hits, teacher_hits = [], []
    for name in names:
        if name == editing_group:
            continue                       #сам с собой не конфликтует
        gs = sched_store.group_schedule(name)
        if not gs:
            continue
        for ls in gs.weeks.get(week, {}).get(day, []):
            if int(getattr(ls, "pair_no", 0)) != pair_no:
                continue
            o_room = _norm(getattr(ls, "room", ""))
            o_teacher = _norm(getattr(ls, "teacher", ""))
            o_subject = _norm(getattr(ls, "subject", ""))
            same_lesson = (o_subject == subject_n)
            info = {"group": name,
                    "subject": getattr(ls, "subject", "") or getattr(ls, "raw", ""),
                    "room": getattr(ls, "room", ""), "teacher": getattr(ls, "teacher", "")}
            if room_n and o_room == room_n and not (same_lesson and o_teacher == teacher_n):
                room_hits.append(info)
            if teacher_n and o_teacher == teacher_n and not (same_lesson and o_room == room_n):
                teacher_hits.append(info)
    return {"room": room_hits, "teacher": teacher_hits}
