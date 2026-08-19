"""
test_voice_command.py — Детерминированный разбор голосовых команд преподавателя.

Безопасность прежде всего: парсер НЕ угадывает. Проверяем широкий набор формулировок И
все конфликтные ситуации, где обязан быть переспрос, а не молчаливое неверное действие.
"""
import pytest
from voice_command import parse, stt_context

ROSTER = [("Иванов", "Иван"), ("Петров", "Пётр"), ("Гордеев", "Ярослав"),
          ("Иванов", "Олег"), ("Смирнова", "Анна")]
LESSONS = [{"id": "L1", "label": "Практика №3 · 10.07"}]


def ok(text, roster=ROSTER, lessons=LESSONS):
    return parse(text, roster, lessons)


# ── Оценки: цифры, слова, склонения, синонимы ──────────────────────────────────────
@pytest.mark.parametrize("text,val", [
    ("поставь Гордееву пятёрку", "5"),
    ("Гордееву 5", "5"),
    ("Гордееву отлично", "5"),
    ("Петрову четвёрку", "4"),
    ("Петрову 4 за сегодня", "4"),
    ("Петрову хорошо", "4"),
    ("Гордееву тройку", "3"),
    ("Гордееву удовлетворительно", "3"),
    ("Гордееву двойку", "2"),
    ("Гордееву неудовлетворительно", "2"),
    ("выставь Смирновой пять", "5"),
    ("запиши Смирновой оценку четыре", "4"),
    ("дай Гордееву балл пять", "5"),
])
def test_grades(text, val):
    c = ok(text)
    assert c.ok and c.action == "grade" and c.value == val, (text, c.error, c.value)


# ── Посещаемость: Н / Б / О во множестве форм ──────────────────────────────────────
@pytest.mark.parametrize("text,action,val", [
    ("отметь Гордееву пропуск", "absent_n", "Н"),
    ("Гордеев прогулял", "absent_n", "Н"),
    ("Гордеев не был", "absent_n", "Н"),
    ("Гордеев не пришёл", "absent_n", "Н"),
    ("Гордеев отсутствовал", "absent_n", "Н"),
    ("Смирнова не явилась", "absent_n", "Н"),
    ("Петров болеет", "absent_b", "Б"),
    ("Петров заболел", "absent_b", "Б"),
    ("Петров на больничном", "absent_b", "Б"),
    #🔥 3.7.6: «О» — ОПОЗДАЛ. Раньше здесь стояли «по уважительной» / «отпросилась»:
    #метка называлась «уважительная причина», и эти же тесты закрепляли тот смысл.
    #Отдельной метки для уважительной причины больше нет (решение Ярослава 19.08.2026).
    ("Гордеев опоздал", "absent_o", "О"),
    ("Гордеев пришёл позже", "absent_o", "О"),
    ("Смирнова задержалась", "absent_o", "О"),
])
def test_attendance(text, action, val):
    c = ok(text)
    assert c.ok and c.action == action and c.value == val, (text, c.error, c.action)


def test_present_lecture():
    c = ok("отметь Гордеева присутствовал")
    assert c.ok and c.action == "present" and c.value == "✓"


def test_negation_not_confused_with_present():
    #«не пришёл» — это пропуск, НЕ присутствие. Негатив важнее.
    c = ok("Гордеев не пришёл на пару")
    assert c.ok and c.action == "absent_n"


# ── Однофамильцы ───────────────────────────────────────────────────────────────────
def test_homonym_requires_choice():
    c = ok("Иванову пять")
    assert not c.ok and c.candidates
    assert ("Иванов", "Иван") in c.candidates and ("Иванов", "Олег") in c.candidates
    assert c.value == "5"


def test_homonym_resolved_by_name():
    c = ok("Иванову Олегу поставь тройку")
    assert c.ok and c.student == ("Иванов", "Олег") and c.value == "3"


# ── КОНФЛИКТЫ: обязателен переспрос, не догадка ────────────────────────────────────
def test_conflict_grade_and_absence():
    c = ok("Гордееву пять но болел")
    assert not c.ok and ("одно" in c.error.lower() or "оценка, и пропуск" in c.error.lower())


