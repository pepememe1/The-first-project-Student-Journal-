"""
test_schedule_pkg_server_safe.py — пакет schedule импортируется на СЕРВЕРЕ.

Регрессия, которую тест ловит: сервер переиспользует парсер расписания
(`from schedule import parser`), но store.py/overrides.py — десктопные (тянут data_store,
core.DBManager, sync_runner, файловый логгер `log`). Когда store реэкспортировался из
schedule/__init__.py напрямую, `import log` падал на сервере, и снимок расписания для
сайта не собирался ВООБЩЕ — преподаватель видел вечное «строится…».

Проверяем суть напрямую: импорт пакета НЕ должен подтягивать store (в нём десктопные
зависимости), а store-функции обязаны оставаться доступны десктопу через ленивую выдачу.
"""
import importlib
import sys

import pytest


def _fresh_import_schedule():
    """Импортирует schedule заново, вернув модуль. store из кэша убираем, чтобы точно
    увидеть, подтянет ли его загрузка пакета."""
    for m in list(sys.modules):
        if m == "schedule" or m.startswith("schedule."):
            sys.modules.pop(m, None)
    return importlib.import_module("schedule")


def test_importing_package_does_not_load_store():
    """Ключевое: `import schedule` (то, что делает сервер ради parser) НЕ грузит store.
    Именно store тянет десктопный `log` и валил сборку расписания на сервере."""
    _fresh_import_schedule()
    from schedule import parser  # noqa: F401  — то, что реально нужно серверу
    assert "schedule.store" not in sys.modules, \
        "пакет НЕ должен импортировать store при загрузке — на сервере это роняло сборку"


def test_store_functions_still_reachable_on_desktop():
    """Десктоп: ленивый реэкспорт не должен спрятать store-функции."""
    sched = _fresh_import_schedule()
    for name in ("group_schedule", "subjects_for_group", "current_week_parity",
                 "week_label", "load_cached", "save"):
        assert hasattr(sched, name), f"schedule.{name} должен быть доступен на десктопе"
    #обращение к ним ТЕПЕРЬ подтянет store (ленивая загрузка) — это ожидаемо
    assert "schedule.store" in sys.modules


def test_unknown_attribute_raises():
    """Опечатка в имени даёт честный AttributeError, а не тихо тянет store."""
    sched = _fresh_import_schedule()
    with pytest.raises(AttributeError):
        sched.nonexistent_function_xyz
