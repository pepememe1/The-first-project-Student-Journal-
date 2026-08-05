"""
test_subject_archive.py — GET /web/admin/group-subject-archive (3.6.1).

Живой запрос: «когда мы парсим предметы с сайта, текущие должны перезаписаться, а
старые улететь в архив, где будут видны в админке — вкладки групп и архивы по датам
и текущего семестра». Строка часов гасится (deleted=True), а не удаляется — архив
показывает и погашенные (active=false), и живые (active=true) записи ТЕКУЩЕГО термина,
плюс отдельные снимки прошлых семестров.
"""
from conftest import make_admin, make_teacher


def test_current_term_shows_active_and_archived_subjects(client):
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "G7", "subjects": ["Физика"]}, headers=admin)
    r = client.post("/web/admin/group-hours",
                    json={"group": "G7", "hours": {"Физика": 40}, "zet": {"Физика": 1.1}},
                    headers=admin)
    assert r.status_code == 200, r.text

    #Реимпорт заменяет план — «Физика» уходит, «Химия» приходит.
    r = client.put("/web/admin/groups/G7", json={"subjects": ["Химия"]}, headers=admin)
    assert r.status_code == 200, r.text

    arc = client.get("/web/admin/group-subject-archive?group=G7", headers=admin).json()
    cur = next(t for t in arc["terms"] if t["is_current"])
    by_name = {s["subject"]: s for s in cur["subjects"]}
    assert by_name["Химия"]["active"] is True
    assert by_name["Физика"]["active"] is False
    #Часы погашенного предмета видны (архив — не потеря данных).
    assert by_name["Физика"]["hours_total"] == 40


def test_past_term_is_its_own_snapshot(client):
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "G8", "subjects": ["Химия"]}, headers=admin)
    r = client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L-old", "group_name": "G8", "subject": "История", "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2020", "year": "2020/2021", "semester": 1}]}},
        headers=admin)
    assert r.status_code == 200, r.text

    arc = client.get("/web/admin/group-subject-archive?group=G8", headers=admin).json()
    years = {(t["year"], t["semester"]) for t in arc["terms"]}
    assert ("2020/2021", 1) in years
    past = next(t for t in arc["terms"] if (t["year"], t["semester"]) == ("2020/2021", 1))
    assert not past["is_current"]
    assert {s["subject"] for s in past["subjects"]} == {"История"}
    assert all(s["active"] for s in past["subjects"])


def test_unknown_group_is_404(client):
    admin = make_admin(client)
    r = client.get("/web/admin/group-subject-archive?group=nope", headers=admin)
    assert r.status_code == 404


def test_teacher_forbidden(client):
    admin = make_admin(client)
    th = make_teacher(client, admin)
    client.post("/web/admin/groups", json={"name": "G9", "subjects": []}, headers=admin)
    r = client.get("/web/admin/group-subject-archive?group=G9", headers=th)
    assert r.status_code == 403
