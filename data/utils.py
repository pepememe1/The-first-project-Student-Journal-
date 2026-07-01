"""
utils.py — Вспомогательные функции и утилиты
"""

from styles import DEFAULT_GROUPS, DEFAULT_SUBJECTS
from data_store import get_store


#ДОСТУП К ДАННЫМ ЧЕРЕЗ ХРАНИЛИЩЕ (data_store: локальный SQLite + синк с сервером)

def get_groups():
    """Список групп из хранилища или значения по умолчанию."""
    store = get_store()
    if store:
        try:
            stored = store.get_groups()
            return stored if stored else DEFAULT_GROUPS
        except Exception as e:
            print(f"[ERROR] get_groups: {e}")
    return DEFAULT_GROUPS


def get_subjects_for_group(group_name: str):
    """Предметы для группы.

    ПРИОРИТЕТ — предметы группы, спарсенные с сайта ВСГУТУ (расписание): всегда
    актуальны и не заданы «текстом» в проге. Если расписания ещё нет/нет совпадения —
    откатываемся на предметы, заданные вручную в журнале, затем на дефолт."""
    try:
        import schedule.store as sched_store
        site = sched_store.subjects_for_group(group_name)
        if site:
            return site
    except Exception as e:
        print(f"[ERROR] get_subjects_for_group (site): {e}")
    store = get_store()
    if store:
        try:
            for g in store.get_groups():
                if g.get("name") == group_name:
                    return g.get("subjects", DEFAULT_SUBJECTS)
        except Exception as e:
            print(f"[ERROR] get_subjects_for_group: {e}")
    return DEFAULT_SUBJECTS


def parse_logins():
    """База преподавателей из хранилища."""
    store = get_store()
    if store:
        try:
            t = store.get_teachers()
            if t:
                return t, ""
        except Exception as e:
            print(f"[ERROR] parse_logins: {e}")
    return {}, ""
