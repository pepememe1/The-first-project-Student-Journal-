"""
test_esstu_import.py — POST /web/admin/groups/import-esstu (+ GET .../esstu/specialties).

esstu_parser (сеть/PDF) ЗАМОКАН — этот файл проверяет ТОЛЬКО то, что делает сам
эндпоинт с результатом парсера: заменяет Group.subjects, upsert'ит SubjectHours
ИМЕННО текущего семестра (часами ЭТОГО семестра, не общим итогом дисциплины за все
курсы), не трогает teacher_id, пополняет каталог Subject, считает курс/семестр
(study_hours.course_and_semester — уже отдельно проверен в tests/test_study_hours.py).
Сам парсер (PDF/HTML сайта ВСГУТУ) — server/tests/test_esstu_parser.py, на реальных
снимках.

⚠️ План-фикстура строится ФУНКЦИЕЙ от вычисленного «текущего семестра», а не
хардкодом номера семестра — иначе тест был бы то зелёным, то красным в зависимости
от того, в каком месяце его запускают (course_and_semester зависит от даты сервера)."""
import study_hours
from app import db as app_db
from app.models import Group
from app.parsers import esstu_parser
from conftest import make_admin, make_teacher, assign_teacher


def _current_term():
    return app_db.default_term()


def _current_semester_for(enrollment_year: int) -> int:
    ty, ts = _current_term()
    _, overall = study_hours.course_and_semester(enrollment_year, ty, ts)
    return overall


def _plan_for(enrollment_year: int) -> list:
    """Один предмет ИМЕННО текущего семестра (38ч) + один вечно «безсеместровый»
    (сетка не откалибровалась для него) — детерминированно для любой даты запуска."""
    target = _current_semester_for(enrollment_year)
    return [
        {"subject": "Русский язык", "index": "ОУП.01", "hours": 90.0, "zet": 2.5,
         "hours_by_semester": {target: 38.0}},
        {"subject": "Физическая культура", "index": "ЭЛ.01", "hours": 40.0, "zet": 1.11,
         "hours_by_semester": {}},
    ]


def _make_group(client, admin, name="ИС-21", subjects=None):
    r = client.post("/web/admin/groups", json={"name": name, "subjects": subjects or []},
                    headers=admin)
    assert r.status_code == 200, r.text
    return name


