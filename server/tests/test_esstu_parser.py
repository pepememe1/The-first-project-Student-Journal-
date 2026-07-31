"""
test_esstu_parser.py — parsers/esstu_parser.py на РЕАЛЬНЫХ снимках сайта ВСГУТУ.

Снимки (server/tests/fixtures/esstu_*) — сохранённые вживую HTML-страницы и PDF
учебных планов (см. докстринг esstu_parser.py — вся структура разведана по этим же
файлам). В сеть НЕ ходим: requests.get подменяется на чтение fixture с диска, иначе
тесты были бы то зелёными, то красными в зависимости от того, жив ли сайт колледжа
прямо сейчас, и тянули бы CI за собой в интернет.

pdfplumber опционален (см. requirements) — модуль пропускается целиком, если пакета
нет, той же формулой, что и в esstu_parser.py самом.
"""
import pathlib

import pytest

pdfplumber = pytest.importorskip("pdfplumber", reason="pdfplumber не установлен")

from app.parsers import esstu_parser as P  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class _FakeResponse:
    def __init__(self, content: bytes, encoding: str = "utf-8"):
        self.content = content
        self.encoding = encoding          # settable — get_all_specialties() переприсваивает
        self.apparent_encoding = encoding
        self.status_code = 200

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8")

    def raise_for_status(self):
        pass


@pytest.fixture()
def college_html():
    return (FIXTURES / "esstu_college.html").read_bytes()


@pytest.fixture()
def directions_09_02_07_html():
    return (FIXTURES / "esstu_directions_09_02_07.html").read_bytes()


@pytest.fixture()
def plan_09_02_07_pdf():
    return (FIXTURES / "esstu_plan_09_02_07_2022.pdf").read_bytes()


@pytest.fixture()
def plan_09_02_06_pdf():
    return (FIXTURES / "esstu_plan_09_02_06_2022.pdf").read_bytes()


# ── get_all_specialties() ───────────────────────────────────────────────────

def test_get_all_specialties_reads_real_table(monkeypatch, college_html):
    monkeypatch.setattr(P, "_fetch", lambda url, timeout=P._TIMEOUT_PAGE: _FakeResponse(college_html))
    specialties = P.get_all_specialties()
    assert len(specialties) == 12
    codes = {s["code"] for s in specialties}
    assert {"09.02.07", "09.02.06", "43.02.16"} <= codes
    isp = next(s for s in specialties if s["code"] == "09.02.07")
    assert isp["name"] == "Информационные системы и программирование"
    assert isp["qualification"] == "программист"
    assert isp["directions_url"] == f"{P.DIRECTIONS_URL}?code=09.02.07&lvlCode=SPO9"


def test_get_all_specialties_empty_on_network_failure(monkeypatch):
    monkeypatch.setattr(P, "_fetch", lambda *a, **k: None)
    assert P.get_all_specialties() == []


def test_get_all_specialties_empty_on_garbage_html(monkeypatch):
    monkeypatch.setattr(P, "_fetch", lambda *a, **k: _FakeResponse(b"<html><body>oops</body></html>"))
    assert P.get_all_specialties() == []


# ── match_specialty() ────────────────────────────────────────────────────────

def test_match_specialty_known_prefix(college_html, monkeypatch):
    monkeypatch.setattr(P, "_fetch", lambda *a, **k: _FakeResponse(college_html))
    specialties = P.get_all_specialties()
    m = P.match_specialty("ИС-21", specialties)
    assert m is not None and m["code"] == "09.02.07"


def test_match_specialty_unknown_prefix_returns_none():
    """«К74/1» — кафедральная нумерация, НЕ в GROUP_PREFIX_TO_SPECIALTY (см. докстринг
    словаря: угадывать такие соответствия нельзя, только подтверждённые вручную)."""
    assert P.match_specialty("К74/1", []) is None
    assert P.match_specialty("", []) is None


# ── _fetch_plan_years() / get_study_plan() год набора ───────────────────────

def test_fetch_plan_years_reads_real_table(monkeypatch, directions_09_02_07_html):
    monkeypatch.setattr(P, "_fetch", lambda *a, **k: _FakeResponse(directions_09_02_07_html))
    years = P._fetch_plan_years("09.02.07")
    assert set(years) == {2022, 2023, 2024, 2025}
    assert years[2022].startswith("/aicstorages/publicDownload/")


