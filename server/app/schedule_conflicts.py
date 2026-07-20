"""
schedule_conflicts.py — сверка расписаний: поиск накладок.

Накладка — это когда один преподаватель (или одна аудитория) в ОДИН слот
(неделя · день · номер пары) занят РАЗНЫМИ занятиями у разных групп.

⚠️ Слово «разными» здесь несущее, и это выяснилось на живых данных портала. Наивное
правило «несколько групп в одном слоте = накладка» дало на реальном расписании ВСГУТУ
638 «проблем», из которых 622 (97%) оказались обычными общими парами: совместные лекции
и подгруппы одного курса (К65/1 и К65/2 сидят на одной химии). Такой список админ
открыл бы один раз.

Поэтому сравниваются САМИ ЗАНЯТИЯ: для преподавателя — пара (предмет, аудитория), для
аудитории — (предмет, преподаватель). Совпали у всех групп → это одна пара, на которую
пришло несколько групп, и тревожить некого. Различаются → преподаватель физически не
может вести два разных предмета одновременно, а в одной аудитории не могут идти два
разных занятия: вот это и есть накладка.

Отдельно остаётся ручная отметка `schedule_joint_marks` — для случаев, которые правилом
не покрываются (например, одна аудитория намеренно делится между двумя занятиями).

⚠️ ИСТОЧНИК ДАННЫХ — УЖЕ СОБРАННЫЙ снимок портала (`schedule_web.full_state`). Своей
сборки мы не запускаем никогда: она стоит ~68 GET и десятки секунд, а боевой VPS
одноядерный — детектор, дёргающий сборку на каждое открытие админки, просто повесил бы
сервер. Снимок ещё не готов → честно сообщаем `building=True` и пустой список. Это
важно различать на клиенте: «накладок нет» и «мы ещё не смотрели» — разные вещи, и
выдавать второе за первое значит усыплять составителя расписания ложным спокойствием.

Наложение админ-правок делается ТЕМ ЖЕ кодом, что и выдача расписания студенту
(`routers.web._apply_overrides`). Дублировать его здесь нельзя: разъехавшись, проверка
начнёт искать накладки в расписании, которого никто не видит.
"""
from . import schedule_web
from .models import ScheduleJointMark, ScheduleOverride, joint_mark_id

#Порядок дней для сортировки выдачи: админу удобнее читать проблемы по расписанию, а
#не в случайном порядке словаря.
_DAY_ORDER = {d: i for i, d in enumerate(["Пнд", "Втр", "Срд", "Чтв", "Птн", "Сбт"])}


def _norm(value: str) -> str:
    """Приведение для СРАВНЕНИЯ: «Иванов И.И.», «иванов и.и.» и «Иванов  И.И. » —
    один и тот же человек. Для показа берём исходное написание, а не это."""
    return " ".join((value or "").strip().lower().split())


def _iter_slots(merged: dict):
    """(week:int, day:str, pair_no:int, lesson:dict) по слитому расписанию группы."""
    for wk, days in (merged.get("weeks") or {}).items():
        try:
            week = int(wk)
        except (TypeError, ValueError):
            continue                      #мусорный ключ недели пропускаем молча
        for day, lessons in (days or {}).items():
            for lesson in (lessons or []):
                try:
                    pair_no = int(lesson.get("pair_no") or 0)
                except (TypeError, ValueError):
                    continue
                yield week, day, pair_no, lesson


def merged_schedules(db) -> tuple:
    """({группа: слитое расписание}, building). Портальная основа — из готового снимка."""
    #Ленивый импорт: routers.web импортирует этот модуль, прямой импорт дал бы цикл.
    from .routers.web import _apply_overrides

    snap, building = schedule_web.full_state()
    names = set(snap.groups.keys()) if snap is not None else set()
    #Группы, существующие ТОЛЬКО в правках: колледж без страницы на портале.
    rows = (db.query(ScheduleOverride.group_name)
            .filter(ScheduleOverride.deleted == False)  # noqa: E712
            .distinct().all())
    names |= {r[0] for r in rows if r[0]}

    out = {}
    for name in names:
        gs = snap.groups.get(name) if snap is not None else None
        merged = _apply_overrides(db, name, gs.to_dict() if gs is not None else None)
        if merged:
            out[name] = merged
    return out, building


def _joint_ids(db) -> set:
    return {row.id for row in db.query(ScheduleJointMark).all()}


