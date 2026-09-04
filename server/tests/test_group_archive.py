"""
test_group_archive.py — АРХИВ учебных групп: выпустилась, но не удалена.

Живая жалоба Влада (03.09.2026): «начался новый учебный год, набрали новые группы,
другие перешли на новый курс; если раньше группа была, но не перешла на следующий курс —
она идёт в архив, где видно предметы, студентов, закреплённых преподавателей и куратора».

Что здесь держится (и что покраснеет, если правку откатить):
  • кандидат вычисляется СЕГОДНЯ — из расхождения «портал против календаря», а не через
    год, когда накопится история. Ради этого признак и заведён: сентябрь уже наступил;
  • группа, про которую не известно НИЧЕГО, кандидатом НЕ становится. Уберёшь это
    условие — и продукт предложит убрать каждую группу, заведённую руками;
  • архив ПОКАЗЫВАЕТ содержимое, а не прячет: студенты, предметы, преподаватели,
    кураторы на месте. Это отличие от `deleted`, ради которого всё и делалось;
  • дверь наружу есть;
  • архивные исчезают из рабочего списка — иначе архив не значил бы ничего;
  • имя со слэшем («К74/1») проходит все ручки. Рядом с этим дефектом в проекте уже
    жил зелёный тест, который держал удобную «К-24».
"""
from app import schedule_web
from app.db import SessionLocal
from app.models import Group, SubjectHours, User
from app.security import hash_password
from conftest import make_admin


def _portal(monkeypatch, mapping):
    """Индекс портала: {курс: [имена групп]}. Сеть в тестах не трогаем."""
    monkeypatch.setattr(schedule_web, "groups_by_course_cached", lambda category="": mapping)


def _group(client, admin, name, enrollment_year=None, subjects=()):
    payload = {"id": f"grp:{name}", "name": name, "subjects": list(subjects)}
    if enrollment_year is not None:
        payload["enrollment_year"] = enrollment_year
    r = client.post("/sync/push", json={"changes": {"groups": [payload]}}, headers=admin)
    assert r.status_code == 200, r.text


def _student(client, admin, login, group):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": "Иван Иванов",
        "surname": "Иванов", "name": "Иван", "group_name": group,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text


def _cur_year(client, admin):
    r = client.get("/web/admin/term", headers=admin)
    if r.status_code == 200 and isinstance(r.json(), dict) and r.json().get("year"):
        return r.json()["year"]
    from app import webdata as W
    db = SessionLocal()
    try:
        return W.current_term(W.load_config(db))[0]
    finally:
        db.close()


def _candidates(client, admin):
    r = client.get("/web/admin/group-archive", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["candidates"]


# ── кандидаты ───────────────────────────────────────────────────────────────────────

def test_group_that_did_not_advance_is_a_candidate(client, monkeypatch):
    """Календарь ушёл на 3 курс, портал держит группу на 2 — это и есть «не перешла»."""
    admin = make_admin(client)
    start = int(_cur_year(client, admin).split("/")[0])
    _group(client, admin, "К74/1", enrollment_year=start - 2)      # ожидается 3 курс
    _portal(monkeypatch, {2: ["К74/1"]})                           # портал держит 2

    got = _candidates(client, admin)
    assert [c["group"] for c in got] == ["К74/1"], got
    assert got[0]["course"] == 2 and got[0]["expected_course"] == 3
    assert "не перешла" in got[0]["reason"]


def test_group_that_advanced_is_not_a_candidate(client, monkeypatch):
    """Обратный ход: портал догнал календарь — предлагать нечего."""
    admin = make_admin(client)
    start = int(_cur_year(client, admin).split("/")[0])
    _group(client, admin, "К75/1", enrollment_year=start - 2)
    _portal(monkeypatch, {3: ["К75/1"]})

    assert _candidates(client, admin) == []


def test_group_without_any_history_is_never_a_candidate(client, monkeypatch):
    """Ни года поступления, ни свидетельства — «не знаю» это не «выпустилась».

    Без этого условия продукт предложил бы убрать каждую заведённую руками группу.
    """
    admin = make_admin(client)
    _group(client, admin, "К99/9")
    _portal(monkeypatch, {})
    assert _candidates(client, admin) == []


def test_witness_covers_groups_without_enrollment_year(client, monkeypatch):
    """Второй признак: года поступления нет, но есть свидетельство прошлого года."""
    admin = make_admin(client)
    _group(client, admin, "К60/2")
    db = SessionLocal()
    try:
        row = db.get(Group, "grp:К60/2")
        row.last_course, row.last_course_year = 4, "2024/2025"
        db.commit()
    finally:
        db.close()
    _portal(monkeypatch, {4: ["К60/2"]})               # курс не вырос

    got = _candidates(client, admin)
    assert [c["group"] for c in got] == ["К60/2"], got
    assert "был 4" in got[0]["reason"]


def test_listing_candidates_changes_nothing(client, monkeypatch):
    """🔥 Чтение не имеет права стирать основание, по которому группа сюда попала.

    Иначе первый показ давал бы кандидатов, второй — пустоту, и это читалось бы как
    «само починилось».
    """
    admin = make_admin(client)
    start = int(_cur_year(client, admin).split("/")[0])
    _group(client, admin, "К76/1", enrollment_year=start - 2)
    _portal(monkeypatch, {2: ["К76/1"]})

    assert _candidates(client, admin) == _candidates(client, admin)
    assert len(_candidates(client, admin)) == 1


# ── сам архив ───────────────────────────────────────────────────────────────────────

def test_archive_shows_students_subjects_teachers_and_curators(client, monkeypatch):
    """Главное требование: архив ПОКАЗЫВАЕТ содержимое, а не прячет его."""
    admin = make_admin(client)
    _portal(monkeypatch, {})
    _group(client, admin, "К70/1", subjects=["Математика"])
    _student(client, admin, "petrov", "К70/1")

    db = SessionLocal()
    try:
        db.add(User(id="teach:sidorov", role="teacher", login="sidorov",
                    surname="Сидоров", name="Пётр", curated_groups=["К70/1"],
                    updated_at="x", deleted=False))
        db.add(SubjectHours(id="hrs:К70/1|Математика|2025/2026|1", group_name="К70/1",
                            subject="Математика", year="2025/2026", semester=1,
                            hours_total=72, teacher_id="teach:sidorov",
                            updated_at="x", deleted=False))
        db.commit()
    finally:
        db.close()

    r = client.post("/web/admin/groups/archive", headers=admin,
                    json={"group": "К70/1", "reason": "выпустилась"})
    assert r.status_code == 200, r.text

    d = client.get("/web/admin/group-archive/detail", headers=admin,
                   params={"group": "К70/1"}).json()
    assert d["archived"] is True and d["archived_reason"] == "выпустилась"
    assert any(s["subject"] == "Математика" for s in d["subjects"])
    assert d["students"] and d["students"][0]["login"] == "petrov"
    assert "Сидоров" in " ".join(d["curators"])
    assert "Сидоров" in " ".join(d["teachers"])

    # Ничего не удалено: студент на месте.
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.group_name == "К70/1",
                                     User.role == "student").count() == 1
    finally:
        db.close()


