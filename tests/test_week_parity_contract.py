"""Контракт чётности учебной недели: Python ↔ нативная Java-копия виджета.

Зачем это нужно. Правило «какая сейчас неделя, I или II» живёт в Python
(`server/app/schedule_web.py::current_week_parity`, зеркало в `schedule/store.py`)
и с появлением Android-виджета получило ТРЕТЬЮ реализацию — на Java
(`ScheduleWidgetData.weekParity`). Виджет обязан считать неделю сам: он рисует
расписание из кэша без единого запроса к серверу (токен живёт жёстко 5 часов, §6),
и спросить чётность ему не у кого.

Импортировать Python из Java нельзя, поэтому согласованность держит общий файл
случаев — ровно тот же приём, что уже применён к расчёту оценок
(`docs/contracts/grade-cases.json`, `tests/test_grade_contract.py`). Здесь
проверяется питоновская сторона; джавовую проверяет
`web/android/app/src/test/java/ru/esstu/gradebook/WeekParityContractTest.java`
(`cd web/android && ./gradlew testDebugUnitTest` — JVM-тест, устройство не нужно).

⚠️ Расхождение здесь не «немного другая цифра»: сдвиг на день переворачивает
чётность, и виджет показал бы РАСПИСАНИЕ ЧУЖОЙ НЕДЕЛИ — правдоподобное, но неверное.
"""
import datetime
import json
import pathlib

import pytest

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "contracts" / "week-parity-cases.json"


def _cases():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return data["cases"]


def _parity(d: datetime.date) -> int:
    """Источник правды. Импортируем лениво: серверный пакет доступен не во всех
    прогонах клиентских тестов (сервер лежит отдельным деревом)."""
    import sys
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "server"))
    from app.schedule_web import current_week_parity
    return current_week_parity(d)


def test_contract_file_exists_and_is_not_empty():
    assert CONTRACT.exists(), f"нет файла контракта: {CONTRACT}"
    cases = _cases()
    assert len(cases) >= 20, "случаев слишком мало — сдвиг на день может не проявиться"


def test_python_matches_contract():
    """Питоновская сторона обязана давать ровно то, что записано в контракте."""
    for case in _cases():
        d = datetime.date.fromisoformat(case["date"])
        assert _parity(d) == case["parity"], f"{case['date']}: чётность разошлась с контрактом"


def test_contract_covers_year_boundary():
    """1 января — самая опасная дата: там обнуляется день года, и ошибка на единицу
    в формуле проявляется именно здесь, а в середине года может и не проявиться."""
    dates = {c["date"] for c in _cases()}
    assert any(d.endswith("-01-01") for d in dates), "в контракте нет 1 января"
    assert any(d.endswith("-12-31") for d in dates), "в контракте нет 31 декабря"


def test_contract_has_two_full_consecutive_weeks():
    """Две подряд идущие недели ловят смещение на день надёжнее точечных дат: внутри
    недели чётность обязана быть постоянной, а между неделями — смениться ровно один
    раз."""
    dates = sorted(datetime.date.fromisoformat(c["date"]) for c in _cases())
    runs = []
    streak = [dates[0]]
    for prev, cur in zip(dates, dates[1:]):
        if (cur - prev).days == 1:
            streak.append(cur)
        else:
            runs.append(streak)
            streak = [cur]
    runs.append(streak)
    assert max(len(r) for r in runs) >= 14, "нет сплошного отрезка в 14 дней"


@pytest.mark.parametrize("day_shift", [1, -1])
def test_shifted_formula_would_fail(day_shift):
    """Страховка от бессмысленного теста: если бы формула была сдвинута на день,
    контракт обязан это заметить. Иначе он зелёный при любой реализации."""
    mismatches = 0
    for case in _cases():
        d = datetime.date.fromisoformat(case["date"]) + datetime.timedelta(days=day_shift)
        if _parity(d) != case["parity"]:
            mismatches += 1
    assert mismatches > 0, "сдвинутая на день формула прошла бы контракт — он бесполезен"