def find_conflicts(db) -> dict:
    """{"building": bool, "count": int, "items": [...]}.

    Пустой список при building=True означает «ещё не проверяли», а не «всё чисто»."""
    schedules, building = merged_schedules(db)
    joint = _joint_ids(db)

    #(kind, week, day, pair, значение) → {"groups": {...}, "sigs": {...}, "subjects": {...}}
    buckets: dict = {}
    labels: dict = {}                 #исходное написание значения — для показа админу
    for group, sched in schedules.items():
        for week, day, pair_no, lesson in _iter_slots(sched):
            subject = _norm(lesson.get("subject"))
            teacher = _norm(lesson.get("teacher"))
            room = _norm(lesson.get("room"))
            #Подпись занятия. Для преподавателя важно, ЧТО и ГДЕ он ведёт; для
            #аудитории — ЧТО и КТО в ней. Совпадение подписи означает, что это одна и
            #та же пара, просто на неё пришло несколько групп.
            for kind, value, raw, sig in (("teacher", teacher, lesson.get("teacher"), (subject, room)),
                                          ("room", room, lesson.get("room"), (subject, teacher))):
                if not value:
                    continue          #пустое поле ни с чем конфликтовать не может
                key = (kind, week, day, pair_no, value)
                labels.setdefault(key, (raw or "").strip())
                b = buckets.setdefault(key, {"groups": set(), "sigs": set(), "subjects": set()})
                b["groups"].add(group)
                b["sigs"].add(sig)
                b["subjects"].add((lesson.get("subject") or "").strip())

    items = []
    for key, b in buckets.items():
        groups, sigs = b["groups"], b["sigs"]
        if len(groups) < 2:
            continue
        #⚠️ ГЛАВНЫЙ ФИЛЬТР. Несколько групп на одной паре — это НОРМА, а не ошибка:
        #совместная лекция и подгруппы одного курса (К65/1 и К65/2) в реальном
        #расписании ВСГУТУ дают 97% всех совпадений. Проверка на живых данных портала
        #давала 638 «проблем», из которых 622 были обычными общими парами — такой
        #список админ просто перестал бы открывать.
        #
        #Настоящая накладка — когда занятия РАЗНЫЕ: преподаватель в одно время ведёт
        #разные предметы или сидит в разных аудиториях (физически невозможно), либо в
        #одной аудитории идут два разных занятия. Одинаковая подпись = одна пара.
        if len(sigs) < 2:
            continue
        kind, week, day, pair_no, value = key
        mark_id = joint_mark_id(kind, week, day, pair_no, value)
        if mark_id in joint:
            continue                  #помечено как совместная пара — это не ошибка
        items.append({
            "id": mark_id,            #он же ключ, которым админ пометит слот совместным
            "kind": kind,
            "value": labels.get(key, value),
            "week": week,
            "day": day,
            "pair_no": pair_no,
            "groups": sorted(groups),
            "subjects": sorted(s for s in b["subjects"] if s),
        })

    items.sort(key=lambda c: (c["week"], _DAY_ORDER.get(c["day"], 9),
                              c["pair_no"], c["kind"], c["value"]))
    return {"building": building, "count": len(items), "items": items}


def slot_conflicts(db, editing_group: str, week, day: str, pair_no,
                   room: str = "", teacher: str = "", subject: str = "") -> dict:
    """Накладки ОДНОГО слота против ДРУГИХ групп — для живой проверки при переносе пары.

    Редактор дёргает это сразу после drag-drop: черновик ещё не сохранён, поэтому
    проверяем ПРЕДЛОЖЕННЫЕ room/teacher/subject в целевом слоте против того, что у
    других групп уже стоит в это же время. Правило совпадает с find_conflicts: занятость
    аудитории/преподавателя считается накладкой, только если занятие РАЗНОЕ (иначе это
    общая пара — норма). Помеченные «совместными» слоты не считаем.

    building=True → полный снимок портала ещё собирается, проверка НЕполна (клиент
    обязан показать это иначе, чем «накладок нет»)."""
    schedules, building = merged_schedules(db)
    joint = _joint_ids(db)
    try:
        week, pair_no = int(week), int(pair_no)
    except (TypeError, ValueError):
        return {"building": building, "room": [], "teacher": []}

    room_n, teacher_n, subject_n = _norm(room), _norm(teacher), _norm(subject)
    room_hits, teacher_hits = [], []
    for g, sched in schedules.items():
        if g == editing_group:
            continue                          #сам с собой не конфликтует
        for w, d, pn, lesson in _iter_slots(sched):
            if w != week or d != day or pn != pair_no:
                continue
            o_room, o_teacher = _norm(lesson.get("room")), _norm(lesson.get("teacher"))
            o_subject = _norm(lesson.get("subject"))
            same_lesson = (o_subject == subject_n)
            info = {"group": g, "subject": lesson.get("subject") or "",
                    "teacher": lesson.get("teacher") or "", "room": lesson.get("room") or ""}
            #Аудитория занята другим занятием: тот же кабинет, но пара не та же.
            if room_n and o_room == room_n and not (same_lesson and o_teacher == teacher_n):
                if joint_mark_id("room", week, day, pair_no, room) not in joint:
                    room_hits.append(info)
            #Преподаватель ведёт в это же время другое занятие.
            if teacher_n and o_teacher == teacher_n and not (same_lesson and o_room == room_n):
                if joint_mark_id("teacher", week, day, pair_no, teacher) not in joint:
                    teacher_hits.append(info)
    return {"building": building, "room": room_hits, "teacher": teacher_hits}
