"""
schedule/ — парсинг и хранение расписания занятий колледжа ВСГУТУ.

Публичный API (что импортируют UI и остальной код):

    from schedule import (
        build_snapshot, load_cached, save, current_week_parity, week_label,
        get_identity, set_identity, guess_group, guess_teacher,
        Snapshot, GroupSchedule, Lesson, WEEKDAYS,
    )

Источник данных — публичный сайт portal.esstu.ru (см. parser.py). Снимок кладётся в
локальный зашифрованный кэш (store.py), на сервер не уходит. Заделы под будущее
(одежда Вектора по специальности, напоминания о парах) — в specialty.py и
reminders.py; в рантайме пока НЕ подключены.
"""
from .model import Lesson, GroupSchedule, Snapshot, WEEKDAYS, DEFAULT_PAIR_TIMES
from .parser import (
    build_snapshot, parse_group_page, parse_cell, list_college_groups, fetch_text,
)
from .store import (
    save, load_cached, cache_age_minutes,
    current_week_parity, week_label,
    get_identity, set_identity, guess_group, guess_teacher,
)

__all__ = [
    "Lesson", "GroupSchedule", "Snapshot", "WEEKDAYS", "DEFAULT_PAIR_TIMES",
    "build_snapshot", "parse_group_page", "parse_cell", "list_college_groups",
    "fetch_text",
    "save", "load_cached", "cache_age_minutes",
    "current_week_parity", "week_label",
    "get_identity", "set_identity", "guess_group", "guess_teacher",
]
