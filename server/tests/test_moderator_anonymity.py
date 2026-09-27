"""
test_moderator_anonymity.py — «Модератор №N» не раскрывается одним запросом (аудит
22.09.2026, находка F-10, P1).

Модератор подписан номером, чтобы получивший ограничение не уносил из чата фамилию того,
кто его выдал (требование Влада, 12.09.2026). Но номер был только ПОДПИСЬЮ: в каждом
сообщении лежал сырой `sender_id`, по нему карточка профиля отдавала ФИО, аватарку и
«О себе», а список чатов подписывал последнее сообщение в группе настоящей фамилией.

Правило: личность модератора видят администратор и модераторы; остальным — номер и
псевдоним-идентификатор `moderator:N`, по которому не восстановить ни логин, ни ФИО.

Обратный ход (проверен): вернуть `"sender_id": m.sender_id` в `_msg_out` — краснеет
`test_user_sees_only_the_number_in_the_ticket`; снять маску в `_safe_user` (одна дверь
карточек на весь мессенджер) — краснеют обе проверки карточки профиля и проверка
«забытый зритель — это маска».
"""
import json

from app.security import hash_password

from conftest import make_admin

SECRET_LOGIN = "ivanova_secret"
SECRET_NAME = "Иванова Тайная"


def _moderator(client, admin):
    r = client.post("/web/admin/moderators",
                    json={"login": SECRET_LOGIN, "password": "moderpass1",
                          "full_name": SECRET_NAME}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": SECRET_LOGIN, "password": "moderpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _student(client, admin, login="bob"):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:" + login, "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": "Боб Бобов",
        "surname": "Боб", "name": "Бобов", "group_name": "К-24"}]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    return "stud:" + login, {"Authorization": "Bearer " + r.json()["access_token"]}


def _ticket_with_moderator_reply(client):
    admin = make_admin(client)
    _, bob = _student(client, admin)
    conv = client.get("/web/messenger/moderation", headers=bob).json()["conversation_id"]
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "позовите живого человека"}, headers=bob).status_code == 200
    mod = _moderator(client, admin)
    r = client.post(f"/web/admin/messenger/conversations/{conv}/reply",
                    json={"body": "Здравствуйте, разберёмся"}, headers=mod)
    assert r.status_code == 200, r.text
    return admin, bob, mod, conv


def _bob_messages(client, bob, conv):
    r = client.get(f"/web/messenger/chats/{conv}/messages", headers=bob)
    assert r.status_code == 200, r.text
    return r.json()["messages"]


def test_user_sees_only_the_number_in_the_ticket(client):
    _admin, bob, _mod, conv = _ticket_with_moderator_reply(client)
    msgs = _bob_messages(client, bob, conv)
    reply = next(m for m in msgs if m["body"] == "Здравствуйте, разберёмся")
    assert reply["sender_id"].startswith("moderator:"), reply["sender_id"]
    assert reply["sender_name"].startswith("Модератор №")
    dump = json.dumps(msgs, ensure_ascii=False)
    assert SECRET_LOGIN not in dump and SECRET_NAME not in dump, "личность ушла в ленту"


def test_profile_by_alias_is_masked_for_the_user(client):
    _admin, bob, _mod, conv = _ticket_with_moderator_reply(client)
    alias = next(m for m in _bob_messages(client, bob, conv)
                 if m["body"] == "Здравствуйте, разберёмся")["sender_id"]
    r = client.get(f"/web/messenger/users/{alias}/profile", headers=bob)
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["profile"]["full_name"].startswith("Модератор №")
    assert card["profile"]["avatar"] == "" and card["profile"]["bio"] == ""
    assert card["achievements"] == []
    assert SECRET_NAME not in json.dumps(card, ensure_ascii=False)


def test_profile_by_real_id_is_masked_for_the_user(client):
    """Даже знающий настоящий id (из старой версии клиента, из логов) карточку не
    получает: маска решается по зрителю, а не по тому, как пришёл запрос."""
    admin, bob, _mod, conv = _ticket_with_moderator_reply(client)
    staff = client.get(f"/web/admin/messenger/conversations/{conv}/messages", headers=admin)
    assert staff.status_code == 200, staff.text
    real_id = next(m for m in staff.json()["messages"]
                   if m["body"] == "Здравствуйте, разберёмся")["sender_id"]
    assert not real_id.startswith("moderator:"), "администратор обязан видеть настоящий id"
    card = client.get(f"/web/messenger/users/{real_id}/profile", headers=bob).json()
    assert SECRET_NAME not in json.dumps(card, ensure_ascii=False)
    assert card["profile"]["id"].startswith("moderator:")
    shared = client.get(f"/web/messenger/users/{real_id}/shared", headers=bob).json()
    assert shared == {"groups": [], "channels": []}


def test_admin_sees_the_person_behind_the_number(client):
    admin, bob, _mod, conv = _ticket_with_moderator_reply(client)
    alias = next(m for m in _bob_messages(client, bob, conv)
                 if m["body"] == "Здравствуйте, разберёмся")["sender_id"]
    card = client.get(f"/web/messenger/users/{alias}/profile", headers=admin).json()
    assert card["profile"]["full_name"] == SECRET_NAME, card


def test_masking_is_the_default_when_the_viewer_is_unknown():
    """Забытый зритель — это маска, а не утечка: безопасная сторона по построению."""
    from app.routers.messenger._common import _masked_for, _safe_user

    class U:
        id, role, mod_number, full_name, name, login = "mod:x", "moderator", 7, "Фамилия", "", "x"
        group_name, birthday, prefs, subjects = "", "", {}, []

    assert _masked_for(U()) is True
    assert _safe_user(U())["id"] == "moderator:7"

    class Admin:
        id, role = "admin:a", "admin"

    assert _safe_user(U(), viewer=Admin())["full_name"] == "Фамилия"
