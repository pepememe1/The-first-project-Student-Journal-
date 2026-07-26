"""
test_homework_grading.py — ДЗ как оцениваемый тип занятия (решение заказчика, 3.1).

Правило: домашнее задание идёт в средний балл НАРАВНЕ с практикой, попадает в долги при
«2»/«Н», но НЕ считается пропуском занятия. Последнее — не мелочь: «Н» на домашней работе
значит «не сдал», а не «не был», и учёт его в посещаемости наказывал бы студента дважды.

Тесты держат оба конца: единую формулу (grading) и её потребителей — Вектор на десктопе
(vector.intents) и серверные выборки (server/tests/test_homework.py).
"""
import grading
from vector import intents


def test_homework_counts_into_average_like_practice():
    """Практика «5» и ДЗ «3» дают средний 4.0 — ДЗ полноправно участвует в расчёте."""
    items = [("l1", "Практика"), ("l2", "ДЗ")]
    records = {"l1": "5", "l2": "3"}
    assert grading.practice_average(items, records, {}) == 4.0


def test_homework_alone_gives_average():
    """Даже если по предмету пока только ДЗ — средний считается, а не обнуляется."""
    assert grading.practice_average([("h", "ДЗ")], {"h": "4"}, {}) == 4.0


def test_homework_absence_weighs_like_practice_absence():
    """«Н» на ДЗ = «не сдал» и весит как пропуск практики (по умолчанию 2.0)."""
    items = [("h", "ДЗ")]
    assert grading.practice_average(items, {"h": "Н"}, {}) == 2.0
    #…и отключается тем же тумблером методики, что и для практики.
    assert grading.practice_average(items, {"h": "Н"}, {"avg_count_absence": False}) == 0.0


def test_is_practice_covers_only_graded_types():
    assert grading.is_practice("ДЗ") and grading.is_practice("Практика")
    assert not grading.is_practice("Лекция")
    assert not grading.is_practice("Экзамен")   #у экзамена своя ветка (avg_include_exam)


def test_homework_is_a_debt_but_not_an_absence():
    """Несданное ДЗ — долг. Но в пропуски оно не попадает: это не прогул занятия."""
    lessons = [("h", "ДЗ", 1)]
    debts = intents._is_debt(lessons, {"h": "Н"})
    assert debts and "ДЗ №1 не сдано" in debts[0], debts

    absences = intents._count_absences(lessons, {"h": "Н"})
    assert absences["всего"] == 0, f"ДЗ не должно считаться пропуском: {absences}"


def test_practice_debt_wording_unchanged():
    """Формулировка по практике не должна была поменяться из-за появления ДЗ."""
    debts = intents._is_debt([("p", "Практика", 2)], {"p": "2"})
    assert debts == ["практика №2 не сдана (2)"], debts
