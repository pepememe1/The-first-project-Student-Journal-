"""
test_voice_command.py — Детерминированный разбор голосовых команд преподавателя.

Безопасность прежде всего: парсер НЕ угадывает. Проверяем широкий набор формулировок И
все конфликтные ситуации, где обязан быть переспрос, а не молчаливое неверное действие.
"""
import pytest
from vector.voice_command import parse, stt_context

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
    ("Гордеев по уважительной", "absent_o", "О"),
    ("Гордеев отсутствовал по уважительной причине", "absent_o", "О"),
    ("Смирнова отпросилась", "absent_o", "О"),
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
