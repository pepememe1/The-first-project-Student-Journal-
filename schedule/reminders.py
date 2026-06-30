"""
schedule/reminders.py — ЗАДЕЛ НА БУДУЩЕЕ: «сейчас/скоро пара, поторопись».

⚠️ ВНИМАНИЕ: заготовка под будущую фичу, в рантайме ПОКА НЕ ВЫЗЫВАЕТСЯ. Здесь только
чистые функции над моделью расписания (без UI, таймеров и обращения к Вектору) —
их легко покрыть тестами и потом подключить.

Задумка: Вектор смотрит расписание пользователя и за ~5–10 минут до начала пары
напоминает «скоро пара по такому-то предмету в такой-то аудитории, поторопись», а во
время пары показывает, что идёт сейчас.

Как подключать потом (план):
  • в main_window завести QTimer (раз в минуту);
  • на тике взять снимок (schedule.load_cached), определить сущность пользователя
    (schedule.get_identity), собрать пары на сегодня (lessons_for_today) и неделю
    (schedule.current_week_parity);
  • вызвать upcoming_reminder(...) — если вернулась подсказка, отдать её Вектору
    (vector.engine / push-сообщение виджета). Чтобы не спамить, помнить последнюю
    показанную пару (см. поле reminder_key в результате).

Время сравниваем как datetime.time, поэтому функции детерминированы и тестируемы:
передаём now явно, на «настенные часы» внутри не завязываемся.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime

#Короткие имена дней недели в порядке Пн..Вс → индекс weekday() (Пн=0).
_WEEKDAY_BY_INDEX = ["Пнд", "Втр", "Срд", "Чтв", "Птн", "Сбт", "Вск"]

#За сколько минут до пары начинаем напоминать (нижняя и верхняя граница окна).
DEFAULT_LEAD_MIN = (5, 10)


def weekday_code(d: datetime) -> str:
    """Короткий код дня недели для даты ('Пнд'.. 'Сбт'; 'Вск' — выходной)."""
    return _WEEKDAY_BY_INDEX[d.weekday()]


def _parse_time_range(time_str: str) -> tuple[dtime, dtime] | None:
    """Разбирает «09:00-10:35» в (начало, конец). None — если формат неожиданный."""
    try:
        start_s, end_s = time_str.replace(" ", "").split("-", 1)
        sh, sm = (int(x) for x in start_s.split(":"))
        eh, em = (int(x) for x in end_s.split(":"))
        return dtime(sh, sm), dtime(eh, em)
    except Exception:
        return None


@dataclass
class ReminderInfo:
    """Результат проверки расписания на «сейчас» момент времени.

    current — пара, идущая прямо сейчас (или None). upcoming — ближайшая будущая пара
    сегодня (или None). minutes_to_upcoming — сколько до её начала. hurry — True, если
    до начала ближайшей пары попали в окно DEFAULT_LEAD_MIN (пора поторопиться).
    reminder_key — стабильный ключ показанной пары (чтобы не напоминать дважды).
    """
    current: object = None
    upcoming: object = None
    minutes_to_upcoming: int | None = None
    hurry: bool = False
    reminder_key: str = ""


def current_and_next(lessons_today: list, now: datetime,
                     lead_min: tuple[int, int] = DEFAULT_LEAD_MIN) -> ReminderInfo:
    """По списку пар на сегодня и текущему времени возвращает ReminderInfo.

    lessons_today — список Lesson (model.Lesson) на сегодняшний день. Пары без
    распознанного времени пропускаются. ⚠️ ЗАДЕЛ: в рантайме пока не вызывается.
    """
    now_t = now.time()
    current = None
    upcoming = None
    minutes_to = None

    #идём по парам по возрастанию времени начала
    timed = []
    for ls in lessons_today:
        rng = _parse_time_range(getattr(ls, "time", "") or "")
        if rng:
            timed.append((rng[0], rng[1], ls))
    timed.sort(key=lambda t: (t[0].hour, t[0].minute))

    for start, end, ls in timed:
        if start <= now_t <= end:
            current = ls
        elif start > now_t and upcoming is None:
            upcoming = ls
            #минуты до начала ближайшей пары
            delta = (start.hour * 60 + start.minute) - (now_t.hour * 60 + now_t.minute)
            minutes_to = max(0, delta)

    lo, hi = lead_min
    hurry = (upcoming is not None and minutes_to is not None and lo <= minutes_to <= hi)

    key = ""
    if upcoming is not None:
        key = f"{getattr(upcoming, 'pair_no', '')}-{getattr(upcoming, 'time', '')}"

    return ReminderInfo(current=current, upcoming=upcoming,
                        minutes_to_upcoming=minutes_to, hurry=hurry,
                        reminder_key=key)


def lessons_for_today(snapshot, kind: str, entity: str, now: datetime) -> list:
    """Достаёт из снимка список пар сущности на СЕГОДНЯ (по дню недели и чётности).

    kind: 'group' | 'teacher'. entity — имя группы или ФИО преподавателя.
    ⚠️ ЗАДЕЛ: в рантайме пока не вызывается. Импорт store — лениво, чтобы модуль был
    самодостаточным заделом.
    """
    from .store import current_week_parity
    week = current_week_parity(now.date())
    day = weekday_code(now)
    if snapshot is None or not entity:
        return []
    if kind == "teacher":
        weeks = snapshot.teacher_index.get(entity, {})
        return [e["lesson"] for e in weeks.get(week, {}).get(day, [])]
    gs = snapshot.groups.get(entity)
    if not gs:
        return []
    return list(gs.weeks.get(week, {}).get(day, []))


def upcoming_reminder(snapshot, kind: str, entity: str, now: datetime,
                      lead_min: tuple[int, int] = DEFAULT_LEAD_MIN) -> ReminderInfo:
    """Удобная обёртка: собрать пары на сегодня и вернуть ReminderInfo.

    ⚠️ ЗАДЕЛ: точка, которую в будущем дёргает таймер Вектора.
    """
    today = lessons_for_today(snapshot, kind, entity, now)
    return current_and_next(today, now, lead_min)
