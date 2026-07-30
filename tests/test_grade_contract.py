"""
test_grade_contract.py — Контракт fail-логики оценок (Python-сторона).

Пиннит grading.is_failed к общему golden-файлу docs/contracts/grade-cases.json. Тот же
файл проверяет JS (web/src/utils/grades.test.js) — так десктоп/сервер (Python) и веб (JS)
не разойдутся молча. Раньше правило дублировалось инлайном в трёх местах.
"""
import json
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
