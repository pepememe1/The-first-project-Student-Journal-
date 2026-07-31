"""
test_study_hours.py — чистые функции study_hours.py, не привязанные к БД/журналу.

course_and_semester — счётчик курса/семестра группы ОТ ГОДА ПОСТУПЛЕНИЯ и ТЕКУЩЕГО
учебного термина (та же пара (year, semester), что везде в проекте — см.
webdata.current_term/data/terms.py), используется импортом учебного плана ВСГУТУ
(server/app/parsers/esstu_parser.py + POST /web/admin/groups/import-esstu).
"""
import study_hours


def test_just_enrolled_is_course_1_semester_1():
    assert study_hours.course_and_semester(2025, "2025/2026", 1) == (1, 1)


def test_first_year_spring_is_course_1_semester_2():
    assert study_hours.course_and_semester(2025, "2025/2026", 2) == (1, 2)


def test_one_year_later_autumn_is_course_2_semester_3():
    assert study_hours.course_and_semester(2024, "2025/2026", 1) == (2, 3)


def test_one_year_later_spring_is_course_2_semester_4():
    assert study_hours.course_and_semester(2024, "2025/2026", 2) == (2, 4)


def test_three_years_later_is_course_4():
    """Ровно та комбинация, что проверена вручную на реальном плане 09.02.07/2022."""
    assert study_hours.course_and_semester(2022, "2025/2026", 1) == (4, 7)


def test_term_year_takes_only_the_first_half_of_the_slash():
    """Формат термина — "YYYY/YYYY+1" (db.py::default_term) — берём год ДО слэша."""
    assert study_hours.course_and_semester(2020, "2023/2024", 2) == (4, 8)
