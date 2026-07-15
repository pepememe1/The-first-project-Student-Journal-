"""
utils.py — Вспомогательные функции и утилиты
"""

from styles import DEFAULT_GROUPS, DEFAULT_SUBJECTS
import log
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
            log.get("utils").warning(f"[ERROR] get_groups: {e}")
    return DEFAULT_GROUPS


def get_subjects_for_group(group_name: str):
    """Предметы для группы.

    ПРИОРИТЕТ — предметы группы, спарсенные с сайта ВСГУТУ (расписание): всегда
    актуальны и не заданы «текстом» в проге. Если расписания ещё нет/нет совпадения —
    откатываемся на предметы, заданные вручную в журнале, затем на дефолт.

    ВСЕГДА добавляем предметы, по которым в группе РЕАЛЬНО есть занятия: иначе предмет,
    заведённый преподавателем вручную (и отсутствующий в портальном расписании), был бы
    невидим студенту — вместе с уже выставленными оценками (частый баг «нет предметов»)."""
    base = None
    try:
        import schedule.store as sched_store
        site = sched_store.subjects_for_group(group_name)
        if site:
            base = list(site)
    except Exception as e:
        log.get("utils").warning(f"[ERROR] get_subjects_for_group (site): {e}")
    if base is None:
        store = get_store()
        if store:
            try:
                for g in store.get_groups():
                    if g.get("name") == group_name:
                        base = list(g.get("subjects", []) or [])
                        break
            except Exception as e:
                log.get("utils").warning(f"[ERROR] get_subjects_for_group: {e}")
    if not base:
        base = list(DEFAULT_SUBJECTS)
    #Юнион с предметами, у которых есть реальные занятия в группе (сохраняем порядок base).
    try:
        from core import DBManager
        for s in DBManager.group_subjects_with_lessons(group_name):
            if s not in base:
                base.append(s)
    except Exception as e:
        log.get("utils").warning(f"[ERROR] get_subjects_for_group (lessons): {e}")
    return base or DEFAULT_SUBJECTS


def parse_logins():
    """База преподавателей из хранилища."""
    store = get_store()
    if store:
        try:
            t = store.get_teachers()
            if t:
                return t, ""
        except Exception as e:
            log.get("utils").warning(f"[ERROR] parse_logins: {e}")
    return {}, ""
