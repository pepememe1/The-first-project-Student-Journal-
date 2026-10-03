"""
test_admin_monitor.py — Мониторинг для админки: «кто онлайн» и журнал событий.

Проверяем: доступ строго админский (teacher/student/без токена — отказ), присутствие
отмечается на авторизованном запросе, ключевые события (старт, неудачный вход)
попадают в журнал, дельта-опрос отдаёт только новое.
"""
from conftest import make_admin, make_teacher


def test_online_requires_admin(client):
    h = make_admin(client)
    th = make_teacher(client, h)
    assert client.get("/admin/online", headers=th).status_code == 403
    assert client.get("/admin/events", headers=th).status_code == 403
    assert client.get("/admin/online").status_code == 401          # без токена


def test_online_lists_active_admin(client):
    h = make_admin(client)
    #Сам запрос /admin/online проходит через get_current_user → отмечает присутствие.
    r = client.get("/admin/online", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["window_sec"] == 90
    logins = [u["login"] for u in data["online"]]
    assert "admin" in logins
    me = next(u for u in data["online"] if u["login"] == "admin")
    assert me["role"] == "admin"
    assert me["idle_sec"] >= 0


def test_events_capture_start_and_failed_login(client):
    h = make_admin(client)
    client.post("/auth/login", json={"login": "admin", "password": "wrong"})  # неудача
    r = client.get("/admin/events", headers=h)
    assert r.status_code == 200, r.text
    kinds = [e["kind"] for e in r.json()["events"]]
    assert "server_start" in kinds          # старт сервера залогирован
    assert "login_failed" in kinds          # неудачный вход залогирован


def test_events_delta_returns_only_new(client):
    h = make_admin(client)
    last_id = client.get("/admin/events", headers=h).json()["last_id"]
    client.post("/auth/login", json={"login": "admin", "password": "wrong"})
    new = client.get("/admin/events", headers=h, params={"since": last_id}).json()
    assert new["events"], "должны прийти новые события после since"
    assert all(e["id"] > last_id for e in new["events"])
    assert any(e["kind"] == "login_failed" for e in new["events"])


def test_one_login_is_one_line_in_the_monitor_and_still_in_the_audit(client):
    """🔥 Живой прогон 01.10.2026: каждый вход в мониторе выглядел трижды — «вход
    выполнен» и рядом сырой код «login.ok · login.ok» от журнала аудита. В монитор —
    одна запись человеческими словами; в БД аудита запись остаётся (её читает разбор
    инцидентов и пасхалки входа)."""
    from app.db import SessionLocal
    from app.models import AuditEvent
    h = make_admin(client)
    last_id = client.get("/admin/events", headers=h).json()["last_id"]
    assert client.post("/auth/login", json={"login": "admin", "password": "adminpass1"}
                       ).status_code == 200
    client.post("/auth/login", json={"login": "admin", "password": "wrong"})
    new = client.get("/admin/events", headers=h, params={"since": last_id}).json()["events"]
    kinds = [e["kind"] for e in new]
    assert kinds.count("login") == 1 and kinds.count("login_failed") == 1, kinds
    assert not {"login.ok", "login.fail"} & set(kinds), f"дубль сырым кодом: {kinds}"
    db = SessionLocal()
    try:
        actions = {a for (a,) in db.query(AuditEvent.action).filter(
            AuditEvent.action.in_(("login.ok", "login.fail"))).all()}
    finally:
        db.close()
    assert actions == {"login.ok", "login.fail"}, "вход перестал попадать в журнал аудита"
