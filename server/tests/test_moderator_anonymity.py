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


# ── «О беседе», лента группы и трекер (находка 17.10.2026, M02; починено 21.10.2026) ──
#Подпись «Модератор №N» стояла и здесь, но рядом уходили настоящий id, аватарка и группа,
#а строка «вступил/вышел» навсегда записывала в ленту фамилию.
#Обратный ход (проверен): убрать ветку `aliases` в `conversation_info` — краснеет
#`test_conversation_info_shows_the_moderator_by_number_only`; вернуть `user.id, name`
#в «вышел» у `remove_member` — `test_owner_removes_the_moderator_by_alias…`; убрать
#псевдоним из `_members`/`_task_out` трекера — `test_tracker_shows_the_moderator_by_number_only`.

def _real_id(login=SECRET_LOGIN):
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        return db.query(User.id).filter(User.login == login).scalar()
    finally:
        db.close()


def _group_with_moderator(client):
    """Преподаватель зовёт модератора в группу ПСЕВДОНИМОМ — другого id он не знает."""
    from conftest import make_teacher
    admin, bob, _mod, conv = _ticket_with_moderator_reply(client)
    alias = next(m for m in _bob_messages(client, bob, conv)
                 if m["body"] == "Здравствуйте, разберёмся")["sender_id"]
    teacher = make_teacher(client, admin, login="tgroup")
    r = client.post("/web/messenger/chats/group", headers=teacher,
                    json={"title": "Курсовой проект", "member_ids": [alias, "stud:bob"]})
    assert r.status_code == 200, r.text
    return admin, teacher, bob, alias, r.json()["conversation_id"]


def _leaks(payload) -> list:
    dump = json.dumps(payload, ensure_ascii=False)
    return [s for s in (SECRET_LOGIN, SECRET_NAME, _real_id()) if s and s in dump]


def test_conversation_info_shows_the_moderator_by_number_only(client):
    admin, _teacher, bob, alias, gid = _group_with_moderator(client)
    info = client.get(f"/web/messenger/chats/{gid}", headers=bob).json()
    row = next(p for p in info["participants"] if p.get("masked"))
    assert row["user_id"] == alias and row["full_name"].startswith("Модератор №")
    assert row["avatar"] == "" and row["group_name"] == "" and row["bio"] == ""
    assert _leaks(info) == [], "личность модератора ушла в «О беседе»"
    #Администратор видит человека, как и в карточке профиля.
    staff = client.get(f"/web/messenger/chats/{gid}", headers=admin)
    if staff.status_code == 200:      #админ может и не быть участником — тогда 403
        assert SECRET_NAME in json.dumps(staff.json(), ensure_ascii=False)


def test_owner_removes_the_moderator_by_alias_and_the_feed_keeps_the_number(client):
    _admin, teacher, bob, alias, gid = _group_with_moderator(client)
    r = client.delete(f"/web/messenger/chats/{gid}/members/{alias}", headers=teacher)
    assert r.status_code == 200, r.text
    info = client.get(f"/web/messenger/chats/{gid}", headers=bob).json()
    assert not any(p.get("masked") for p in info["participants"]), "модератор не исключён"
    feed = client.get(f"/web/messenger/chats/{gid}/messages", headers=bob).json()["messages"]
    left = [m for m in feed if m.get("kind") == "system" and "user_left" in m["body"]]
    assert left, "строки «вышел» нет"
    assert _leaks(feed) == [], "лента записала фамилию модератора навсегда"


def test_media_tab_shows_the_moderator_by_number_only(client):
    """Вкладка «Медиа» отдавала сырой `sender_id`: картинка или гифка модератора в группе
    раскрывала его, хотя лента прячет его за номером (gb-review 28.10.2026). Обратный ход
    (проверен): убрать подмену `_sender_aliases` в `chat_media` — краснеет."""
    _admin, _teacher, bob, alias, gid = _group_with_moderator(client)
    r = client.post("/auth/login", json={"login": SECRET_LOGIN, "password": "moderpass1"})
    mod = {"Authorization": "Bearer " + r.json()["access_token"]}
    png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42"
           "mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    sent = client.post(f"/web/messenger/chats/{gid}/messages",
                       json={"body": png, "kind": "image"}, headers=mod)
    assert sent.status_code == 200, sent.text
    media = client.get(f"/web/messenger/chats/{gid}/media", headers=bob)
    assert media.status_code == 200, media.text
    item = next(x for x in media.json()["media"] if x["message_id"] == sent.json()["id"])
    assert item["sender_id"] == alias, "во вкладке «Медиа» — настоящий id модератора"
    assert _leaks(media.json()) == [], "личность модератора ушла во вкладку «Медиа»"


def test_tracker_shows_the_moderator_by_number_only(client):
    _admin, teacher, bob, alias, gid = _group_with_moderator(client)
    url = f"/web/messenger/chats/{gid}/tracker"
    assert client.put(url + "/settings", headers=teacher,
                      json={"enabled": True}).status_code == 200
    import uuid
    pid, tid = "trkp:" + uuid.uuid4().hex, "trkt:" + uuid.uuid4().hex
    res = client.post(url + "/save", headers=teacher, json={"ops": [
        {"op": "project.create", "id": pid, "title": "Курсовая"}]}).json()
    todo = next(c["id"] for p in res["state"]["projects"] if p["id"] == pid
                for c in p["columns"] if c["kind"] == "todo")
    res = client.post(url + "/save", headers=teacher, json={"ops": [
        {"op": "task.create", "id": tid, "column_id": todo, "title": "Проверить главу",
         "assignees": [alias]}]}).json()
    assert res["skipped"] == [], res["skipped"]
    state = client.get(url, headers=bob).json()
    assert _task_of(state, tid)["assignees"] == [alias], "назначение по псевдониму не легло"
    assert any(m["user_id"] == alias and m.get("masked") for m in state["members"])
    assert _leaks(state) == [], "личность модератора ушла в трекер"
    details = client.get(f"{url}/tasks/{tid}/details", headers=bob).json()
    assert _leaks(details) == [], "личность модератора ушла в историю задачи"


