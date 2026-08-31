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
from itertools import pairwise

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
    for prev, cur in pairwise(dates):
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

    ⚠️ НЕДЕЛЯ ТЕПЕРЬ НАЧИНАЕТСЯ С ПОНЕДЕЛЬНИКА (31.08.2026). Раньше здесь стояло
    воскресенье — наследие JS-идиомы «номер недели года», где `getDay()` считает от
    воскресенья. С переходом на правило портала точка отсчёта — ПОНЕДЕЛЬНИК первой
    учебной недели, и границы недели сдвинулись на день. Это не косметика теста:
    воскресенье теперь принадлежит ПРЕДЫДУЩЕЙ неделе, и проверка Вс..Сб сломалась бы
    на законной формуле.
    """
    start = datetime.date(2026, 2, 9)          # понедельник
    assert start.weekday() == 0, "дата в тесте перестала быть понедельником"
    first = _parity(start)
    for i in range(1, 7):                      # Вт..Вс той же недели
        d = start + datetime.timedelta(days=i)
        assert _parity(d) == first, f"{d}: чётность изменилась ВНУТРИ недели"
    nxt = start + datetime.timedelta(days=7)
    assert _parity(nxt) != first, "чётность обязана смениться на следующей неделе"


def test_parity_alternates_over_ten_weeks():
    """Десять недель подряд обязаны идти строго через одну. Ловит и «застрявшую»
    чётность (всегда I), и слишком частое переключение."""
    start = datetime.date(2026, 2, 9)          # понедельник
    seq = [_parity(start + datetime.timedelta(days=7 * w)) for w in range(10)]
    for a, b in pairwise(seq):
        assert a != b, f"чётность не чередуется: {seq}"


#Точка отсчёта по правилу портала: (год, на какой день недели выпало 1 сентября)
#→ понедельник первой учебной недели. Значения взяты из `getReferenceDate()`
#(portal.esstu.ru/menu.htm), а не выведены нами.
_REFERENCE_CASES = [
    (2024, "воскресенье", datetime.date(2024, 9, 2)),
    (2025, "понедельник", datetime.date(2025, 9, 1)),
    (2026, "вторник",     datetime.date(2026, 8, 31)),
    (2027, "среда",       datetime.date(2027, 8, 30)),
    (2028, "пятница",     datetime.date(2028, 8, 28)),
    (2030, "воскресенье", datetime.date(2030, 9, 2)),
    (2031, "понедельник", datetime.date(2031, 9, 1)),
]


@pytest.mark.parametrize("year,подпись,ожидание", _REFERENCE_CASES)
def test_reference_date_matches_the_portal(year, подпись, ожидание):
    """🔥 ГЛАВНЫЙ СТОРОЖ ЭТОГО РАСЧЁТА, и он куплен дефектом на бою (31.08.2026).

    Мы считали неделю «номером недели с 1 января», портал — от начала УЧЕБНОГО года.
    Разошлись ровно на неделю: у нас шла II, у портала I, в сентябре 2026 расходились
    26 дней из 30. Студент видел расписание ЧУЖОЙ недели — правдоподобное и неверное.

    ⚠️ Проверяем именно ТОЧКУ ОТСЧЁТА, а не пары «дата → чётность». Чётность легко
    подогнать сдвигом, и такая подгонка сойдётся на текущей неделе, а развалится
    через полгода. Точка отсчёта — то, где живёт само правило.

    ⚠️ Асимметрия правила портала выглядит как ошибка, но ошибкой НЕ является:
    1 сентября в БУДНИЙ день → откатываемся к понедельнику НАЗАД (учебный год уже
    идёт), в ВЫХОДНОЙ → переносим ВПЕРЁД (в выходные не учатся). Выпрямлять нельзя —
    разойдёмся с порталом на переходной неделе, а она и есть первая учебная.
    """
    import sys
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "server"))
    from app.schedule_web import _academic_week_start

    #Сначала убеждаемся, что подпись в таблице не разъехалась с календарём: иначе
    #проверка держала бы придуманный случай, а не настоящий.
    дни = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    assert дни[datetime.date(year, 9, 1).weekday()] == подпись, (
        f"1 сентября {year} — не {подпись}; таблица случаев разошлась с календарём")

    got = _academic_week_start(datetime.date(year, 9, 15))
    assert got == ожидание, (
        f"1 сентября {year} ({подпись}): точка отсчёта {got}, а портал считает от {ожидание}")
    assert got.weekday() == 0, f"{got} — не понедельник; отсчёт недели обязан начинаться с него"


def test_the_day_the_defect_was_found():
    """Конкретный день, на котором расхождение заметили: 31.08.2026 — портал показывал
    I неделю, мы II. Отдельным тестом, потому что общее правило можно перенести верно,
    а на границе полугодия всё равно промахнуться: 31 августа лежит ДО 1 сентября и
    попадает в ветку «точка отсчёта в текущем году» только из-за месяца (8 > 7)."""
    assert _parity(datetime.date(2026, 8, 31)) == 1
    assert _parity(datetime.date(2026, 9, 7)) == 2, "следующая неделя обязана быть II"


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