def test_get_study_plan_empty_for_unpublished_year(monkeypatch, directions_09_02_07_html):
    monkeypatch.setattr(P, "_fetch", lambda *a, **k: _FakeResponse(directions_09_02_07_html))
    assert P.get_study_plan("09.02.07", 1999) == []


# ── _parse_pdf_plan() — самая рискованная часть: колонка часов + сетка семестров ──

def test_pdf_hours_match_manually_verified_values(plan_09_02_07_pdf):
    """Числа сверены вручную (см. историю разведки) — если разбор «поедет» на
    другую колонку, эти конкретные значения расскажут об этом first."""
    rows = P._parse_pdf_plan(plan_09_02_07_pdf)
    assert len(rows) == 61
    by_index = {r["index"]: r for r in rows}
    assert by_index["ОУП.01"]["subject"] == "Русский язык"
    assert by_index["ОУП.01"]["hours"] == 90.0
    assert by_index["ОУП.01"]["zet"] == pytest.approx(2.5)
    assert by_index["ОУП.02"]["hours"] == 78.0
    assert by_index["ОУП.04"]["hours"] == 234.0  # Математика


def test_pdf_hours_by_semester_sums_to_total(plan_09_02_07_pdf):
    """Самопроверка сетки: там, где семестры нашлись, их сумма обязана совпасть
    с «Всего» — она же и есть критерий, по которому сетка вообще принимается."""
    rows = P._parse_pdf_plan(plan_09_02_07_pdf)
    with_grid = [r for r in rows if r["hours_by_semester"]]
    assert len(with_grid) >= 30  # больше половины дисциплин — многосеместровых меньшинство
    for r in with_grid:
        assert sum(r["hours_by_semester"].values()) == pytest.approx(r["hours"], abs=0.5)


def test_pdf_known_two_semester_subject_splits_correctly(plan_09_02_07_pdf):
    """Русский язык — 2 семестра (проверено вручную: 38+52=90)."""
    rows = P._parse_pdf_plan(plan_09_02_07_pdf)
    row = next(r for r in rows if r["index"] == "ОУП.01")
    assert row["hours_by_semester"] == {1: 38.0, 2: 52.0}


def test_pdf_column_detection_generalizes_to_a_different_specialty(plan_09_02_06_pdf):
    """Другая специальность — ДРУГАЯ колонка «Всего» (8, не 9) и ДРУГОЙ шаг сетки
    семестров (13, не 7) — числа сверены вручную отдельно от первого файла."""
    rows = P._parse_pdf_plan(plan_09_02_06_pdf)
    assert rows  # структура совсем другая (128 колонок вместо 75) — должна ПРОЧИТАТЬСЯ
    by_index = {r["index"]: r for r in rows}
    assert by_index["ОГСЭ.01"]["subject"] == "Основы философии"
    assert by_index["ОГСЭ.01"]["hours"] == 52.0
    assert by_index["ОГСЭ.02"]["hours"] == 36.0


def test_pdf_parse_returns_empty_without_pdfplumber(monkeypatch, plan_09_02_07_pdf):
    """pdfplumber недоступен (окружение без опционального пакета) — честное [],
    не исключение наружу."""
    import builtins
    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "pdfplumber":
            raise ImportError("нет пакета")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    assert P._parse_pdf_plan(plan_09_02_07_pdf) == []


def test_pdf_parse_returns_empty_on_garbage_bytes():
    assert P._parse_pdf_plan(b"not actually a pdf") == []


# ── get_study_plan() — end-to-end (год→href→скачка→разбор), сеть замокана ──

def test_get_study_plan_end_to_end(monkeypatch, directions_09_02_07_html, plan_09_02_07_pdf):
    calls = []

    def _fake_fetch(url, timeout=P._TIMEOUT_PAGE):
        calls.append(url)
        if "directions2.htm" in url:
            return _FakeResponse(directions_09_02_07_html)
        return _FakeResponse(plan_09_02_07_pdf)

    monkeypatch.setattr(P, "_fetch", _fake_fetch)
    rows = P.get_study_plan("09.02.07", 2022)
    assert len(rows) == 61
    assert len(calls) == 2  # страница «года набора» + сам файл плана
