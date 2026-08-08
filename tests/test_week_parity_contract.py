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


def test_parity_is_stable_inside_week_and_flips_between():
    """🔥 ИНВАРИАНТ, который поймал реальный баг продукта (починен в 3.6.9).

    До правки формула брала день недели ТЕКУЩЕЙ даты вместо 1 января, и чётность
    менялась внутри одной календарной недели по два-три раза (2026-02-02 Пн → I,
    Вт-Пт → II, Сб → I, Вс → II). Контракт из 30 дат был при этом ЗЕЛЁНЫМ: он сверял
    Python с Java, а обе стороны были одинаково неправы.

    ⚠️ Учебная неделя здесь начинается с ВОСКРЕСЕНЬЯ — наследие JS-идиомы, где
    `getDay()` считает от воскресенья. Проверяем Вс..Сб, а не Пн..Вс.
    """
    start = datetime.date(2026, 2, 8)          # воскресенье
    first = _parity(start)
    for i in range(1, 7):                      # Пн..Сб той же недели
        d = start + datetime.timedelta(days=i)
        assert _parity(d) == first, f"{d}: чётность изменилась ВНУТРИ недели"
    nxt = start + datetime.timedelta(days=7)
    assert _parity(nxt) != first, "чётность обязана смениться на следующей неделе"


def test_parity_alternates_over_ten_weeks():
    """Десять недель подряд обязаны идти строго через одну. Ловит и «застрявшую»
    чётность (всегда I), и слишком частое переключение."""
    start = datetime.date(2026, 2, 8)          # воскресенье
    seq = [_parity(start + datetime.timedelta(days=7 * w)) for w in range(10)]
    for a, b in zip(seq, seq[1:]):
        assert a != b, f"чётность не чередуется: {seq}"


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
