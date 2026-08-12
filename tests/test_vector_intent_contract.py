"""
test_vector_intent_contract.py — контракт разбора вопроса к «Вектору»: Python ↔ JS.

Зачем это нужно. Классификатор вопроса живёт в `vector_nlu.py` (корень репозитория,
чистый stdlib — используется и сервером, и десктопом). Мобильное приложение должно
понимать вопрос БЕЗ ИНТЕРНЕТА, поэтому появился JS-порт `web/src/utils/vectorNlu.js`
(тот же алгоритм, переписанный вручную). Порт обязан отвечать ТОЧНО так же, как
оригинал — иначе на сайте и внутри приложения окажутся два разных «Вектора».

Импортировать Python из JS нельзя, поэтому согласованность держит общий файл случаев
— ровно тот же приём, что уже применён к чётности учебной недели
(`docs/contracts/week-parity-cases.json`, `tests/test_week_parity_contract.py`) и к
fail-логике оценок (`docs/contracts/grade-cases.json`, `tests/test_grade_contract.py`).

Здесь проверяется питоновская сторона (сам `vector_nlu.classify`, референс, из
которого контракт и сгенерирован — см. `tools/gen_vector_contract.py`). Джавовую
сторону проверяет `web/tests/vectorNlu.contract.test.mjs`
(`cd web && npx node --test tests/vectorNlu.contract.test.mjs`).

Перегенерировать контракт: `python tools/gen_vector_contract.py`.
"""
import json
from pathlib import Path

import pytest

import vector_nlu

_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "contracts" / "vector-intent-cases.json"
)


def _cases():
    data = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    return data["cases"]


def test_contract_file_exists_and_is_not_empty():
    assert _CONTRACT_PATH.exists(), f"нет файла контракта: {_CONTRACT_PATH}"
    cases = _cases()
    assert len(cases) >= 60, "случаев слишком мало для устойчивого контракта"


def test_contract_covers_every_intent_of_the_lexicon():
    """Каждый интент лексикона обязан набираться хотя бы одной формулировкой в
    контракте — недостижимый интент выглядел бы как рабочая фича (тот же приём, что
    test_vector_matrix.py::test_every_intent_in_lexicon_is_reachable)."""
    covered = {c["intent"] for c in _cases()}
    missing = set(vector_nlu.INTENT_STEMS) - covered
    assert not missing, f"интенты без единого случая в контракте: {sorted(missing)}"


def test_contract_has_unknown_cases():
    """Явно непонятные фразы — часть контракта, не только удачные попадания."""
    unknown = [c for c in _cases() if c["intent"] == "unknown"]
    assert len(unknown) >= 10, "заведомо непонятных формулировок должно быть не меньше десятка"


def test_python_matches_contract():
    """Питоновская сторона обязана давать РОВНО то, что записано в контракте, по всем
    четырём полям — не только intent."""
    for case in _cases():
        got = vector_nlu.classify(case["q"], case["surnames"], case["subjects"])
        for field in ("intent", "surname", "subject", "day"):
            assert got[field] == case[field], (
                f"«{case['q']}»: поле {field} = {got[field]!r}, "
                f"ожидалось {case[field]!r} (контракт устарел? см. tools/gen_vector_contract.py)")


@pytest.fixture
def restore_intent_stems():
    """Возвращает нетронутую копию словаря основ ПОСЛЕ теста — тест ниже портит
    лексикон намеренно, порча не должна пережить сам тест."""
    original = {k: list(v) for k, v in vector_nlu.INTENT_STEMS.items()}
    yield
    vector_nlu.INTENT_STEMS.clear()
    vector_nlu.INTENT_STEMS.update(original)


def test_a_broken_lexicon_would_fail_the_contract(restore_intent_stems):
    """🔑 ОБРАТНЫЙ ТЕСТ — страховка от бессмысленного сторожа (тот же приём, что
    test_week_parity_contract.py::test_shifted_formula_would_fail). Если бы лексикон
    был испорчен, сравнение с контрактом ОБЯЗАНО заметить расхождение — иначе тест
    выше зелёный при любой реализации и ничего не проверяет.

    Ломаем НАСТОЯЩИЙ `vector_nlu.INTENT_STEMS` (а не копию/заглушку) — так же, как
    ломали бы код при реальном регрессе, а не эмулируем поломку сбоку."""
    vector_nlu.INTENT_STEMS["hello"] = []  # «привет»/«здравствуйте» больше не распознаются
    vector_nlu.INTENT_STEMS["homework"] = []  # «что задали» — тоже

    mismatches = 0
    for case in _cases():
        got = vector_nlu.classify(case["q"], case["surnames"], case["subjects"])
        if got["intent"] != case["intent"]:
            mismatches += 1
    assert mismatches > 0, "испорченный лексикон прошёл бы контракт — сторож бесполезен"