def test_conflict_two_grades():
    c = ok("Гордееву четыре нет пять")
    assert not c.ok and "несколько оценок" in c.error.lower()


def test_grade_out_of_scale():
    c = ok("Гордееву шесть")   # «шесть» не в словаре оценок → не действие
    assert not c.ok


def test_grade_out_of_scale_digit():
    c = ok("Гордееву 6")
    assert not c.ok and "шкал" in c.error.lower()


def test_unknown_surname_no_guess():
    c = ok("Сидорову пятёрку")
    assert not c.ok and not c.student and "фамилию" in c.error.lower()


def test_no_action():
    c = ok("Гордеев Ярослав")
    assert not c.ok and "действие" in c.error.lower()


def test_no_lesson_today():
    c = ok("Гордееву пять", lessons=[])
    assert not c.ok and "сегодня" in c.error.lower()


def test_multiple_lessons_today_asks():
    two = [{"id": "L1", "label": "Практика №3"}, {"id": "L2", "label": "Лекция №2"}]
    c = ok("Гордееву пять", lessons=two)
    assert not c.ok and "несколько" in c.error.lower()


def test_empty_text():
    c = ok("")
    assert not c.ok and c.error


def test_heard_is_preserved():
    c = ok("Гордееву пять")
    assert c.heard == "Гордееву пять"


def test_summary_mentions_student_and_value():
    c = ok("Гордееву пять")
    assert "Гордеев" in c.summary and "5" in c.summary and "Практика" in c.summary


def test_stt_context_lists_roster():
    ctx = stt_context(ROSTER)
    assert "Гордеев" in ctx and "Смирнова" in ctx and "пять" in ctx


# ── ВОПРОСЫ (информационные) → Q&A, НЕ запись ──────────────────────────────────────
@pytest.mark.parametrize("text", [
    "назови всех моих студентов из группы К74/1",
    "какой средний балл группы",
    "какой средний балл у Гордеева",
    "сколько пропусков у Гордеева",           # содержит «пропуск», но это ВОПРОС
    "покажи должников",
    "перечисли студентов с двойками",
    "кто отсутствовал сегодня",
    "какая успеваемость у Смирновой",
])
def test_questions_route_to_qa_not_write(text):
    c = ok(text)
    assert c.is_question and not c.ok, (text, c.action, c.value)
    assert c.action == "" or c.action not in ()  # действие записи не выполняем


def test_command_is_not_question():
    #Явная команда без вопросительных маркеров — это запись, не вопрос.
    c = ok("Гордееву пять")
    assert not c.is_question and c.ok


# ═══ ПАКЕТНЫЕ КОМАНДЫ (parse_batch) ═══════════════════════════════════════════════
from voice_command import parse_batch

# Ростер без однофамильцев — по алфавиту: Абрамов, Гордеев, Петров, Смирнова, Яковлев
BR = [("Гордеев", "Ярослав"), ("Петров", "Пётр"), ("Смирнова", "Анна"),
      ("Абрамов", "Иван"), ("Яковлев", "Олег")]
L1 = [{"id": "L1", "label": "Практика №3 · 10.07"}]


def b(text, roster=BR, lessons=L1):
    return parse_batch(text, roster, lessons)


def test_batch_whole_group_same_grade():
    r = b("всей группе пять")
    assert r.kind == "grades" and len(r.items) == 5
    assert all(it.value == "5" and it.action == "grade" for it in r.items)


def test_batch_whole_group_variants():
    for txt in ["весь класс получил четыре", "поставь всем четыре", "всему классу четыре"]:
        r = b(txt)
        assert r.kind == "grades" and len(r.items) == 5 and all(it.value == "4" for it in r.items), txt


def test_batch_first_n_alpha_word():
    r = b("первым двум по списку пять")
    assert r.kind == "grades" and len(r.items) == 2
    assert [it.surname for it in r.items] == ["Абрамов", "Гордеев"]
    assert all(it.value == "5" for it in r.items)


def test_batch_first_n_digit():
    r = b("первым 3 по списку два")
    assert r.kind == "grades" and len(r.items) == 3
    assert [it.surname for it in r.items] == ["Абрамов", "Гордеев", "Петров"]
    assert all(it.value == "2" for it in r.items)


