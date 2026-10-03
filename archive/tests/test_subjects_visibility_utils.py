"""Вырезано из tests/test_subjects_visibility.py 30.09.2026 вместе с data/utils.py.

Архив, не прогон: pytest сюда не заходит (testpaths = tests). Вернуть — перенести
archive/data/utils.py обратно в data/ и эту проверку обратно в тест."""
from data.core import DBManager
from data.utils import get_subjects_for_group

TOURISM = "Информационно-коммуник. технологии в туризме и гостеприимстве"


#_add_lesson и фикстура fresh_db — в tests/test_subjects_visibility.py и tests/conftest.py


def test_subject_with_lessons_is_visible(fresh_db):
    #Предмет, которого нет ни в портале, ни в списке предметов группы, но есть занятия.
    _add_lesson("К74/1", TOURISM, "L1")
    assert TOURISM in get_subjects_for_group("К74/1")
