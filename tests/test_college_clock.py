"""test_college_clock.py — часы колледжа: одна дверь, и мимо неё никто не ходит.

`college_clock` отвечает «сколько на часах в Улан-Удэ» независимо от пояса машины. Здесь:
• сам модуль — смена суток ровно в полночь по Улан-Удэ, метки из базы, мусор;
• разбор напоминаний — у ЛЮБОЙ ветки результат несёт пояс «сейчас», иначе сервер отдаёт
  подсказку без зоны, и телефон в другом поясе читает её по своим часам;
• СВОЙСТВО по всему продукту: ни одного обращения к часам МАШИНЫ ради даты или времени
  суток (`date.today()`, `datetime.now()` без пояса, `.astimezone()` без пояса,
  `time.localtime/strftime/ctime/mktime`, `fromtimestamp` без пояса, `utcnow`).
  До 15.10.2026 таких мест было больше двадцати, и бой (Москва) жил на пять часов
  позади колледжа. Новое такое место красит прогон.

⚠️ Обратный ход у сторожа свой: детектор натравливается на синтетический текст с каждой
запрещённой формой и обязан найти все — иначе он неотличим от сломанного разбора.
"""
import ast
import pathlib
from datetime import date, datetime, timedelta, timezone

import pytest

import college_clock
import reminder_parse

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _freeze(monkeypatch, utc):
    monkeypatch.setattr(college_clock, "_utcnow", lambda: utc)


# ── сам модуль ──────────────────────────────────────────────────────────────────────
def test_offset_is_ulan_ude():
    assert college_clock.UTC_OFFSET_H == 8
    assert college_clock.TZ.utcoffset(None) == timedelta(hours=8)


@pytest.mark.parametrize("utc, day", [
    (datetime(2026, 10, 15, 15, 59, 59, tzinfo=timezone.utc), date(2026, 10, 15)),
    (datetime(2026, 10, 15, 16, 0, 0, tzinfo=timezone.utc), date(2026, 10, 16)),
])
def test_day_changes_at_ulan_ude_midnight(monkeypatch, utc, day):
    _freeze(monkeypatch, utc)
    assert college_clock.today() == day
    assert college_clock.ddmmyyyy() == day.strftime("%d.%m.%Y")


def test_naive_moment_is_read_as_utc():
    assert college_clock.local(datetime(2026, 10, 15, 23, 30)).strftime("%d.%m %H:%M") == "16.10 07:30"


@pytest.mark.parametrize("iso, expected", [
    ("2026-10-15T23:30:00+00:00", "16.10.2026 07:30"),
    ("2026-10-15T23:30:00Z", "16.10.2026 07:30"),
    ("2026-10-16T07:30:00+08:00", "16.10.2026 07:30"),
])
def test_iso_from_the_database_lands_on_college_clock(iso, expected):
    assert college_clock.local_from_iso(iso).strftime("%d.%m.%Y %H:%M") == expected


@pytest.mark.parametrize("junk", ["", "мусор", None, "2026-13-40"])
def test_unparsable_iso_is_unknown_not_now(junk):
    assert college_clock.local_from_iso(junk) is None


# ── разбор напоминаний ──────────────────────────────────────────────────────────────
# 16.10.2026 07:30 в Улан-Удэ.
NOW_IRK = datetime(2026, 10, 16, 7, 30, tzinfo=college_clock.TZ)


@pytest.mark.parametrize("text, expected", [
    ("напомни завтра в 10:00", "17.10.2026 10:00"),
    ("сегодня в 15:00 пара", "16.10.2026 15:00"),
    ("в пятницу в 12:00", "16.10.2026 12:00"),
    ("12 мая в 10:00", "12.05.2027 10:00"),
    ("20.10 в 9:30", "20.10.2026 09:30"),
    ("в 18:00", "16.10.2026 18:00"),
])
def test_every_reminder_branch_keeps_the_college_zone(text, expected):
    """Ветка с датой («12 мая», «20.10») собирала время БЕЗ пояса: сервер отдавал
    подсказку «10:00» без зоны, и телефон в Москве ставил напоминание на 10:00 МСК."""
    w = reminder_parse.parse_reminder(text, NOW_IRK)["when"]
    assert w.tzinfo is not None and w.utcoffset() == timedelta(hours=8), (text, w)
    assert w.strftime("%d.%m.%Y %H:%M") == expected


# ── свойство: никто не ходит к часам машины ─────────────────────────────────────────
#Где искать: всё, что исполняется в продукте (сервер, общие модули, десктоп).
_SCAN = ["server/app", "desktop", "data", "sync", "schedule"]
#Корневые общие модули — по одному файлу (в корне лежат и скрипты сборки).
_SCAN_ROOT_FILES = True
#Исключения — С ПРИЧИНОЙ. Пусто, и так и должно быть: метки для ХРАНЕНИЯ берутся как
#`datetime.now(timezone.utc)` и сюда не попадают; календарь и циферблат — `college_clock`.
ALLOWED: dict = {}

_TIME_FUNCS = {"localtime", "ctime", "mktime"}


def _is_datetime_like(node) -> bool:
    """`date`, `datetime`, `_dt.date`, `datetime.datetime` …"""
    name = node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")
    return name in ("date", "datetime")


_CALENDAR_ATTRS = {"year", "month", "day", "hour", "minute"}
_CALENDAR_CALLS = {"weekday", "isoweekday", "date", "timetuple"}