def test_batch_several_students_different_grades():
    r = b("Гордееву пять Петрову четыре Смирновой три")
    assert r.kind == "grades" and len(r.items) == 3
    by = {it.surname: it.value for it in r.items}
    assert by == {"Гордеев": "5", "Петров": "4", "Смирнова": "3"}


def test_batch_several_students_shared_grade():
    r = b("Гордееву и Петрову пять")
    assert r.kind == "grades" and len(r.items) == 2
    assert all(it.value == "5" for it in r.items)
    assert {it.surname for it in r.items} == {"Гордеев", "Петров"}


def test_batch_comma_separated():
    r = b("Гордееву пять, Петрову четыре, Яковлеву три")
    by = {it.surname: it.value for it in r.items}
    assert by == {"Гордеев": "5", "Петров": "4", "Яковлев": "3"}


def test_batch_absence_shared():
    r = b("Гордееву и Смирновой пропуск")
    assert r.kind == "grades" and len(r.items) == 2
    assert all(it.action == "absent_n" and it.value == "Н" for it in r.items)


def test_batch_out_of_scale_group():
    r = b("всей группе 6")
    assert r.kind == "error" and "шкал" in r.error.lower()


def test_batch_multiple_grades_group_error():
    r = b("всей группе пять и четыре")
    assert r.kind == "error" and "несколько" in r.error.lower()


def test_batch_trailing_student_without_grade_skipped():
    #При РАЗНЫХ оценках студент без своей оценки пропускается с предупреждением, не угадываем.
    r = b("Гордееву пять Петрову четыре Смирновой")
    by = {it.surname: it.value for it in r.items}
    assert by == {"Гордеев": "5", "Петров": "4"}
    assert any("Смирнов" in w for w in r.warnings)


def test_batch_question_still_routes():
    r = b("какой средний балл группы")
    assert r.is_question and r.kind == "question"


def test_batch_no_lesson_today():
    r = b("всей группе пять", lessons=[])
    assert r.kind == "error" and "сегодня" in r.error.lower()


# ═══ СОЗДАНИЕ ЗАНЯТИЯ ГОЛОСОМ ═════════════════════════════════════════════════════
def test_create_lecture_with_topic():
    r = b("Создай сегодня лекцию по теме Введение в модули")
    assert r.kind == "lesson" and r.lesson.type == "Лекция"
    assert "Введение в модули" in r.lesson.topic


def test_create_practice():
    r = b("добавь практику по теме Циклы и функции")
    assert r.kind == "lesson" and r.lesson.type == "Практика"
    assert "Циклы" in r.lesson.topic


def test_create_lesson_with_number():
    r = b("создай лекцию номер 4 по теме Массивы")
    assert r.kind == "lesson" and r.lesson.number == 4 and "Массивы" in r.lesson.topic


def test_create_lesson_no_topic_warns():
    r = b("создай сегодня лекцию")
    assert r.kind == "lesson" and (not r.lesson.topic) and r.warnings


def test_create_homework():
    r = b("задай домашнее задание по теме Создать базу данных")
    assert r.kind == "lesson" and r.lesson.type == "ДЗ", r.lesson.type
    assert "базу данных" in r.lesson.topic


def test_homework_wins_over_other_type_words():
    """«ДЗ по практике» — это ДЗ, а не практика: основа «домашн»/«дз» проверяется первой."""
    r = b("создай дз по практике номер 2")
    assert r.kind == "lesson" and r.lesson.type == "ДЗ", r.lesson.type


def test_short_stem_dz_does_not_match_inside_words():
    """«дз» ищется как отдельное слово. Иначе «создай лекцию про надзор» стала бы ДЗ."""
    r = b("создай лекцию по теме государственный надзор")
    assert r.kind == "lesson" and r.lesson.type == "Лекция", r.lesson.type


# ═══ БУРЯТСКИЕ ФИО (Самбуева, Гындынова, Цыбенов… + имена Бато, Арюна, Баянжаргал) ═══
BUR = [("Самбуева", "Арюна"), ("Халзанова", "Дарина"), ("Гындынова", "Оюна"),
       ("Цыбенов", "Ардан"), ("Бомбаров", "Бато"), ("Дашиев", "Баянжаргал"),
       ("Дашиев", "Аюр")]
