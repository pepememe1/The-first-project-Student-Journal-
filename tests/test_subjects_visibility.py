"""
test_subjects_visibility.py — Предмет с реальными занятиями виден студенту.

Регрессионный гард на баг «у студента нет предметов/оценок»: get_subjects_for_group
раньше брал предметы ТОЛЬКО из портального расписания / списка группы и игнорировал
реально существующие занятия. Предмет, заведённый преподавателем вручную (и отсутствующий
в портале), становился невидим студенту вместе с уже выставленными оценками.

⚠️ Переписано 31.08.2026 без `core.GradeBook` (класс мёртв в продукте и удалён тем же
заходом). Занятие заводится ПРЯМОЙ записью в таблицу — тем же способом, каким её
наполняет синхронизация, то есть ближе к живому пути, чем было. Проверяемые функции
(`get_subjects_for_group`, `DBManager.group_subjects_with_lessons`) не менялись.
"""
from data.core import DBManager
from data.utils import get_subjects_for_group

TOURISM = "Информационно-коммуник. технологии в туризме и гостеприимстве"


def _add_lesson(group: str, subject: str, lid: str, deleted: int = 0):
    """Занятие прямой записью — так же, как его кладёт `sync_engine` при pull."""
    DBManager._init_sqlite_tables()
    conn = DBManager.get_conn()
    cur = conn.cursor()
    #Колонки ровно как в схеме `DBManager._init_sqlite_tables` (у занятий нет `device` —
    #он есть у оценок; угадывать схему нельзя, надо смотреть).
    cur.execute(
        "INSERT OR REPLACE INTO lessons "
        "(id,group_name,subject,type,number,topic,date,retake_date,hour,"
        " year,semester,updated_at,deleted) "
        "VALUES (?,?,?,'Практика',1,'Тема','01.09.2025','',0,'','0',"
        "        '2026-01-01T00:00:00',?)",
        (lid, group, subject, deleted))
    conn.commit()
    conn.close()


def test_subject_with_lessons_is_visible(fresh_db):
    #Предмет, которого нет ни в портале, ни в списке предметов группы, но есть занятия.
    _add_lesson("К74/1", TOURISM, "L1")
    assert TOURISM in get_subjects_for_group("К74/1")


def test_deleted_lesson_subject_not_forced(fresh_db):
    #Удалённое занятие (надгробие) не должно тянуть предмет в список.
    _add_lesson("К74/1", "Только надгробие", "L1", deleted=1)
    assert "Только надгробие" not in DBManager.group_subjects_with_lessons("К74/1")


def test_group_subjects_with_lessons_query(fresh_db):
    _add_lesson("К74/1", "Математика", "L1")
    _add_lesson("К74/2", "Физика", "L2")
    assert DBManager.group_subjects_with_lessons("К74/1") == ["Математика"]