def test_archive_has_a_way_back(client, monkeypatch):
    """Дверь наружу: архив по ошибке обязан сниматься без правки базы руками."""
    admin = make_admin(client)
    _portal(monkeypatch, {})
    _group(client, admin, "К71/1")

    client.post("/web/admin/groups/archive", headers=admin, json={"group": "К71/1"})
    r = client.get("/web/admin/group-archive", headers=admin).json()
    assert [g["group"] for g in r["archived"]] == ["К71/1"]

    client.post("/web/admin/groups/archive", headers=admin,
                json={"group": "К71/1", "archived": False})
    r = client.get("/web/admin/group-archive", headers=admin).json()
    assert r["archived"] == []


def test_archived_group_leaves_the_working_list(client, monkeypatch):
    """Архивная исчезает из обычного списка и достаётся только явным флагом.

    Обратный ход на смысл всей задачи: не исчезает — значит выпустившиеся группы
    остались в каждом выпадающем списке, и архив не сделал ничего.
    """
    admin = make_admin(client)
    _portal(monkeypatch, {})
    _group(client, admin, "К72/1")
    _group(client, admin, "К73/1")
    client.post("/web/admin/groups/archive", headers=admin, json={"group": "К73/1"})

    names = [g["name"] for g in
             client.get("/web/admin/groups", headers=admin).json()["groups"]]
    assert names == ["К72/1"], names

    all_names = {g["name"] for g in
                 client.get("/web/admin/groups", headers=admin,
                            params={"include_archived": "true"}).json()["groups"]}
    assert all_names == {"К72/1", "К73/1"}


def test_group_name_with_slash_survives_every_endpoint(client, monkeypatch):
    """⚠️ Имя со слэшем НЕ идёт в путь URL: Starlette раскодирует `%2F` ДО роутинга и
    путь разваливается на лишний сегмент. Проверяем именно «К74/1», а не удобную
    «К-24» — рядом с этим дефектом в проекте уже жил зелёный тест."""
    admin = make_admin(client)
    _portal(monkeypatch, {})
    _group(client, admin, "К74/1")

    r = client.post("/web/admin/groups/archive", headers=admin, json={"group": "К74/1"})
    assert r.status_code == 200 and r.json()["archived"] is True, r.text

    d = client.get("/web/admin/group-archive/detail", headers=admin,
                   params={"group": "К74/1"})
    assert d.status_code == 200, d.text
    assert d.json()["group"] == "К74/1"


def test_witness_is_written_only_on_purpose(client, monkeypatch):
    """Свидетельство ставит ЯВНАЯ ручка, а не чтение списка."""
    admin = make_admin(client)
    _group(client, admin, "К77/1")
    _portal(monkeypatch, {2: ["К77/1"]})

    _candidates(client, admin)                     # чтение не пишет
    db = SessionLocal()
    try:
        assert db.get(Group, "grp:К77/1").last_course is None
    finally:
        db.close()

    r = client.post("/web/admin/groups/archive-witness", headers=admin)
    assert r.status_code == 200 and r.json()["updated"] >= 1, r.text
    db = SessionLocal()
    try:
        assert db.get(Group, "grp:К77/1").last_course == 2
    finally:
        db.close()
