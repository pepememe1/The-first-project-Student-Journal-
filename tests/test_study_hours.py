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


# ── ЧАСЫ, ПРИХОДЯЩИЕСЯ НА СТРОКУ ЗАНЯТИЯ (row_hours_map) ──────────────────────────
# Посещаемость отмечается ПО СТРОКЕ таблицы, а часы считались только парами. Из-за
# этого `webdata.absences` вела свой, ВТОРОЙ счёт «часов» — просто по строкам, без
# перевода, — и правило §4.15 «учебные часы только через study_hours» нарушалось молча.


class _L:
    def __init__(self, lid, ltype, number=1, subject="Мат", subgroup=0):
        self.id, self.type, self.number, self.subject = lid, ltype, number, subject
        #Раздельное обучение: у пары есть ещё и подгруппа, и без неё «Практика №1»
        #двух подгрупп схлопывается в одну пару (дефект, найденный Полковником).
        self.subgroup = subgroup


def test_a_practice_row_is_a_whole_pair():
    """Практика лежит одной строкой — значит эта строка и есть вся пара, 2 часа."""
    m = study_hours.row_hours_map([_L("P1", "Практика")])
    assert m["P1"] == 2


def test_a_lecture_split_in_two_rows_shares_the_pair():
    """Старая (десктопная) раскладка: лекция ДВУМЯ строками — по часу на строку."""
    m = study_hours.row_hours_map([_L("L1", "Лекция"), _L("L2", "Лекция")])
    assert m["L1"] == m["L2"] == 1


def test_a_lecture_in_a_single_row_is_a_whole_pair():
    """🔥 ЖИВОЙ ПУТЬ. `POST /web/teacher/lesson` кладёт лекцию ОДНОЙ строкой, и она
    стоит целую пару. Формула «строка лекции = 1 час» (так считала `absences` и так
    говорили комментарии по проекту) занижала бы такую лекцию ровно вдвое.

    Обратный ход: захардкодить лекции 1 час на строку — тест краснеет."""
    assert study_hours.row_hours_map([_L("L1", "Лекция")])["L1"] == 2


def test_rows_that_do_not_bear_hours_are_absent_from_the_map():
    """ДЗ вне аудитории, экзамен в учебные часы не идёт — строки в карте нет вовсе,
    и вызывающему не нужно повторять это правило у себя."""
    m = study_hours.row_hours_map([_L("H1", "ДЗ"), _L("E1", "Экзамен")])
    assert m == {}


def test_same_lesson_number_in_different_subjects_is_not_one_pair():
    """🔥 Ключ пары — (предмет, тип, номер). Сюда приходят занятия студента по ВСЕМ
    предметам сразу, и «Лекция №1» по математике не имеет отношения к «Лекции №1» по
    физике. Схлопнув их, мы отдали бы каждой по часу вместо двух.

    Обратный ход: убрать предмет из ключа — тест краснеет."""
    m = study_hours.row_hours_map([_L("L1", "Лекция", subject="Мат"),
                                   _L("L2", "Лекция", subject="Физика")])
    assert m["L1"] == m["L2"] == 2


def test_row_hours_and_hours_done_agree_within_one_subject():
    """🔥 СВОЙСТВО: на занятиях ОДНОГО предмета и одной подгруппы две формулы модуля
    обязаны дать одно и то же — и на старой раскладке (лекция двумя строками), и на
    живой (одной).

    ⚠️ Граница «одного предмета» здесь не для удобства (поймано Полковником 31.08.2026).
    `hours_done` ключует пары БЕЗ предмета, потому что её зовут по одному предмету —
    значит на списке из нескольких предметов она схлопывает «Лекцию №1» математики и
    физики в одну пару и честно занижает результат. Это не дефект `hours_done`, а её
    область применения; закреплено обратным тестом ниже, чтобы следующий читатель не
    решил, будто формулы взаимозаменяемы."""
    for lessons in (
        [_L("L1", "Лекция"), _L("L2", "Лекция"), _L("P1", "Практика", number=2)],
        [_L("L1", "Лекция"), _L("P1", "Практика", number=2)],
        [_L("L1", "Лекция"), _L("H1", "ДЗ", number=3), _L("E1", "Экзамен", number=4)],
    ):
        assert sum(study_hours.row_hours_map(lessons).values()) == study_hours.hours_done(lessons)


def test_hours_done_is_not_a_multi_subject_formula():
    """Обратная сторона предыдущего: на ДВУХ предметах формулы расходятся, и это норма.

    `row_hours_map` даёт 4 часа (две разные пары), `hours_done` — 2 (одна, предмет в её
    ключе не участвует). Тест стоит здесь затем, чтобы расхождение было НАЗВАНО: пока
    его не было, докстринг `attendance_hours` обещал «Y у обеих один и тот же», и по
    этому обещанию можно было посчитать часы студента по всем предметам через
    `hours_done` — то есть занизить их вдвое и больше."""
    lessons = [_L("A", "Лекция", subject="Математика"), _L("B", "Лекция", subject="Физика")]
    assert sum(study_hours.row_hours_map(lessons).values()) == 4.0
    assert study_hours.hours_done(lessons) == 2


def test_a_pair_costs_two_hours_in_every_subgroup():
    """🔥 РАЗДЕЛЬНОЕ ОБУЧЕНИЕ (найдено Полковником 31.08.2026).

    Нумерация занятий ведётся ОТДЕЛЬНО в пределах подгруппы
    (`webdata.next_lesson_number` фильтрует по `Lesson.subgroup`), поэтому «Практика №1»
    у предмета существует ДВАЖДЫ — своя у каждой подгруппы. Пока подгруппы не было в
    ключе пары, обе строки схлопывались в одну «пару», и её два часа делились между
    ними: пропущенная практика стоила 1 час вместо двух — ровно тот дефект, который этот
    заход объявил починенным.

    Обратный ход: убрать `subgroup` из ключа `row_hours_map` — тест краснеет (1.0)."""
    m = study_hours.row_hours_map([_L("A", "Практика", subgroup=1),
                                   _L("B", "Практика", subgroup=2)])
    assert m == {"A": 2.0, "B": 2.0}, m

    #Лекция двумя строками В КАЖДОЙ подгруппе: по 1 часу на строку, а не по 0.5.
    lec = study_hours.row_hours_map([
        _L("A", "Лекция", subgroup=1), _L("B", "Лекция", subgroup=1),
        _L("C", "Лекция", subgroup=2), _L("D", "Лекция", subgroup=2)])
    assert set(lec.values()) == {1.0}, lec


def test_pairs_of_different_subjects_never_merge():
    """Ключ содержит и ПРЕДМЕТ: «Лекция №1» по математике и по физике — разные пары."""
    m = study_hours.row_hours_map([_L("A", "Лекция", subject="Математика"),
                                   _L("B", "Лекция", subject="Физика")])
    assert m == {"A": 2.0, "B": 2.0}, m
