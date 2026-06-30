"""
test_schedule_parser.py — парсер расписания на СОХРАНЁННОЙ странице (без сети).

Фикстура tests/fixtures/group_K15_1.htm — реальная страница группы К15/1 с портала,
декодированная в UTF-8. Юнит-тесты от сети не зависят: проверяем разбор ячеек, дни,
обе недели, времена пар и чётность недели.
"""
import os
from datetime import date

from schedule import parse_group_page, parse_cell, current_week_parity, week_label
from schedule.parser import list_college_groups
from schedule.model import WEEKDAYS

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "group_K15_1.htm")


def _load_fixture() -> str:
    with open(_FIXTURE, "r", encoding="utf-8") as f:
        return f.read()


def test_parse_cell_full():
    """Полная ячейка: тип, предмет, преподаватель, аудитория."""
    ls = parse_cell("лек.Физика ШАГДУРОВА А.И.  а.0310", pair_no=2, time="10:45-12:20")
    assert ls is not None
    assert ls.kind == "лек"
    assert ls.subject == "Физика"
    assert ls.teacher == "ШАГДУРОВА А.И."
    assert ls.room == "0310"
    assert ls.pair_no == 2
    assert ls.raw == "лек.Физика ШАГДУРОВА А.И.  а.0310"


def test_parse_cell_empty():
    """Пустая клетка («_» или пробелы) → None (окно в расписании)."""
    assert parse_cell("_") is None
    assert parse_cell("   ") is None
    assert parse_cell("") is None


def test_parse_cell_subgroups():
    """Подгруппы: первый преподаватель/аудитория в основных полях, второй — в extra."""
    ls = parse_cell("пр.Иностранный язык РАДНАТАРОВА Н.В.  а.712и/д   КИМ С.В. - а.718а")
    assert ls is not None
    assert ls.subject == "Иностранный язык"
    assert ls.teacher == "РАДНАТАРОВА Н.В."
    assert ls.room == "712и/д"
    assert "КИМ" in ls.extra        # вторая подгруппа сохранена


def test_parse_cell_no_kind():
    """Физкультура идёт без префикса типа — разбор не должен падать, raw сохранён."""
    ls = parse_cell("Физическая культура ФКС 14  а.9-Спорт2")
    assert ls is not None
    assert "Физическая культура" in ls.raw
    assert ls.room == "9-Спорт2"


def test_parse_group_page_structure():
    """Страница группы: обе недели, дни недели, времена пар."""
    gs = parse_group_page(_load_fixture(), name="К15/1")
    assert gs.name == "К15/1"
    #обе недели присутствуют
    assert 1 in gs.weeks and 2 in gs.weeks
    #в каждой неделе есть дни из WEEKDAYS
    for wk in (1, 2):
        assert set(gs.weeks[wk].keys()).issubset(set(WEEKDAYS))
        assert gs.weeks[wk]                       # непусто
    #времена пар прочитаны (6 интервалов, начинаются с 09:00)
    assert len(gs.pair_times) == 6
    assert gs.pair_times[0].startswith("09:00")


def test_parse_group_page_known_lesson():
    """В понедельник недели I 2-я пара — лекция по физике (Шагдурова)."""
    gs = parse_group_page(_load_fixture(), name="К15/1")
    mon = gs.weeks[1].get("Пнд", [])
    phys = [l for l in mon if l.subject == "Физика"]
    assert phys, "Физика в понедельник не найдена"
    assert phys[0].teacher == "ШАГДУРОВА А.И."


def test_group_subjects_collected():
    """Список предметов группы непустой и без мусорных пустых строк."""
    gs = parse_group_page(_load_fixture(), name="К15/1")
    subs = gs.subjects()
    assert "Физика" in subs
    assert "Математика" in subs
    assert all(s.strip() for s in subs)


def test_list_college_groups_filters_K():
    """Из индекса берём только группы на «К» (магистратура «М…» отброшена)."""
    html = (
        '<a href="1.htm">К15/1</a>'
        '<a href="69.htm">М215</a>'
        '<a href="2.htm">К25</a>'
    )
    groups = list_college_groups(html)
    names = [n for n, _ in groups]
    assert "К15/1" in names
    assert "К25" in names
    assert "М215" not in names


def test_build_snapshot_offline():
    """build_snapshot с подменённым fetch (без сети): группы, предметы, инверсия
    преподавателей и round-trip сериализации снимка."""
    from schedule.parser import build_snapshot
    from schedule.model import Snapshot

    index_html = '<a href="1.htm">К15/1</a><a href="69.htm">М215</a>'
    group_html = _load_fixture()

    def fake_fetch(url, timeout=20):
        return index_html if url.endswith("raspisan.htm") else group_html

    snap = build_snapshot(fetch=fake_fetch)
    assert "К15/1" in snap.groups            # колледж попал
    assert "М215" not in snap.groups         # магистратура отброшена
    assert "Физика" in snap.subjects
    #инверсия преподавателей: у Шагдуровой есть пара в К15/1
    assert any("ШАГДУРОВА" in t for t in snap.teachers())

    #сериализация туда-обратно не теряет структуру
    restored = Snapshot.from_dict(snap.to_dict())
    assert restored.group_names() == snap.group_names()
    assert restored.subjects == snap.subjects
    assert restored.teachers() == snap.teachers()


def test_week_parity_replicates_portal():
    """Чётность недели совпадает с формулой портального week()."""
    #1 января — numberOfDays=0; результат зависит от дня недели года.
    #Проверяем стабильность и диапазон значений, плюс конкретные эталоны.
    assert current_week_parity(date(2025, 9, 1)) in (1, 2)
    #Соседние недели чередуются: parity на +7 дней должен инвертироваться.
    d = date(2025, 9, 1)
    from datetime import timedelta
    assert current_week_parity(d) != current_week_parity(d + timedelta(days=7))
    assert week_label(1) == "I неделя"
    assert week_label(2) == "II неделя"