def test_specialties_endpoint_admin_only(client, monkeypatch):
    monkeypatch.setattr(esstu_parser, "get_all_specialties",
                        lambda: [{"code": "09.02.07", "name": "ИСиП"}])
    admin = make_admin(client)
    r = client.get("/web/admin/esstu/specialties", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["specialties"] == [{"code": "09.02.07", "name": "ИСиП"}]

    teacher = make_teacher(client, admin)
    assert client.get("/web/admin/esstu/specialties", headers=teacher).status_code == 403


def test_specialties_endpoint_suggests_by_group_name(client, monkeypatch):
    specialties = [{"code": "09.02.07", "name": "ИСиП"}]
    monkeypatch.setattr(esstu_parser, "get_all_specialties", lambda: specialties)
    admin = make_admin(client)
    r = client.get("/web/admin/esstu/specialties", params={"group": "ИС-21"}, headers=admin)
    assert r.json()["suggested_code"] == "09.02.07"
    r2 = client.get("/web/admin/esstu/specialties", params={"group": "К74/1"}, headers=admin)
    assert r2.json()["suggested_code"] == ""


def test_plan_years_endpoint_admin_only(client, monkeypatch):
    monkeypatch.setattr(esstu_parser, "_fetch_plan_years",
                        lambda code: {2022: "/a", 2023: "/b", 2024: "/c"})
    admin = make_admin(client)
    r = client.get("/web/admin/esstu/plan-years", params={"specialty_code": "09.02.07"},
                   headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["years"] == [2024, 2023, 2022]   # новые сверху

    teacher = make_teacher(client, admin)
    assert client.get("/web/admin/esstu/plan-years", params={"specialty_code": "09.02.07"},
                      headers=teacher).status_code == 403


def test_plan_years_endpoint_empty_when_nothing_published(client, monkeypatch):
    #Другой specialty_code, чем в test_plan_years_endpoint_admin_only — у кэша
    #TTL=3ч, ключ по коду, второй тест с ТЕМ ЖЕ кодом в этом же процессе увидел
    #бы уже закэшированный (непустой) результат первого.
    monkeypatch.setattr(esstu_parser, "_fetch_plan_years", lambda code: {})
    admin = make_admin(client)
    r = client.get("/web/admin/esstu/plan-years", params={"specialty_code": "43.02.16"},
                   headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["years"] == []


def test_import_replaces_subjects_and_writes_hours_for_current_semester(client, monkeypatch):
    year = 2022
    plan = _plan_for(year)
    monkeypatch.setattr(esstu_parser, "get_study_plan", lambda code, y: plan)
    admin = make_admin(client)
    _make_group(client, admin, "ИС-21", subjects=["Устаревший предмет"])

    r = client.post("/web/admin/groups/import-esstu",
                    json={"group": "ИС-21", "specialty_code": "09.02.07", "enrollment_year": year},
                    headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["semester"] == _current_semester_for(year)
    assert set(data["imported"]) == {"Русский язык"}
    assert set(data["unmapped"]) == {"Физическая культура"}

    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "ИС-21")
    assert set(grp["subjects"]) == {"Русский язык", "Физическая культура"}
    assert "Устаревший предмет" not in grp["subjects"]

    hours = client.get("/web/admin/group-hours", params={"group": "ИС-21"}, headers=admin).json()
    by_subject = {s["subject"]: s for s in hours["subjects"]}
    #38 (часы ИМЕННО этого семестра), а НЕ 90 (общий итог дисциплины за 4 курса) —
    #ровно та ошибка, которую поймал этот тест в первой версии эндпоинта.
    assert by_subject["Русский язык"]["hours_total"] == 38
    assert by_subject["Русский язык"]["zet"] == study_hours.zet_hint(38)
    #Дисциплина без семестра — предмет ЕСТЬ (Group.subjects), но часов нет вовсе.
    assert by_subject["Физическая культура"]["hours_total"] == 0
    assert by_subject["Физическая культура"]["zet"] is None


def test_import_preserves_existing_teacher_assignment(client, monkeypatch):
    """Импорт правит часы/ЗЕТ, но НЕ трогает «кто ведёт» — это отдельное ручное
    назначение администратора (§ролей), к учебному плану отношения не имеет."""
    year = 2022
    admin = make_admin(client)
    make_teacher(client, admin, subjects=["Русский язык"])
    _make_group(client, admin, "ИС-21", subjects=["Русский язык"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Русский язык")

    monkeypatch.setattr(esstu_parser, "get_study_plan", lambda code, y: _plan_for(year))
    r = client.post("/web/admin/groups/import-esstu",
                    json={"group": "ИС-21", "specialty_code": "09.02.07", "enrollment_year": year},
                    headers=admin)
    assert r.status_code == 200, r.text

    hours = client.get("/web/admin/group-hours", params={"group": "ИС-21"}, headers=admin).json()
    row = next(s for s in hours["subjects"] if s["subject"] == "Русский язык")
    assert row["teacher_id"] == "teach:teacher1"
    assert row["hours_total"] == 38   # часы ВСЁ РАВНО обновились


def test_import_requires_admin(client, monkeypatch):
    monkeypatch.setattr(esstu_parser, "get_study_plan", lambda code, y: _plan_for(2022))
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    _make_group(client, admin, "ИС-21")
    r = client.post("/web/admin/groups/import-esstu",
                    json={"group": "ИС-21", "specialty_code": "09.02.07", "enrollment_year": 2022},
                    headers=teacher)
    assert r.status_code == 403


def test_import_unknown_group_is_404(client, monkeypatch):
    monkeypatch.setattr(esstu_parser, "get_study_plan", lambda code, y: _plan_for(2022))
    admin = make_admin(client)
    r = client.post("/web/admin/groups/import-esstu",
                    json={"group": "Нет такой", "specialty_code": "09.02.07", "enrollment_year": 2022},
                    headers=admin)
    assert r.status_code == 404


def test_import_finds_group_when_id_drifted_from_name(client, monkeypatch):
    """GET /admin/groups отдаёт группы ПО ИМЕНИ (id клиенту не виден вовсе), а сам
    эндпоинт лукапит по РЕКОНСТРУИРОВАННОМУ id (grp:{name}). Если у строки в базе id
    почему-то разошёлся с её же name (старые данные, ручная правка) — группа видна
    в UI по имени, но реконструкция id мимо неё промахивается и раньше 404-ила на
    группе, которая точно есть. Заводим ИМЕННО такую строку напрямую (минуя API,
    который всегда строит id согласованно) и проверяем, что импорт всё равно находит
    группу по name."""
    year = 2022
    monkeypatch.setattr(esstu_parser, "get_study_plan", lambda code, y: _plan_for(year))
    admin = make_admin(client)

    db = app_db.SessionLocal()
    try:
        db.add(Group(id="grp:legacy-id-mismatch", name="К74/1", subjects=[],
                     updated_at="2020-01-01T00:00:00", deleted=False))
        db.commit()
    finally:
        db.close()

    r = client.post("/web/admin/groups/import-esstu",
                    json={"group": "К74/1", "specialty_code": "09.02.07", "enrollment_year": year},
                    headers=admin)
    assert r.status_code == 200, r.text
    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "К74/1")
    assert set(grp["subjects"]) == {"Русский язык", "Физическая культура"}


def test_import_empty_plan_is_422_and_no_side_effects(client, monkeypatch):
    """Сайт недоступен / план не опубликован — 422, группа остаётся КАК БЫЛА (не
    затираем предметы пустым списком)."""
    monkeypatch.setattr(esstu_parser, "get_study_plan", lambda code, y: [])
    admin = make_admin(client)
    _make_group(client, admin, "ИС-21", subjects=["Старый предмет"])
    r = client.post("/web/admin/groups/import-esstu",
                    json={"group": "ИС-21", "specialty_code": "09.02.07", "enrollment_year": 2022},
                    headers=admin)
    assert r.status_code == 422

    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "ИС-21")
    assert grp["subjects"] == ["Старый предмет"]


def test_import_missing_fields_is_400(client):
    admin = make_admin(client)
    _make_group(client, admin, "ИС-21")
    r = client.post("/web/admin/groups/import-esstu", json={"group": "ИС-21"}, headers=admin)
    assert r.status_code == 400


def test_import_seeds_subject_catalog(client, monkeypatch):
    year = 2022
    monkeypatch.setattr(esstu_parser, "get_study_plan", lambda code, y: _plan_for(year))
    admin = make_admin(client)
    _make_group(client, admin, "ИС-21")
    r = client.post("/web/admin/groups/import-esstu",
                    json={"group": "ИС-21", "specialty_code": "09.02.07", "enrollment_year": year},
                    headers=admin)
    assert r.status_code == 200, r.text
    names = {s["name"] for s in client.get("/web/admin/subjects", headers=admin).json()["subjects"]}
    assert {"Русский язык", "Физическая культура"} <= names


def test_import_saves_specialty_and_enrollment_year_and_returns_course(client, monkeypatch):
    year = 2022
    monkeypatch.setattr(esstu_parser, "get_study_plan", lambda code, y: _plan_for(year))
    admin = make_admin(client)
    _make_group(client, admin, "ИС-21")
    r = client.post("/web/admin/groups/import-esstu",
                    json={"group": "ИС-21", "specialty_code": "09.02.07", "enrollment_year": year},
                    headers=admin)
    assert r.status_code == 200, r.text
    ty, ts = _current_term()
    expect_course, expect_overall = study_hours.course_and_semester(year, ty, ts)
    assert r.json()["course"] == expect_course
    assert r.json()["semester"] == expect_overall
