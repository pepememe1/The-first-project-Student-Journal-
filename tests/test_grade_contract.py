"""
test_grade_contract.py — Контракт fail-логики оценок (Python-сторона).

Пиннит grading.is_failed к общему golden-файлу docs/contracts/grade-cases.json. Тот же
файл проверяет JS (web/src/utils/grades.test.js) — так десктоп/сервер (Python) и веб (JS)
не разойдутся молча. Раньше правило дублировалось инлайном в трёх местах.
"""
import json
from pathlib import Path

import grading

_CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "docs" / "contracts" / "grade-cases.json")
    .read_text(encoding="utf-8")
)["is_failed"]


def test_is_failed_matches_contract():
    for case in _CASES:
        got = grading.is_failed(case["grade"])
        assert got is case["expected"], (
            f"is_failed({case['grade']!r}) = {got}, ожидалось {case['expected']}")


def test_contract_has_edge_cases():
    #Гард на то, что golden не выхолостили: должны быть и пустые, и «Не зачтено», и «Н».
    grades = {c["grade"].strip() for c in _CASES}
    assert "" in grades and "Не зачтено" in grades and "Н" in grades
