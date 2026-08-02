"""
test_schedule_categories_web.py — /web/schedule* с параметром category
(schedule_web.py + web.py). Сеть замокана — подменяем schedule.parser.fetch_text
и передаём готовый offline-снимок, как это уже делает test_schedule_parser.py.

Регрессия — без category (или category=college) поведение эндпоинтов не меняется
ни в одном байте.
"""
from app import schedule_web
from schedule import parser as P
from conftest import make_admin


def _fake_fetch_factory(index_html: str, group_html: str):
    def _fake_fetch(url, timeout=20):
        return index_html if url.endswith("raspisan.htm") else group_html
    return _fake_fetch


def setup_function(_):
    """TTL-кэш schedule_web — модульный, между тестами не сбрасывается сам."""
    schedule_web.invalidate_all()


def test_categories_endpoint_lists_four_with_dated_flags(client):
    admin = make_admin(client)
    r = client.get("/web/schedule/categories", headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["default"] == "college"
    keys = {c["key"]: c["dated"] for c in data["categories"]}
    assert keys == {"college": False, "bakalavriat": False, "zo1": True, "zo2": True}


def test_groups_endpoint_uses_category_param(client, monkeypatch):
    admin = make_admin(client)
    index_html = '<table><tr><td><a href="1.htm">Б165</a></td><td><a href="2.htm">Б175</a></td></tr></table>'
    monkeypatch.setattr(P, "fetch_text", _fake_fetch_factory(index_html, ""))

    r = client.get("/web/schedule/groups", params={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 200, r.text
    assert set(r.json()["groups"]) == {"Б165", "Б175"}


def test_groups_endpoint_default_is_still_college(client, monkeypatch):
    """Без category (или college) — старое поведение: только «К», «М» отброшена."""
    admin = make_admin(client)
    index_html = '<table><tr><td><a href="1.htm">К15/1</a></td><td><a href="2.htm">М215</a></td></tr></table>'
    monkeypatch.setattr(P, "fetch_text", _fake_fetch_factory(index_html, ""))

    r = client.get("/web/schedule/groups", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["groups"] == ["К15/1"]


def test_groups_endpoint_returns_by_course(client, monkeypatch):
    """§3.5.5: /web/schedule/groups отдаёт ЕЩЁ и by_course — {курс: [группы]},
    курс — реальный столбец таблицы индекса (заголовок «N курс»), не фиксирован."""
    admin = make_admin(client)
    index_html = ('<table>'
                 '<tr><td> 1 курс </td><td> 2 курс </td></tr>'
                 '<tr><td><a href="1.htm">Б165</a></td><td><a href="2.htm">Б164</a></td></tr>'
                 '</table>')
    monkeypatch.setattr(P, "fetch_text", _fake_fetch_factory(index_html, ""))

    r = client.get("/web/schedule/groups", params={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["groups"]) == {"Б165", "Б164"}
    assert body["by_course"] == {"1": ["Б165"], "2": ["Б164"]}


def test_group_schedule_dated_category_end_to_end(client, monkeypatch):
    """Полный путь GET /web/schedule?category=zo1: сессионные блоки, дни-даты."""
    admin = make_admin(client)
    index_html = '<table><tr><td><a href="1.htm">ЗУ-1</a></td></tr></table>'
    group_html = (
        "<table>"
        "<tr><td>Пары</td><td>1-я</td></tr>"
        "<tr><td>Время</td><td>09:00-10:35</td></tr>"
        "<tr><td>Пнд,06 апреля</td><td>лек.Химия Петров П.П. а.100</td></tr>"
        "</table>"
    )
    monkeypatch.setattr(P, "fetch_text", _fake_fetch_factory(index_html, group_html))

    r = client.get("/web/schedule", params={"group": "ЗУ-1", "category": "zo1"}, headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["available"] is True
    weeks = data["schedule"]["weeks"]
    assert list(weeks.keys()) == ["1"]
    assert "Пнд, 06 апреля" in weeks["1"]
    lesson = weeks["1"]["Пнд, 06 апреля"][0]
    assert lesson["subject"] == "Химия"
    assert lesson["teacher"] == "Петров П.П."


def test_admin_schedule_resolves_category_from_stored_group_when_not_passed(client, monkeypatch):
    """§3.5.5: /web/admin/schedule раньше НИКОГДА не знал про category и всегда искал
    группу в индексе колледжа — импортированная (валидная) бакалавриат/заочная группа
    отвечала «расписание недоступно», хотя портал её прекрасно отдаёт. Группа заведена
    ЧЕРЕЗ РЕАЛЬНЫЙ путь импорта (Group.category уже верный в базе) — админ смотрит
    расписание БЕЗ явного category в запросе, сервер обязан сам его подставить."""
    admin = make_admin(client)
    index_html = '<table><tr><td><a href="1.htm">Б165</a></td></tr></table>'
    group_html = (
        "<table>"
        "<tr><td>Пары</td><td>1-я</td></tr>"
        "<tr><td>Время</td><td>09:00-10:35</td></tr>"
        "<tr><td>Пнд</td><td>лек.Физика ИВАНОВ И.И. а.100</td></tr>"
        "<tr><td>Втр</td><td>_</td></tr>"
        "<tr><td>Срд</td><td>_</td></tr>"
        "<tr><td>Чтв</td><td>_</td></tr>"
        "<tr><td>Птн</td><td>_</td></tr>"
        "<tr><td>Сбт</td><td>_</td></tr>"
        "</table>"
    )
    monkeypatch.setattr(P, "fetch_text", _fake_fetch_factory(index_html, group_html))

    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat", "group_name": "Б165"}, headers=admin)
    assert r.status_code == 200, r.text

    r2 = client.get("/web/admin/schedule", params={"group": "Б165"}, headers=admin)
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["available"] is True
    lesson = data["schedule"]["weeks"]["1"]["Пнд"][0]
    assert lesson["subject"] == "Физика"


def test_admin_schedule_college_group_unaffected_without_category(client, monkeypatch):
    """Регрессия: колледжевая группа (даже вовсе не заведённая как `Group`-строка)
    продолжает резолвиться как раньше, без единого изменения поведения."""
    admin = make_admin(client)
    index_html = '<table><tr><td><a href="1.htm">К15/1</a></td></tr></table>'
    group_html = (
        "<table>"
        "<tr><td>Пары</td><td>1-я</td></tr>"
        "<tr><td>Время</td><td>09:00-10:35</td></tr>"
        "<tr><td>Пнд</td><td>лек.Химия ПЕТРОВ П.П. а.100</td></tr>"
        "<tr><td>Втр</td><td>_</td></tr>"
        "<tr><td>Срд</td><td>_</td></tr>"
        "<tr><td>Чтв</td><td>_</td></tr>"
        "<tr><td>Птн</td><td>_</td></tr>"
        "<tr><td>Сбт</td><td>_</td></tr>"
        "</table>"
    )
    monkeypatch.setattr(P, "fetch_text", _fake_fetch_factory(index_html, group_html))

    r = client.get("/web/admin/schedule", params={"group": "К15/1"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["available"] is True


def test_overrides_not_applied_outside_college(client, monkeypatch):
    """Оверлеи (ScheduleOverride) — только для колледжа; для остальных категорий
    _group_schedule отдаёт портальные данные как есть, без попытки наложить их."""
    admin = make_admin(client)
    index_html = '<table><tr><td><a href="1.htm">Б165</a></td></tr></table>'
    group_html = (
        "<table>"
        "<tr><td>Пары</td><td>1-я</td><td>2-я</td></tr>"
        "<tr><td>Время</td><td>09:00-10:35</td><td>10:45-12:20</td></tr>"
        "<tr><td>Пнд</td><td>лек.Физика ИВАНОВ И.И. а.100</td><td>_</td></tr>"
        "<tr><td>Втр</td><td>_</td><td>_</td></tr>"
        "<tr><td>Срд</td><td>_</td><td>_</td></tr>"
        "<tr><td>Чтв</td><td>_</td><td>_</td></tr>"
        "<tr><td>Птн</td><td>_</td><td>_</td></tr>"
        "<tr><td>Сбт</td><td>_</td><td>_</td></tr>"
        "</table>"
    )
    monkeypatch.setattr(P, "fetch_text", _fake_fetch_factory(index_html, group_html))

    r = client.get("/web/schedule", params={"group": "Б165", "category": "bakalavriat"},
                   headers=admin)
    assert r.status_code == 200, r.text
    lesson = r.json()["schedule"]["weeks"]["1"]["Пнд"][0]
    assert lesson.get("_override") is not True
