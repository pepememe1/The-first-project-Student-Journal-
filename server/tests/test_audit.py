"""
test_audit.py — Персистентный журнал аудита (ФСТЭК №21).

Проверяем: значимые действия (вход, неудачный вход, создание/удаление ПДн) ложатся в
БД-журнал; читать его может ТОЛЬКО админ; фильтр по коду действия работает; журнал
переживает пересоздание in-memory монитора (persist), в отличие от /admin/events.
"""
from conftest import make_admin, make_teacher


def test_audit_requires_admin(client):
    h = make_admin(client)
    th = make_teacher(client, h)
    assert client.get("/web/admin/audit", headers=th).status_code == 403
    assert client.get("/web/admin/audit").status_code == 401          # без токена
    assert client.get("/web/admin/audit", headers=h).status_code == 200


def test_login_ok_and_fail_are_recorded(client):
    h = make_admin(client)
    client.post("/auth/login", json={"login": "admin", "password": "adminpass1"})  # ok
    client.post("/auth/login", json={"login": "admin", "password": "nope"})        # fail
    evs = client.get("/web/admin/audit", headers=h).json()["events"]
    actions = [e["action"] for e in evs]
    assert "login.ok" in actions
    assert "login.fail" in actions
    fail = next(e for e in evs if e["action"] == "login.fail")
    assert fail["level"] == "warn" and fail["actor"] == "admin"


def test_student_crud_is_audited_with_filter(client):
    h = make_admin(client)
    client.post("/web/admin/students", headers=h, json={
        "surname": "Иванов", "name": "Иван", "login": "ivanov", "group": "ИС-21",
        "password": "studpass1"})
    client.delete("/web/admin/students/ivanov", headers=h)
    #Фильтр по коду действия отдаёт только нужные записи.
    created = client.get("/web/admin/audit", headers=h,
                         params={"action": "student.create"}).json()["events"]
    assert created and all(e["action"] == "student.create" for e in created)
    assert any(e["target"] == "ivanov" for e in created)
    deleted = client.get("/web/admin/audit", headers=h,
                         params={"action": "student.delete"}).json()["events"]
    assert any(e["target"] == "ivanov" for e in deleted)


def test_audit_survives_monitor_reset(client):
    """Журнал аудита — в БД, поэтому сброс in-memory монитора его не стирает."""
    from app import events as ev
    h = make_admin(client)
    client.post("/auth/login", json={"login": "admin", "password": "adminpass1"})
    ev.reset()                                   # обнуляем ТОЛЬКО живой монитор
    evs = client.get("/web/admin/audit", headers=h).json()["events"]
    assert any(e["action"] == "login.ok" for e in evs), "БД-журнал должен пережить reset"
