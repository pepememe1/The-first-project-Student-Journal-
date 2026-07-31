"""
test_group_category.py — Group.category (schedule/parser.py::CATEGORIES) — создание/
правка группы с категорией, эндпоинт импорта каталожной записи по категории,
списочный эндпоинт отдаёт category. Сеть (schedule_web) замокана.
"""
from app import schedule_web
from schedule import parser as P
from conftest import make_admin, make_teacher


def setup_function(_):
    schedule_web.invalidate_all()


# ── создание/правка группы с категорией ──────────────────────────────────────

def test_create_group_defaults_to_college(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups", json={"name": "ИС-21", "subjects": []}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "college"

    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "ИС-21")
    assert grp["category"] == "college"


def test_create_group_with_known_category(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups",
                    json={"name": "Б165", "subjects": [], "category": "bakalavriat"},
                    headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "bakalavriat"


def test_create_group_with_unknown_category_falls_back_to_college(client):
    """Неизвестный/мусорный ключ категории — не 400, тихий фолбэк на «college»
    (тот же принцип, что «пусто → college»: не ломаем создание группы из-за
    опечатки в необязательном поле)."""
    admin = make_admin(client)
    r = client.post("/web/admin/groups",
                    json={"name": "ИС-22", "subjects": [], "category": "not-a-real-category"},
                    headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "college"


def test_update_group_category(client):
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "ИС-23", "subjects": []}, headers=admin)
    r = client.put("/web/admin/groups/ИС-23", json={"category": "zo1"}, headers=admin)
    assert r.status_code == 200, r.text

    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "ИС-23")
    assert grp["category"] == "zo1"


# ── импорт группы-каталожной записи по категории ─────────────────────────────

def test_import_schedule_category_creates_catalog_only_group(client, monkeypatch):
    admin = make_admin(client)
    monkeypatch.setattr(P, "fetch_text",
                        lambda url, timeout=20: '<a href="1.htm">Б165</a><a href="2.htm">Б175</a>')

    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat", "group_name": "Б165"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "name": "Б165", "category": "bakalavriat"}

    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "Б165")
    assert grp["category"] == "bakalavriat"
    assert grp["subjects"] == []          # каталожная запись — без предметов


def test_import_schedule_category_rejects_name_not_on_portal(client, monkeypatch):
    admin = make_admin(client)
    monkeypatch.setattr(P, "fetch_text", lambda url, timeout=20: '<a href="1.htm">Б165</a>')

    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat", "group_name": "Выдуманная-группа"},
                    headers=admin)
    assert r.status_code == 422, r.text


def test_import_schedule_category_rejects_unknown_category(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "not-a-real-category", "group_name": "Б165"},
                    headers=admin)
    assert r.status_code == 400


def test_import_schedule_category_conflicts_on_existing_group(client, monkeypatch):
    admin = make_admin(client)
    monkeypatch.setattr(P, "fetch_text", lambda url, timeout=20: '<a href="1.htm">Б165</a>')
    r1 = client.post("/web/admin/groups/import-schedule-category",
                     json={"category": "bakalavriat", "group_name": "Б165"}, headers=admin)
    assert r1.status_code == 200, r1.text
    r2 = client.post("/web/admin/groups/import-schedule-category",
                     json={"category": "bakalavriat", "group_name": "Б165"}, headers=admin)
    assert r2.status_code == 409


def test_import_schedule_category_requires_admin(client, monkeypatch):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    monkeypatch.setattr(P, "fetch_text", lambda url, timeout=20: '<a href="1.htm">Б165</a>')
    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat", "group_name": "Б165"}, headers=teacher)
    assert r.status_code == 403


def test_import_schedule_category_missing_fields_is_400(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 400
