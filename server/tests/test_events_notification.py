"""
test_events_notification.py — POST /web/events: мероприятия/события (олимпиады,
конкурсы и т.п.), которые заводит преподаватель или админ и которые уходят выбранной
аудитории уведомлением kind="event" (вкладка «Мероприятия» в NotificationsInbox.vue).

Роль-скоуп — как и везде: админ может широковещательно («все группы») или в конкретные
группы; преподаватель — ТОЛЬКО в свои группы (по предметам, как в журнале), без «все».
"""
import pytest

from conftest import make_admin, make_teacher


@pytest.fixture(autouse=True)
def push_on(monkeypatch):
    """Пуши включены, но сетевой вызов подменяем — проверяем только НАШУ БД (NotifyEvent)."""
    from app import config, rustore_push
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "test-project")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "test-token")
    monkeypatch.setattr(rustore_push, "_post", lambda payload: (True, 200, "{}"))


def _make_student(client, admin, login, group):
    from app.security import hash_password
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": "Студент Тестов",
        "surname": "Тестов", "name": "Студент", "group_name": group,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_teacher_group(client, admin, group="ИС-21", subject="Математика"):
    """Занятие в группе по предмету + явное назначение препода (webdata.teacher_
    assignments) — без назначения препод теперь НЕ увидит группу (§ролей препод↔предмет
    ↔группа, 3.3.1: раньше «предмет числится у препода» ошибочно значило «видны все
    группы предмета»)."""
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L1", "group_name": group, "subject": subject, "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    teach = make_teacher(client, admin, subjects=[subject])  # id детерминирован: teach:teacher1
    r = client.post("/web/admin/groups", json={"name": group, "subjects": [subject]}, headers=admin)
    #Группа могла уже существовать (создана раньше в этом же тесте) — тогда 409, не страшно.
    assert r.status_code in (200, 409), r.text
    r = client.post("/web/admin/group-hours",
                    json={"group": group, "teachers": {subject: "teach:teacher1"}}, headers=admin)
    assert r.status_code == 200, r.text
    return teach


def test_admin_broadcasts_to_all_groups(client):
    admin = make_admin(client)
    _make_student(client, admin, "bob", "К-24")
    sh2 = _make_student(client, admin, "carol", "К-25")

    r = client.post("/web/events", json={
        "title": "Олимпиада по программированию", "body": "Регистрация до пятницы.",
        "groups": []}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "sent": 2, "recipients": 2}

    items = client.get("/me/events", headers=sh2).json()["items"]
    assert len(items) == 1 and items[0]["kind"] == "event"
    assert items[0]["title"] == "Олимпиада по программированию"
    assert "пятницы" in items[0]["body"]


def test_admin_targets_specific_group(client):
    admin = make_admin(client)
    sh_a = _make_student(client, admin, "bob", "К-24")
    sh_b = _make_student(client, admin, "carol", "К-25")

    r = client.post("/web/events", json={
        "title": "Конкурс", "body": "Только для К-24.", "groups": ["К-24"]}, headers=admin)
    assert r.status_code == 200 and r.json()["recipients"] == 1

    assert len(client.get("/me/events", headers=sh_a).json()["items"]) == 1
    assert len(client.get("/me/events", headers=sh_b).json()["items"]) == 0


def test_teacher_can_notify_own_group(client):
    admin = make_admin(client)
    teach = _seed_teacher_group(client, admin, group="ИС-21", subject="Математика")
    sh = _make_student(client, admin, "bob", "ИС-21")

    r = client.post("/web/events", json={
        "title": "Выступление", "body": "Готовим доклад.", "groups": ["ИС-21"]}, headers=teach)
    assert r.status_code == 200, r.text
    assert r.json()["recipients"] == 1
    assert len(client.get("/me/events", headers=sh).json()["items"]) == 1


def test_teacher_cannot_broadcast_to_all(client):
    admin = make_admin(client)
    teach = _seed_teacher_group(client, admin)
    r = client.post("/web/events", json={
        "title": "Т", "body": "Т", "groups": []}, headers=teach)
    assert r.status_code == 400


def test_teacher_cannot_target_foreign_group(client):
    admin = make_admin(client)
    teach = _seed_teacher_group(client, admin, group="ИС-21", subject="Математика")
    r = client.post("/web/events", json={
        "title": "Т", "body": "Т", "groups": ["К-99"]}, headers=teach)
    assert r.status_code == 403


def test_student_forbidden(client):
    admin = make_admin(client)
    sh = _make_student(client, admin, "bob", "К-24")
    r = client.post("/web/events", json={"title": "Т", "body": "Т", "groups": []}, headers=sh)
    assert r.status_code == 403


def test_missing_title_or_body_rejected(client):
    admin = make_admin(client)
    assert client.post("/web/events", json={"title": "", "body": "Т", "groups": []},
                       headers=admin).status_code == 400
    assert client.post("/web/events", json={"title": "Т", "body": "", "groups": []},
                       headers=admin).status_code == 400
