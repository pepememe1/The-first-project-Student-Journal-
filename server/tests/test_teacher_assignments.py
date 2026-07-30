"""
test_teacher_assignments.py — §ролей: явное назначение преподаватель↔предмет↔группа.

Баг 3.3.1: препод с 5 предметами (A,B,C,D,E), которые встречаются у 3 групп, видел в
журнале/статистике ВСЕ ЭТИ ГРУППЫ, а не только реально назначенные ему — webdata.
teacher_groups() строил список объединением «моё занятие есть» ∪ «мой предмет числится
у группы», без привязки конкретного препода к конкретной группе. Теперь единственный
источник правды — SubjectHours.teacher_id (webdata.teacher_assignments), назначается
через POST /web/admin/group-hours (payload.teachers), тот же редактор, где и часы.
"""
from conftest import make_admin, make_teacher, assign_teacher


def _push_lesson(client, admin, group, subject, lesson_id="L1"):
    r = client.post("/sync/push", json={"changes": {"lessons": [
        {"id": lesson_id, "group_name": group, "subject": subject, "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    assert r.status_code == 200, r.text


def test_teacher_with_many_subjects_sees_no_groups_without_assignment(client):
    """5 предметов, ни одного назначения — 0 групп, а не «все группы этих предметов»."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["A", "B", "C", "D", "E"])
    for i, subj in enumerate(["A", "B", "C", "D", "E"]):
        _push_lesson(client, admin, f"G{i}", subj, lesson_id=f"L{i}")

    data = client.get("/web/teacher/overview", headers=th).json()
    assert data["groups"] == [] and data["subjects"] == [] and data["assignments"] == []


def test_assignment_shows_exactly_that_pair_not_other_groups_with_same_subject(client):
    """Тот же предмет встречается у ДВУХ групп — назначена только ОДНА, видна только она."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    _push_lesson(client, admin, "G1", "Математика", "L1")
    _push_lesson(client, admin, "G2", "Математика", "L2")   # тот же предмет, ЧУЖАЯ группа
    assign_teacher(client, admin, "teach:teacher1", "G1", "Математика")

    data = client.get("/web/teacher/overview", headers=th).json()
    assert data["groups"] == ["G1"]
    assert data["assignments"] == [{"group": "G1", "subject": "Математика"}]

    ok = client.get("/web/teacher/journal", params={"group": "G1", "subject": "Математика"},
                    headers=th)
    assert ok.status_code == 200, ok.text
    forbidden = client.get("/web/teacher/journal",
                           params={"group": "G2", "subject": "Математика"}, headers=th)
    assert forbidden.status_code == 403, "чужая группа с тем же предметом — не видна"


def test_teacher_can_teach_different_subjects_to_different_groups(client):
    """Ведёт математику у 74/1 и информатику у 74/2 — каждая группа со СВОИМ предметом."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика", "Информатика"])
    _push_lesson(client, admin, "74/1", "Математика", "L1")
    _push_lesson(client, admin, "74/2", "Информатика", "L2")
    assign_teacher(client, admin, "teach:teacher1", "74/1", "Математика")
    assign_teacher(client, admin, "teach:teacher1", "74/2", "Информатика")

    assert client.get("/web/teacher/journal", params={"group": "74/1", "subject": "Математика"},
                      headers=th).status_code == 200
    assert client.get("/web/teacher/journal", params={"group": "74/2", "subject": "Информатика"},
                      headers=th).status_code == 200
    #Перекрёстно — НЕ назначено, должно быть 403.
    assert client.get("/web/teacher/journal", params={"group": "74/1", "subject": "Информатика"},
                      headers=th).status_code == 403
    assert client.get("/web/teacher/journal", params={"group": "74/2", "subject": "Математика"},
                      headers=th).status_code == 403


def test_journal_without_assignment_is_403_not_empty(client):
    """Раньше — пустой журнал («у группы нет оценок»), выглядело как баг. Теперь честный 403."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    _push_lesson(client, admin, "G1", "Математика")
    r = client.get("/web/teacher/journal", params={"group": "G1", "subject": "Математика"},
                   headers=th)
    assert r.status_code == 403


def test_sync_pull_without_assignment_brings_no_groups_or_lessons(client):
    """Офлайн-утечка (десктоп): без назначения /sync/pull не привозит ничего лишнего."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    client.post("/sync/push", json={"changes": {
        "groups": [{"id": "grp:G1", "name": "G1", "subjects": ["Математика"]}]}},
        headers=admin)
    _push_lesson(client, admin, "G1", "Математика")

    ch = client.get("/sync/pull", headers=th).json()["changes"]
    assert ch["groups"] == [] and ch["lessons"] == []

    assign_teacher(client, admin, "teach:teacher1", "G1", "Математика")
    ch2 = client.get("/sync/pull", headers=th).json()["changes"]
    assert any(g["name"] == "G1" for g in ch2["groups"])
    assert any(l["id"] == "L1" for l in ch2["lessons"])


def test_group_hours_get_reports_teacher_assignment(client):
    """GET /web/admin/group-hours отдаёт назначенного препода вместе с часами."""
    admin = make_admin(client)
    make_teacher(client, admin, subjects=["Математика"])
    client.post("/web/admin/groups", json={"name": "G1", "subjects": ["Математика"]},
                headers=admin)
    assign_teacher(client, admin, "teach:teacher1", "G1", "Математика")

    r = client.get("/web/admin/group-hours?group=G1", headers=admin)
    assert r.status_code == 200, r.text
    row = next(s for s in r.json()["subjects"] if s["subject"] == "Математика")
    assert row["teacher_id"] == "teach:teacher1"
    assert row["teacher_name"] == "Преподаватель"


def test_group_hours_rejects_teacher_without_that_subject(client):
    """Нельзя назначить препода на предмет, которого у него нет в профиле — 400."""
    admin = make_admin(client)
    make_teacher(client, admin, subjects=["Физика"])   # НЕ Математика
    r = client.post("/web/admin/group-hours",
                    json={"group": "G1", "teachers": {"Математика": "teach:teacher1"}},
                    headers=admin)
    assert r.status_code == 400, r.text


def test_group_hours_rejects_unknown_teacher_id(client):
    admin = make_admin(client)
    r = client.post("/web/admin/group-hours",
                    json={"group": "G1", "teachers": {"Математика": "teach:nobody"}},
                    headers=admin)
    assert r.status_code == 404, r.text


def test_unassign_teacher_by_empty_id(client):
    """Пустая строка снимает назначение (тот же приём, что «0 часов = план снят»)."""
    admin = make_admin(client)
    make_teacher(client, admin, subjects=["Математика"])
    client.post("/web/admin/groups", json={"name": "G1", "subjects": ["Математика"]},
               headers=admin)
    assign_teacher(client, admin, "teach:teacher1", "G1", "Математика")
    r = client.post("/web/admin/group-hours",
                    json={"group": "G1", "teachers": {"Математика": ""}}, headers=admin)
    assert r.status_code == 200, r.text
    row = next(s for s in client.get("/web/admin/group-hours?group=G1", headers=admin)
              .json()["subjects"] if s["subject"] == "Математика")
    assert row["teacher_id"] == "" and row["teacher_name"] == ""


def test_only_admin_can_assign_teacher(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    r = client.post("/web/admin/group-hours",
                    json={"group": "G1", "teachers": {"Математика": "teach:teacher1"}},
                    headers=th)
    assert r.status_code == 403
