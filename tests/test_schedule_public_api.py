"""
test_schedule_public_api.py — пакет schedule отдаёт всё, что обещает.

Зачем отдельный тест. Функция может лежать в schedule/store.py, но не быть
реэкспортирована в schedule/__init__.py — и код вида `sched.group_schedule(...)`
падает AttributeError только В РАНТАЙМЕ. Так и случилось однажды: экран админа валился
прямо на входе, хотя все юнит-тесты были зелёными, потому что они импортируют функции
напрямую из модуля, а вызывающий шёл через пакет.

⚠️ ИМЯ СПИСКА ИСПРАВЛЕНО, И ЭТО НЕ КОСМЕТИКА. Он назывался `USED_BY_UI` с подписью «ровно
то, что UI зовёт как sched.<имя> (см. grep по ui/ и vector/)» — обе папки удалены вместе
с Qt, то есть список описывал вызывающих, которых больше нет, и читался как «вот живой
контракт с интерфейсом». Живых потребителей store сегодня ДВА: `subjects_for_group`
(data/utils.py) и `subjects_all` (subjects.py); всё прочее сейчас никем не зовётся.
Тест оставлен и список НЕ урезан намеренно: он охраняет ре-экспорты пакета, а сузить его
до двух имён значило бы разрешить остальным тихо отвалиться — и обнаружить это в тот
момент, когда экран расписания начнут возвращать.
"""
import pytest

import schedule as sched

#Публичная поверхность пакета: имена, которые обязаны быть доступны как sched.<имя>.
#Живые вызывающие есть у subjects_for_group / subjects_all (см. шапку); остальные —
#рабочий, покрытый тестами задел, ре-экспорт которого мы не даём сломать молча.
PUBLIC_API = [
    "build_snapshot", "load_cached", "save", "cache_age_minutes",
    "current_week_parity", "week_label",
    "get_identity", "set_identity", "guess_group", "guess_teacher",
    "group_schedule", "subjects_for_group", "subjects_all",
]

#Те, у кого вызывающий в продукте есть ПРЯМО СЕЙЧАС. Отдельным списком, чтобы разница
#между «работает у людей» и «лежит про запас» была видна в коде, а не в чьей-то памяти.
HAS_LIVE_CALLER = ["subjects_for_group", "subjects_all"]


@pytest.mark.parametrize("name", PUBLIC_API)
def test_public_api_exports(name):
    assert hasattr(sched, name), (
        f"schedule.{name} не реэкспортирован в __init__.py — вызывающий упадёт "
        f"AttributeError в рантайме")
    assert callable(getattr(sched, name))


@pytest.mark.parametrize("name", HAS_LIVE_CALLER)
def test_functions_with_live_callers_are_reachable_through_the_package(name):
    """Эти две зовут `data/utils.py` и `subjects.py` — ИМЕННО через пакет, лениво.

    Проверка узкая намеренно: сломается ре-экспорт — и список предметов молча
    откатится на встроенный дефолт вместо портального, без единой ошибки на экране."""
    assert callable(getattr(sched, name, None))


def test_all_matches_reality():
    """__all__ не должен обещать того, чего нет: он документация для читателя."""
    missing = [n for n in sched.__all__ if not hasattr(sched, n)]
    assert missing == [], f"в __all__ перечислено, но отсутствует: {missing}"