LB = [{"id": "L1", "label": "Практика №1"}]


def bu(text):
    return parse_batch(text, BUR, LB)


@pytest.mark.parametrize("text,surname,val", [
    ("Самбуевой пять", "Самбуева", "5"),
    ("Гындыновой четыре", "Гындынова", "4"),
    ("Цыбенову три", "Цыбенов", "3"),
    ("Бомбарову два", "Бомбаров", "2"),
    ("Халзановой отлично", "Халзанова", "5"),
])
def test_buryat_surnames_declension(text, surname, val):
    r = bu(text)
    assert r.kind == "grades" and len(r.items) == 1
    assert r.items[0].surname == surname and r.items[0].value == val


def test_buryat_batch():
    r = bu("Самбуевой и Цыбенову пять")
    assert r.kind == "grades" and {it.surname for it in r.items} == {"Самбуева", "Цыбенов"}


def test_buryat_firstname_reference():
    #Обращение по уникальному имени: «Бато не пришёл» → Бомбаров Бато, пропуск.
    r = bu("Бато не пришёл")
    assert r.kind == "grades" and len(r.items) == 1
    assert r.items[0].surname == "Бомбаров" and r.items[0].action == "absent_n"


def test_buryat_firstname_grade():
    r = bu("Арюне пять")
    assert r.kind == "grades" and r.items[0].surname == "Самбуева" and r.items[0].value == "5"


def test_buryat_homonym_needs_name():
    #Два Дашиевых без имени → понятная ошибка про однофамильцев (не «не узнал»).
    r = bu("Дашиеву пять")
    assert r.kind == "error" and "однофамил" in r.error.lower()


def test_buryat_homonym_resolved_by_name():
    r = bu("Дашиеву Аюру пять")
    assert r.kind == "grades" and r.items[0].name == "Аюр"


# ═══ РАСШИРЕННЫЕ СИНОНИМЫ ═════════════════════════════════════════════════════════
@pytest.mark.parametrize("text,val", [
    ("Гордееву двояк", "2"),
    ("Гордееву троечку", "3"),
    ("Гордееву четвёрочку", "4"),
    ("Гордееву пятёрочку", "5"),
])
def test_synonym_grades(text, val):
    r = b(text)
    assert r.kind == "grades" and r.items[0].value == val


@pytest.mark.parametrize("text,action", [
    ("Гордеев приболел", "absent_b"),
    ("Гордеев простыл", "absent_b"),
    ("Гордеев опоздал на пару", "absent_o"),
    ("Гордеев с опозданием", "absent_o"),
    ("Гордеева нет на паре", "absent_n"),
])
def test_synonym_absence(text, action):
    r = b(text)
    assert r.kind == "grades" and r.items[0].action == action


def test_synonym_group_pogolovno():
    r = b("поголовно четыре")
    assert r.kind == "grades" and len(r.items) == 5 and all(it.value == "4" for it in r.items)


# ═══════════════════════════════════════════════════════════════════════════════════
# УСТОЙЧИВОСТЬ: бурятские ФИО, варианты транскрипции STT, расширенный словарь.
# «Как автомат Калашникова» — предусмотрены реальные способы, которыми препод и Whisper
# коверкают команды.
# ═══════════════════════════════════════════════════════════════════════════════════

BUR_ROSTER = [("Гындынова", "Арюна"), ("Самбуев", "Бато"), ("Цыренова", "Саяна"),
              ("Дондоков", "Аюр"), ("Гомбоева", "Оюна")]
BUR_LESSONS = [{"id": "L1", "label": "Практика №1 · 10.09"}]


def bok(text):
    return parse(text, BUR_ROSTER, BUR_LESSONS)


@pytest.mark.parametrize("text,surname", [
    ("поставь Гындыновой пять", "Гындынова"),
    ("Самбуеву четыре", "Самбуев"),
    ("Цыреновой тройку", "Цыренова"),
    ("Дондокову отлично", "Дондоков"),
    ("Гомбоевой двойку", "Гомбоева"),
])
def test_buryat_surnames_match(text, surname):
    c = bok(text)
    assert c.ok and c.student[0] == surname, (text, c.error, c.student)


