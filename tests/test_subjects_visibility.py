"""
test_subjects_visibility.py — Предмет с реальными занятиями виден студенту.

Регрессионный гард на баг «у студента нет предметов/оценок»: get_subjects_for_group
раньше брал предметы ТОЛЬКО из портального расписания / списка группы и игнорировал
реально существующие занятия. Предмет, заведённый преподавателем вручную (и отсутствующий
в портале), становился невидим студенту вместе с уже выставленными оценками.
"""
from data.core import GradeBook, DBManager
from data.utils import get_subjects_for_group


def test_subject_with_lessons_is_visible(fresh_db):
    #Предмет, которого нет ни в портале, ни в списке предметов группы, но есть занятия.
    GradeBook("К74/1", "Информационно-коммуник. технологии в туризме и гостеприимстве") \
        .add_lesson("Практика", "Тема", "01.09.2025")
    subs = get_subjects_for_group("К74/1")
    assert "Информационно-коммуник. технологии в туризме и гостеприимстве" in subs


def test_deleted_lesson_subject_not_forced(fresh_db):
    #Удалённое занятие (надгробие) не должно тянуть предмет в список.
    gb = GradeBook("К74/1", "Только надгробие")
    lid = gb.add_lesson("Практика", "Тема", "01.09.2025").id
    gb.delete_lesson(lid)
    assert "Только надгробие" not in DBManager.group_subjects_with_lessons("К74/1")


def test_group_subjects_with_lessons_query(fresh_db):
    GradeBook("К74/1", "Математика").add_lesson("Практика", "Т", "01.09.2025")
    GradeBook("К74/2", "Физика").add_lesson("Практика", "Т", "01.09.2025")
    assert DBManager.group_subjects_with_lessons("К74/1") == ["Математика"]
