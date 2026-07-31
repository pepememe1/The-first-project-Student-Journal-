"""
schedule/ — парсинг и хранение расписания занятий колледжа ВСГУТУ.

Публичный API (что импортируют UI и остальной код):

    from schedule import (
        build_snapshot, load_cached, save, current_week_parity, week_label,
        get_identity, set_identity, guess_group, guess_teacher,
        Snapshot, GroupSchedule, Lesson, WEEKDAYS,
        group_schedule, subjects_for_group, subjects_all,
        CATEGORIES, DEFAULT_CATEGORY, list_category_groups,
    )

Категории (CATEGORIES) — четыре раздела расписания портала (колледж/бакалавриат/
заочное 1/заочное 2, см. докстринг parser.py). «Колледж» (DEFAULT_CATEGORY) —
единственная категория с реальным журналом/оценками, у остальных category-функции
(load_cached/save/group_schedule/…) принимают category как необязательный параметр
и по умолчанию продолжают вести себя как раньше.

Источник данных — публичный сайт portal.esstu.ru (см. parser.py). Снимок кладётся в
локальный зашифрованный кэш (store.py), на сервер не уходит.

⚠️ ВАЖНО про раздельность десктоп/сервер. model.py и parser.py — чистый stdlib+requests
и работают ВЕЗДЕ. А store.py и overrides.py — ДЕСКТОПНЫЕ: они тянут data_store,
core.DBManager, sync_runner и файловый логгер `log`, которых на сервере нет. Сервер
переиспользует ТОЛЬКО parser (`from schedule import parser` в schedule_web.py), поэтому
импорт пакета обязан НЕ грузить store.

Раньше store реэкспортировался здесь напрямую (`from .store import ...`), и `import log`
внутри store.py падал на сервере — снимок расписания для сайта не собирался вовсе
(preподаватель видел вечное «строится…»). Теперь store-функции отдаются ЛЕНИВО через
__getattr__: на сервере, где к ним не обращаются, store не импортируется никогда; на
десктопе первое обращение (`sched.group_schedule`) подгружает его штатно.
"""
from .model import Lesson, GroupSchedule, Snapshot, WEEKDAYS, DEFAULT_PAIR_TIMES
from .parser import (
    build_snapshot, parse_group_page, parse_group_page_dated, parse_cell,
    list_college_groups, list_category_groups, fetch_text,
    CATEGORIES, DEFAULT_CATEGORY,
)

#Имена, которые физически живут в store.py (десктопный модуль). Перечислены явно, чтобы
#__getattr__ не подхватывал что попало и опечатка в вызове давала честный AttributeError.
_STORE_EXPORTS = frozenset({
    "save", "load_cached", "cache_age_minutes",
    "current_week_parity", "week_label",
    "get_identity", "set_identity", "guess_group", "guess_teacher",
    "group_schedule", "subjects_for_group", "subjects_all",
})


def __getattr__(name):
    """Ленивая выдача store-функций: импорт store откладываем до ПЕРВОГО обращения.

    Так `import schedule` (и `from schedule import parser`) на сервере не тащит store с
    его десктопными зависимостями, а десктоп получает те же функции прозрачно."""
    if name in _STORE_EXPORTS:
        from . import store
        return getattr(store, name)
    raise AttributeError(f"module 'schedule' has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + list(_STORE_EXPORTS))


__all__ = [
    "Lesson", "GroupSchedule", "Snapshot", "WEEKDAYS", "DEFAULT_PAIR_TIMES",
    "build_snapshot", "parse_group_page", "parse_group_page_dated", "parse_cell",
    "list_college_groups", "list_category_groups", "fetch_text",
    "CATEGORIES", "DEFAULT_CATEGORY",
    "save", "load_cached", "cache_age_minutes",
    "current_week_parity", "week_label",
    "get_identity", "set_identity", "guess_group", "guess_teacher",
    "group_schedule", "subjects_for_group", "subjects_all",
]