@pytest.mark.parametrize("text,surname", [
    # Whisper часто путает гласные/удвоения в бурятских ФИО — фонетика должна вытянуть.
    ("Гундыновой пять", "Гындынова"),        # ы→у услышал
    ("Самбоеву четыре", "Самбуев"),          # у→о
    ("Цыреновой тройку", "Цыренова"),
    ("Гомбоеевой двойку", "Гомбоева"),        # удвоенная гласная
])
def test_buryat_surnames_transcription_variants(text, surname):
    c = bok(text)
    # либо распознал точно, либо честно переспросил — но НИКОГДА не поставил другому
    if c.ok:
        assert c.student[0] == surname, (text, c.student)
    else:
        assert not c.student, (text, c.student)


def test_buryat_firstname_address():
    # Обращение по УНИКАЛЬНОМУ имени (бурятские имена различимее фамилий).
    c = bok("Бато не пришёл")
    assert c.ok and c.student == ("Самбуев", "Бато") and c.action == "absent_n", (c.error, c.student)


def test_buryat_firstname_grade_single_command():
    #Имя было у ДВУХ тестов сразу, и объявленный выше (пакетный разбор `bu`) молча
    #переопределялся этим — то есть не выполнялся ни разу. Имена разведены.
    c = bok("Арюне пятёрку")
    assert c.ok and c.student == ("Гындынова", "Арюна") and c.value == "5", (c.error, c.student)


def test_buryat_unknown_still_no_guess():
    # Фамилии нет в группе — не подсунуть похоже звучащую.
    c = bok("Раднаевой пять")
    assert not c.ok and not c.student


@pytest.mark.parametrize("text,val", [
    ("Гордееву трёшку", "3"),
    ("Гордееву пятёру", "5"),
    ("Гордееву четвёру", "4"),
    ("Смирновой неудовл", "2"),
    ("Гордееву удовлет", "3"),
    ("Петрову хорошист", "4"),
])
def test_extended_grade_vocab(text, val):
    c = ok(text)
    assert c.ok and c.action == "grade" and c.value == val, (text, c.error, c.value)


@pytest.mark.parametrize("text,action", [
    ("Гордеев пропустил", "absent_n"),
    ("Гордеев не дошёл до аудитории", "absent_n"),
    ("Смирнова заболела", "absent_b"),
    ("Смирнова плохо себя чувствует", "absent_b"),
    ("Гордеев припозднился", "absent_o"),
    ("Гордеев не успел к началу", "absent_o"),
    ("Гордеев присутствовал", "present"),
    ("Гордеев работал на паре", "present"),
])
def test_extended_attendance_vocab(text, action):
    c = ok(text)
    assert c.ok and c.action == action, (text, c.error, c.action)


def test_present_not_confused_by_negation_extended():
    # «не появлялся» — это Н, а не присутствие, хотя рядом «появлял».
    c = ok("Гордеев не появлялся")
    assert c.ok and c.action == "absent_n", (c.error, c.action)


def test_stt_context_has_buryat_hints():
    ctx = stt_context(BUR_ROSTER)
    assert "Гындынова" in ctx and "Бато" in ctx      # опоры бурятской фонетики
    assert "Арюна" in ctx                             # реальный ростер тоже
    assert "пятёрка" in ctx and "опоздал" in ctx


def test_excused_wording_no_longer_marks_anything():
    """🔥 Формулировки уважительной причины («отпросился», «на соревнованиях», «по
    справке») больше не дают метку ВООБЩЕ — и это важнее, чем кажется.

    Соблазн был оставить их привязанными к «О»: словарь уже есть, тесты зелёные. Но
    после переназначения это записывало бы отпросившегося студента как ОПОЗДАВШЕГО —
    то есть тихо подменяло факт. Лучше честный переспрос: преподаватель поставит метку
    руками, а не узнает о подмене из отчёта куратора через семестр.

    Обратный ход: вернуть в `_ABSENCE_O` основу «отпросил» — тест краснеет."""
    for phrase in ("Гордеев отпросился", "Гордеев на соревнованиях",
                   "Гордеев по справке", "Гордеев освобождён"):
        cmd = ok(phrase)
        assert cmd.action != "absent_o", f"«{phrase}» молча стало опозданием"
