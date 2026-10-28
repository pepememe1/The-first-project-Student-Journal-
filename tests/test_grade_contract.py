"""
test_grade_contract.py — Контракт fail-логики оценок (Python-сторона).

Пиннит grading.is_failed к общему golden-файлу docs/contracts/grade-cases.json. Тот же
файл проверяет JS (web/src/utils/grades.test.js) — так десктоп/сервер (Python) и веб (JS)
не разойдутся молча. Раньше правило дублировалось инлайном в трёх местах.
"""
import json
import re
from pathlib import Path

import grading

_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "docs" / "contracts" / "grade-cases.json")
    .read_text(encoding="utf-8")
)
_CASES = _CONTRACT["is_failed"]
_RETAKE = _CONTRACT["needs_retake"]
_TO_FIVE = _CONTRACT["to_five_point"]
_FAILED_SCALED = _CONTRACT["is_failed_scaled"]
_PRACTICE_AVG = _CONTRACT["practice_average"]
_GROUP_AVG = _CONTRACT["group_average"]
_MARK_AVG = _CONTRACT["mark_of_average"]


def test_mark_of_average_matches_contract():
    #Отметка по среднему — одна лесенка (28.10.2026); JS-зеркало markOfAverage сверяется с тем же файлом.
    assert [list(e) for e in grading.MARK_EDGES] == _CONTRACT["mark_edges"]
    for case in _MARK_AVG:
        got = grading.mark_of_average(case["avg"])
        assert got == case["expected"], (
            f"mark_of_average({case['_case']}) = {got}, ожидалось {case['expected']}")


def test_group_average_matches_contract():
    #Средний группы — один расчёт на продукт (20.10.2026); JS-зеркало сверяется с тем же файлом.
    for case in _GROUP_AVG:
        got = grading.group_average(case["values"])
        assert got == case["expected"], (
            f"group_average({case['_case']}) = {got}, ожидалось {case['expected']}")


def test_group_average_tie_is_not_rounded_up():
    #Обратный ход дефекта: `toFixed(2)` в журнале давал 3.63. Округление обязано быть к чётному.
    assert grading.group_average([3.5, 3.75]) == 3.62


#Формы копии «среднего средних». С 21.10.2026 не только `sum(x)/len(x)` (Полковник: копия
#`sum(r["a"] for r in rows) / len(rows)` и `statistics.mean(...)` прошли бы мимо).
_AVERAGE_COPY = re.compile(
    r"sum\(\s*(\w+)\s*\)\s*/\s*len\(\s*\1\s*\)"          #sum(x) / len(x)
    r"|sum\([^()]*\bfor\b[^()]*\)\s*/\s*len\("           #sum(... for ...) / len(...)
    r"|statistics\.f?mean\(")                             #statistics.mean / fmean


def test_average_copy_guard_catches_every_form_it_claims():
    """Обратный ход сторожа: каждая заявленная форма ловится, обычное деление — нет."""
    for bad in ("avg = sum(vals) / len(vals)",
                "g = round(sum(r['average'] for r in rows) / len(rows), 2)",
                "m = statistics.mean(averages)", "m = statistics.fmean(a)"):
        assert _AVERAGE_COPY.search(bad), bad
    for ok in ("share = missed / total", "x = grading.group_average(avgs)",
               "rate = sum(hours) / total_hours"):
        assert not _AVERAGE_COPY.search(ok), ok


def test_no_copy_of_group_average_left_on_the_server():
    """Свойство: формула «сумма средних / их число» живёт только в grading.group_average.
    Тринадцать копий были до 20.10.2026; четырнадцатая покраснит этот тест."""
    root = Path(__file__).resolve().parents[1] / "server" / "app"
    pat = _AVERAGE_COPY
    #Исключение — с причиной: средний балл ВИКТОРИНЫ это баллы теста, а не оценки журнала.
    allowed = {"routers/activities.py"}
    hits = []
    for f in root.rglob("*.py"):
        if "tests" in f.parts or f.relative_to(root).as_posix() in allowed:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                hits.append(f"{f.relative_to(root)}:{i}")
    assert not hits, hits
    assert all((root / a).is_file() for a in allowed), "мёртвая запись в исключениях"


def test_is_failed_matches_contract():
    for case in _CASES:
        got = grading.is_failed(case["grade"])
        assert got is case["expected"], (
            f"is_failed({case['grade']!r}) = {got}, ожидалось {case['expected']}")


def test_needs_retake_matches_contract():
    for case in _RETAKE:
        got = grading.needs_retake(case["records"], case["lesson_id"], case["ri"])
        assert got is case["expected"], (
            f"needs_retake({case['records']!r}, ri={case['ri']}) = {got}, "
            f"ожидалось {case['expected']}")


def test_contract_has_edge_cases():
    #Гард на то, что golden не выхолостили: должны быть и пустые, и «Не зачтено», и «Н».
    grades = {c["grade"].strip() for c in _CASES}
    assert "" in grades and "Не зачтено" in grades and "Н" in grades
    assert _RETAKE, "кейсы пересдач должны быть"


def test_to_five_point_matches_contract():
    for case in _TO_FIVE:
        got = grading.to_five_point(case["raw"], case["scale"])
        assert got == case["expected"], (
            f"to_five_point({case['raw']!r}, {case['scale']!r}) = {got}, "
            f"ожидалось {case['expected']}")


def test_is_failed_scaled_matches_contract():
    for case in _FAILED_SCALED:
        got = grading.is_failed_scaled(case["raw"], case["scale"])
        assert got is case["expected"], (
            f"is_failed_scaled({case['raw']!r}, {case['scale']!r}) = {got}, "
            f"ожидалось {case['expected']}")


def test_practice_average_matches_contract():
    #Офлайн-порт для среднего балла на телефоне (web/src/utils/grading.js::practiceAverage)
    #проверяется тем же golden-файлом — случаи сгенерированы прогоном ЭТОЙ функции, поэтому
    #тест здесь лишь пиннит контракт к самому источнику правды (страховка от опечатки в JSON).
    for case in _PRACTICE_AVG:
        items = [tuple(x) for x in case["items"]]
        got = grading.practice_average(items, case["records"], case["cfg"], case["scale"])
        assert got == case["expected"], (
            f"practice_average({case['_case']}) = {got}, ожидалось {case['expected']}")
