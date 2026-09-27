"""
test_moderation_limits.py — очереди модерации не теряют старое и срочное, история не
грузится целиком, жалобы не множатся (аудит 22.09.2026, находки F-11, F-12, F-13).

  • F-11: очередь обращений резалась LIMIT'ом до сортировки по срочности, беседы —
    по дате создания до сортировки по последнему сообщению. Старое срочное обращение и
    давняя беседа с новым сообщением выпадали из выборки, а экран выглядел полным.
  • F-12: история беседы для модератора поднималась `.all()` целиком вместе с правками.
  • F-13: каждая жалоба — новый тикет со снимком до 400 КБ; ни дедупликации, ни лимита.

Обратный ход (проверен): вернуть `q.limit(...)` без `order_by` — краснеет
`test_old_urgent_ticket_survives_the_queue_limit`; убрать поиск открытой жалобы —
краснеет `test_repeated_report_returns_the_same_ticket`.
"""
from app.security import hash_password

from conftest import make_admin


def _student(client, admin, login):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:" + login, "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": f"Студент {login}",
        "surname": "Студент", "name": login, "group_name": "К-24"}]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    return "stud:" + login, {"Authorization": "Bearer " + r.json()["access_token"]}


def _tickets(n_normal: int):
    """Одно СТАРОЕ срочное обращение и n свежих обычных — прямо в базе (быстро)."""
    from app.db import SessionLocal
    from app.models import SupportTicket
    db = SessionLocal()
    try:
        db.add(SupportTicket(conversation_id="mod:old", user_id="stud:old", category="human",
                             urgent=True, status="open", created_at="2020-01-01T00:00:00+00:00"))
        for i in range(n_normal):
            db.add(SupportTicket(conversation_id=f"mod:n{i}", user_id=f"stud:n{i}",
                                 category="other", urgent=False, status="open",
                                 created_at=f"2026-09-25T10:{i // 60:02d}:{i % 60:02d}+00:00"))
        db.commit()
    finally:
        db.close()


def test_old_urgent_ticket_survives_the_queue_limit(client, monkeypatch):
    from app.routers.messenger import moderation
    monkeypatch.setattr(moderation, "_QUEUE_LIMIT", 5)
    admin = make_admin(client)
    _tickets(12)
    r = client.get("/web/admin/messenger/support", headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tickets"][0]["conversation_id"] == "mod:old", (
        "старое срочное обращение выпало из обрезанной очереди")
    assert data["total"] == 13 and data["truncated"] is True, data


def test_history_is_served_in_windows(client):
    admin = make_admin(client)
    _, bob = _student(client, admin, "hist")
    conv = client.get("/web/messenger/moderation", headers=bob).json()["conversation_id"]
    #Прямо в базу: семь сообщений подряд через API упёрлись бы в антифлуд — и правильно.
    from app.db import SessionLocal
    from app.models import Message
    db = SessionLocal()
    try:
        for i in range(7):
            db.add(Message(conversation_id=conv, sender_id="stud:hist", body=f"сообщение {i}",
                           created_at=f"2026-09-25T11:00:{i:02d}+00:00"))
        db.commit()
    finally:
        db.close()
    r = client.get(f"/web/admin/messenger/conversations/{conv}/messages",
                   params={"limit": 3}, headers=admin).json()
    assert len(r["messages"]) == 3 and r["has_more"] is True, r
    assert r["messages"][-1]["body"] == "сообщение 6", "окно обязано быть ПОСЛЕДНИМ"
    older = client.get(f"/web/admin/messenger/conversations/{conv}/messages",
                       params={"limit": 3, "before": r["next_before"]}, headers=admin).json()
    assert older["messages"][-1]["id"] < r["messages"][0]["id"]


def test_repeated_report_returns_the_same_ticket(client):
    admin = make_admin(client)
    _, alice = _student(client, admin, "alice")
    bob_id, _bob = _student(client, admin, "bobby")
    body = {"user_id": bob_id, "reason_code": "spam", "field": "bio"}
    r1 = client.post("/web/messenger/user-reports", json=body, headers=alice).json()
    r2 = client.post("/web/messenger/user-reports", json=body, headers=alice).json()
    assert r1["report_id"] == r2["report_id"] and r2.get("duplicate") is True, (r1, r2)


def test_daily_report_cap(client, monkeypatch):
    from app.routers.messenger import _common
    monkeypatch.setattr(_common, "REPORTS_PER_DAY", 2)
    admin = make_admin(client)
    _, alice = _student(client, admin, "alice2")
    targets = [_student(client, admin, f"t{i}")[0] for i in range(3)]
    codes = [client.post("/web/messenger/user-reports",
                         json={"user_id": t, "reason_code": "spam", "field": "profile"},
                         headers=alice).status_code for t in targets]
    assert codes == [200, 200, 429], codes


def test_report_queues_say_when_they_are_cut(client):
    """Очереди жалоб на сообщения и на профили говорят, что показаны НЕ все (F-11).

    Обе режутся на 300 строк. Раньше признака не было вовсе: модератор, разобрав видимые,
    считал очередь пустой, а старые жалобы так и оставались «новыми» — за краем списка."""
    from app.db import SessionLocal
    from app.models import MessageReport, UserReport
    admin = make_admin(client)
    with SessionLocal() as db:
        for i in range(301):
            db.add(MessageReport(message_id=i + 1, conversation_id="c1",
                                 message_snapshot="x", reporter_id="u1",
                                 reported_user_id="u2", status="open"))
            db.add(UserReport(reported_user_id="u2", reporter_id="u1", field="bio",
                              snapshot="x", status="open"))
        db.commit()
    for path in ("/web/admin/messenger/reports", "/web/admin/messenger/user-reports"):
        data = client.get(path, params={"status": "open"}, headers=admin).json()
        assert len(data["reports"]) == 300, path
        assert data["total"] == 301 and data["truncated"] is True, \
            f"{path}: обрезанная очередь выглядит полной"