def _task_of(state, tid):
    return next(t for t in state["tasks"] if t["id"] == tid)


# ── Нашёл Полковник 21.10.2026 после первой починки M02 ──────────────────────────────
#Обратный ход (проверен): вернуть `user_fio(peer)` в заголовок личного чата — краснеет
#`test_direct_chat_with_a_moderator_is_titled_by_number`; вернуть `sender.full_name` в
#снимок пересылки или убрать маску в `chat_saved` — `test_forwarded_moderator_message_…`.

def test_direct_chat_with_a_moderator_is_titled_by_number(client):
    _admin, bob, mod, _conv = _ticket_with_moderator_reply(client)
    r = client.post("/web/messenger/chats/direct/stud:bob", headers=mod)
    assert r.status_code == 200, r.text
    chats = client.get("/web/messenger/chats", headers=bob).json()
    rows = chats["chats"] if isinstance(chats, dict) else chats
    item = next(c for c in rows if c.get("kind") == "direct")
    assert item["title"].startswith("Модератор №"), item["title"]
    #Адрес беседы — тоже: он виден в ссылке и в адресной строке.
    assert _leaks(item) == [], "личность модератора в списке чатов или в адресе беседы"


# ── id личного чата (остаток M02, закрыт 21.10.2026) ─────────────────────────────────
#Обратный ход (проверен): собрать id из `user.id, peer.id` — краснеют оба первых теста;
#убрать второго кандидата в `_ensure_direct` — `…started_before_the_fix…`; убрать
#`_unalias` в `open_direct` — `…same_from_both_sides`.

def test_direct_chat_id_is_the_same_from_both_sides(client):
    """Беседа одна, с какой стороны её ни открой; студент открывает по псевдониму —
    другого id модератора он не знает."""
    _admin, bob, mod, conv = _ticket_with_moderator_reply(client)
    alias = next(m for m in _bob_messages(client, bob, conv)
                 if m["body"] == "Здравствуйте, разберёмся")["sender_id"]
    from_mod = client.post("/web/messenger/chats/direct/stud:bob", headers=mod).json()
    from_bob = client.post(f"/web/messenger/chats/direct/{alias}", headers=bob)
    assert from_bob.status_code == 200, from_bob.text
    assert from_bob.json()["conversation_id"] == from_mod["conversation_id"]
    assert alias in from_mod["conversation_id"], from_mod["conversation_id"]
    assert _leaks(from_bob.json()) == [], "личность модератора в ответе на открытие чата"


def test_an_ordinary_pair_keeps_the_old_chat_id(client):
    """Без модератора id прежний: на бою 44 личных чата, и новая формула не имеет права
    завести им двойников (замечание Полковника 21.10.2026)."""
    from conftest import make_teacher
    from app.models import direct_conversation_id
    admin = make_admin(client)
    _sid, bob = _student(client, admin)
    teacher = make_teacher(client, admin, login="tpair")
    r = client.post("/web/messenger/chats/direct/stud:bob", headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["conversation_id"] == direct_conversation_id(_real_id("tpair"), "stud:bob")


def test_a_direct_chat_started_before_the_fix_is_not_split(client):
    """Беседа по прежней формуле (из настоящих id) находится, а не заводится вторая рядом.
    На бою таких 21.10.2026 не было — это страховка на случай, когда роль модератора дали
    человеку, который уже переписывался."""
    from app.db import SessionLocal
    from app.models import Conversation, ConversationParticipant, direct_conversation_id
    _admin, _bob, mod, _conv = _ticket_with_moderator_reply(client)
    real = _real_id()
    legacy = direct_conversation_id(real, "stud:bob")
    db = SessionLocal()
    try:
        db.add(Conversation(id=legacy, kind="direct", created_at="2026-10-01 00:00:00"))
        for uid in (real, "stud:bob"):
            db.add(ConversationParticipant(conversation_id=legacy, user_id=uid,
                                           role="member", joined_at="2026-10-01 00:00:00"))
        db.commit()
    finally:
        db.close()
    r = client.post("/web/messenger/chats/direct/stud:bob", headers=mod)
    assert r.status_code == 200, r.text
    assert r.json()["conversation_id"] == legacy, "у пары завелась вторая переписка"


def test_forwarded_moderator_message_keeps_the_number(client):
    _admin, bob, _mod, conv = _ticket_with_moderator_reply(client)
    reply = next(m for m in _bob_messages(client, bob, conv)
                 if m["body"] == "Здравствуйте, разберёмся")
    saved = client.post("/web/messenger/chats/saved", headers=bob).json()["conversation_id"]
    r = client.post("/web/messenger/messages/forward", headers=bob,
                    json={"message_ids": [reply["id"]], "to_conversation_ids": [saved]})
    assert r.status_code == 200, r.text
    #Подпись «Переслано от …» в самом сообщении — снимок, который живёт вечно.
    fwd = _bob_messages(client, bob, saved)
    assert fwd and all(SECRET_NAME not in json.dumps(m, ensure_ascii=False) for m in fwd)
    assert any((m.get("forwarded_from") or "").startswith("Модератор №") for m in fwd)
    #Вкладка «Избранное» исходной беседы.
    tab = client.get(f"/web/messenger/chats/{conv}/saved", headers=bob).json()["saved"]
    assert tab and tab[0]["from_id"].startswith("moderator:")
    assert _leaks(tab) == [], "личность модератора ушла во вкладку «Избранное»"
