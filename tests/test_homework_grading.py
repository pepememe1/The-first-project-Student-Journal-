"""
test_homework_grading.py — ДЗ как оцениваемый тип занятия (решение заказчика, 3.1).

Правило: домашнее задание идёт в средний балл НАРАВНЕ с практикой, попадает в долги при
«2»/«Н», но НЕ считается пропуском занятия. Последнее — не мелочь: «Н» на домашней работе
значит «не сдал», а не «не был», и учёт его в посещаемости наказывал бы студента дважды.

⚠️ Здесь остался ОДИН конец — единая формула (`grading.py`). Прежде тесты держали ещё и
десктопного Вектора (`vector.intents._is_debt`/`_count_absences`), но пакет `vector/`
удалён: у него не осталось ни одного вызывающего в продукте (нативных экранов нет с
удаления Qt, окно показывает ту же SPA). Правило «несданное ДЗ — долг, но НЕ пропуск»
проверяется теперь на живом пути — `server/tests/test_homework.py`.
"""
import grading


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
