"""
test_schedule_public_api.py — пакет schedule отдаёт всё, что зовёт UI.

Зачем отдельный тест. Функция может лежать в schedule/store.py, но не быть
реэкспортирована в schedule/__init__.py — и код вида `sched.group_schedule(...)`
падает AttributeError только В РАНТАЙМЕ. Так и случилось: админ-дашборд валился
прямо на входе, хотя все юнит-тесты были зелёными, потому что они импортируют
функции напрямую из модуля, а UI — через пакет.
"""
import pytest

import schedule as sched

#Ровно то, что UI зовёт как sched.<имя> (см. grep по ui/ и vector/).
USED_BY_UI = [
    "build_snapshot", "load_cached", "save", "cache_age_minutes",
    "current_week_parity", "week_label",
    "get_identity", "set_identity", "guess_group", "guess_teacher",
    "group_schedule", "subjects_for_group", "subjects_all",
]


@pytest.mark.parametrize("name", USED_BY_UI)
def test_public_api_exports(name):
    assert hasattr(sched, name), (
        f"schedule.{name} не реэкспортирован в __init__.py — UI упадёт "
        f"AttributeError в рантайме")
    assert callable(getattr(sched, name))


def test_all_matches_reality():
    """__all__ не должен обещать того, чего нет: он документация для читателя."""
    missing = [n for n in sched.__all__ if not hasattr(sched, n)]
    assert missing == [], f"в __all__ перечислено, но отсутствует: {missing}"