def _is_now_call(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "now" and _is_datetime_like(node.func.value))


def utc_calendar_reads(tree) -> list:
    """Календарь, взятый из UTC-момента: `now = datetime.now(timezone.utc)` и затем
    `now.year`, `now.month`, `now.weekday()` в той же функции (или сразу
    `datetime.now(timezone.utc).year`). Первая версия сторожа этого не видела — вызов
    с поясом законен для ХРАНЕНИЯ, — и так прожил десктопный `data/terms.default_term`
    (находка Полковника 15.10.2026)."""
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign) and _is_now_call(n.value)
                 for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(fn):
            if not isinstance(n, ast.Attribute):
                continue
            base = n.value
            from_now = _is_now_call(base) or (isinstance(base, ast.Name) and base.id in names)
            if from_now and (n.attr in _CALENDAR_ATTRS or n.attr in _CALENDAR_CALLS):
                out.append((n.lineno, f"календарь из UTC-момента (.{n.attr})"))
    return out


def machine_clock_calls(source: str) -> list:
    """Обращения к часам машины ради даты/времени суток: [(строка, форма)]."""
    tree = ast.parse(source)
    out = utc_calendar_reads(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        f, attr = node.func, node.func.attr
        no_args = not node.args and not node.keywords
        base = f.value
        if attr in ("today", "utcnow") and _is_datetime_like(base):
            out.append((node.lineno, f"{attr}()"))
        elif attr == "now" and _is_datetime_like(base) and no_args:
            out.append((node.lineno, "now() без пояса"))
        elif attr == "astimezone" and no_args:
            out.append((node.lineno, "astimezone() без пояса"))
        elif attr == "fromtimestamp" and _is_datetime_like(base) and len(node.args) < 2 \
                and not any(k.arg == "tz" for k in node.keywords):
            out.append((node.lineno, "fromtimestamp() без пояса"))
        elif isinstance(base, ast.Name) and base.id == "time":
            if attr in _TIME_FUNCS or (attr == "strftime" and len(node.args) < 2):
                out.append((node.lineno, f"time.{attr}"))
    return out


def _product_files():
    files = []
    for d in _SCAN:
        files += [p for p in (ROOT / d).rglob("*.py") if "tests" not in p.parts]
    if _SCAN_ROOT_FILES:
        files += [p for p in ROOT.glob("*.py") if p.name != "college_clock.py"]
    return files


def test_nobody_reads_the_machine_clock_for_dates():
    found = []
    for p in _product_files():
        rel = p.relative_to(ROOT).as_posix()
        for line, form in machine_clock_calls(p.read_text(encoding="utf-8")):
            if (rel, line) not in ALLOWED:
                found.append(f"{rel}:{line} — {form}")
    assert not found, ("Часы МАШИНЫ вместо часов колледжа (бой живёт по Москве, колледж — по "
                       "Улан-Удэ). Возьми `college_clock.now()/today()/stamp()`, а для метки "
                       "хранения — `datetime.now(timezone.utc)`:\n" + "\n".join(found))


def test_allowed_list_has_no_dead_entries():
    dead = [k for k in ALLOWED if not (ROOT / k[0]).exists()]
    assert not dead, dead


def test_the_detector_sees_every_forbidden_form():
    """Обратный ход: каждая форма, которой был устроен дефект, обязана находиться."""
    src = "\n".join([
        "import time, datetime as _dt",
        "from datetime import date, datetime, timezone",
        "a = date.today()",
        "b = datetime.now()",
        "c = _dt.date.today()",
        "d = datetime.now(timezone.utc).astimezone()",
        "e = time.strftime('%Y')",
        "f = time.localtime(1)",
        "g = datetime.fromtimestamp(1)",
        "h = datetime.utcnow()",
        "i = datetime.today()",
        #А это законно и находиться НЕ должно:
        "ok1 = datetime.now(timezone.utc)",
        "ok2 = time.strftime('%Y', time.gmtime())",
        "ok3 = datetime.fromtimestamp(1, timezone.utc)",
        "ok4 = x.astimezone(timezone.utc)",
        #Календарь из UTC-момента — дефект `data/terms.default_term` до 15.10.2026:
        "def term():",
        "    now = datetime.now(timezone.utc)",
        "    return now.year, now.month",
        "def stamp():",
        "    now = datetime.now(timezone.utc)",
        "    return now.isoformat(), datetime.now(timezone.utc).weekday()",
    ])
    lines = sorted({line for line, _ in machine_clock_calls(src)})
    assert lines == [3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 21], lines


@pytest.mark.parametrize("utc, term", [
    (datetime(2030, 8, 31, 16, 30, tzinfo=timezone.utc), ("2030/2031", 1)),   #1 сен 00:30 Улан-Удэ
    (datetime(2030, 8, 31, 15, 30, tzinfo=timezone.utc), ("2029/2030", 2)),   #31 авг 23:30
    (datetime(2031, 1, 31, 16, 30, tzinfo=timezone.utc), ("2030/2031", 2)),   #1 фев 00:30
])
def test_desktop_term_follows_the_college_calendar(monkeypatch, utc, term):
    """Программа на ПК выбирает семестр тем же календарём, что сервер (`app/db.default_term`):
    иначе итоговая оценка, выставленная на ПК в первые часы 1 сентября, уезжает в другой
    семестр, чем на сайте. Год заведомо не текущий — сторож календарных тестов."""
    from data import terms
    _freeze(monkeypatch, utc)
    assert terms.default_term() == term
