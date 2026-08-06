"""
test_admin_subjects_portal.py — каталог предметов по категориям портала (живой запрос
Влада: сортировка «Предметов» на колледж/бакалавриат/заочное, как у Расписания/Групп,
+ импорт с портала без «- N п/г»-дублей). Сеть (schedule_web) замокана.
"""
from app import schedule_web
from schedule import parser as P
from conftest import make_admin, make_teacher


def setup_function(_):
    schedule_web.invalidate_all()


def _snapshot_with_subgroup_tag(monkeypatch):
    """Реальный Snapshot через настоящий build_snapshot: одна группа с лекцией без
    метки («Физика») и лабораторной, разбитой на подгруппы («Информатика- 1 п/г» /
    «- 2 п/г»). Тот же приём, что уже применён в test_group_category.py."""
    index_html = '<table><tr><td><a href="1.htm">Б165</a></td></tr></table>'
    page = (
        "<table>"
        "<tr><td>Пары</td><td>1-я</td><td>2-я</td></tr>"
        "<tr><td>Время</td><td>09:00-10:35</td><td>10:45-12:20</td></tr>"
        "<tr><td>Пнд</td><td>лек.Физика ИВАНОВ И.И. а.100</td>"
        "<td>лаб.Информатика- 1 п/г ЦЫРЕНОВА А.А. а.15-357-2</td></tr>"
        "<tr><td>Втр</td><td>_</td><td>лаб.Информатика- 2 п/г ЦЫРЕНОВА А.А. а.15-357-1</td></tr>"
        "<tr><td>Срд</td><td>_</td><td>_</td></tr><tr><td>Чтв</td><td>_</td><td>_</td></tr>"
        "<tr><td>Птн</td><td>_</td><td>_</td></tr><tr><td>Сбт</td><td>_</td><td>_</td></tr></table>")

    def _fetch(url, timeout=20):
        if url.endswith("raspisan.htm"):
            return index_html
        if url.endswith("1.htm"):
            return page
        return ""
    monkeypatch.setattr(P, "fetch_text", _fetch)
    return P.build_snapshot(category="bakalavriat", fetch=_fetch)


def test_portal_subjects_excludes_subgroup_duplicate(client, monkeypatch):
    """Ключевой живой запрос: «Информатика- 1/2 п/г» не должна всплыть как отдельная
    строка — только каноническая «Информатика», один раз."""
    admin = make_admin(client)
    snap = _snapshot_with_subgroup_tag(monkeypatch)
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))

    r = client.get("/web/admin/subjects/portal", params={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 200, r.text
    names = [s["name"] for s in r.json()["subjects"]]
    assert names.count("Информатика") == 1
    assert not any("п/г" in n for n in names)
    assert "Физика" in names


def test_portal_subjects_marks_already_in_catalog(client, monkeypatch):
    admin = make_admin(client)
    snap = _snapshot_with_subgroup_tag(monkeypatch)
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))
    client.post("/web/admin/subjects", json={"name": "Физика"}, headers=admin)

    r = client.get("/web/admin/subjects/portal", params={"category": "bakalavriat"}, headers=admin)
    by_name = {s["name"]: s["in_catalog"] for s in r.json()["subjects"]}
    assert by_name["Физика"] is True
    assert by_name["Информатика"] is False


def test_portal_subjects_reports_building(client, monkeypatch):
    admin = make_admin(client)
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (None, True))
    r = client.get("/web/admin/subjects/portal", params={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["building"] is True
    assert r.json()["subjects"] == []


def test_portal_subjects_rejects_unknown_category(client):
    admin = make_admin(client)
    r = client.get("/web/admin/subjects/portal", params={"category": "not-a-category"}, headers=admin)
    assert r.status_code == 400


def test_portal_subjects_requires_admin(client, monkeypatch):
    admin = make_admin(client)
    headers = make_teacher(client, admin, login="t1")
    snap = _snapshot_with_subgroup_tag(monkeypatch)
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))
    r = client.get("/web/admin/subjects/portal", params={"category": "bakalavriat"}, headers=headers)
    assert r.status_code == 403


def test_import_portal_adds_missing_subjects_without_duplicates(client, monkeypatch):
    admin = make_admin(client)
    snap = _snapshot_with_subgroup_tag(monkeypatch)
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))

    r = client.post("/web/admin/subjects/import-portal",
                    json={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["imported"] == 2                 # «Физика» + «Информатика», без п/г-дублей
    assert data["skipped"] == 0

    names = {s["name"] for s in client.get("/web/admin/subjects", headers=admin).json()["subjects"]}
    assert names == {"Физика", "Информатика"}
    assert not any("п/г" in n for n in names)


def test_import_portal_skips_subjects_already_in_catalog(client, monkeypatch):
    admin = make_admin(client)
    snap = _snapshot_with_subgroup_tag(monkeypatch)
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))
    client.post("/web/admin/subjects", json={"name": "Физика"}, headers=admin)

    r = client.post("/web/admin/subjects/import-portal",
                    json={"category": "bakalavriat"}, headers=admin)
    data = r.json()
    assert data["imported"] == 1                  # только «Информатика»
    assert data["skipped"] == 1                    # «Физика» уже была


def test_import_portal_respects_picked_names(client, monkeypatch):
    """Явный отбор (галочки) — импортируем ТОЛЬКО перечисленное, а не весь список."""
    admin = make_admin(client)
    snap = _snapshot_with_subgroup_tag(monkeypatch)
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))

    r = client.post("/web/admin/subjects/import-portal",
                    json={"category": "bakalavriat", "names": ["Физика"]}, headers=admin)
    data = r.json()
    assert data["imported"] == 1
    names = {s["name"] for s in client.get("/web/admin/subjects", headers=admin).json()["subjects"]}
    assert names == {"Физика"}


def test_import_portal_requires_admin(client, monkeypatch):
    admin = make_admin(client)
    headers = make_teacher(client, admin, login="t2")
    snap = _snapshot_with_subgroup_tag(monkeypatch)
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))
    r = client.post("/web/admin/subjects/import-portal",
                    json={"category": "bakalavriat"}, headers=headers)
    assert r.status_code == 403
