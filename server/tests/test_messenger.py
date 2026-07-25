"""
test_messenger.py — ядро мессенджера, Фаза 1 (личные чаты).

Проверяем: открытие direct-чата идемпотентно; отправка/история; серверную метку времени;
роль-скоуп (не-участник не читает/не пишет → 403); список чатов с непрочитанными; опрос
новых по ?after=; отметку прочтения; связь ответа reply_to_id.
"""
from conftest import make_admin, make_teacher
from app.security import hash_password


def _make_student(client, admin_headers, login, name="Студент"):
    """Завести студента (через push админа) и вернуть (id, headers)."""
    uid = f"stud:{login}"
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": uid, "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": name,
        "group_name": "К-24",
    }]}}, headers=admin_headers)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert r.status_code == 200, r.text
    return uid, {"Authorization": f"Bearer {r.json()['access_token']}"}


def _setup(client):
    """admin + преподаватель A + студенты B и C."""
    admin = make_admin(client)
    a = make_teacher(client, admin)                      # id teach:teacher1
    b_id, b = _make_student(client, admin, "bob", "Боб Бобов")
    c_id, c = _make_student(client, admin, "carol", "Кэрол Кэрова")
    return admin, ("teach:teacher1", a), (b_id, b), (c_id, c)


# ── Открытие личного чата ────────────────────────────────────────────────────────────
def test_open_direct_is_idempotent(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    r1 = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a)
    assert r1.status_code == 200, r1.text
    conv = r1.json()["conversation_id"]
    assert r1.json()["peer"]["full_name"] == "Боб Бобов"
    #Повторный вызов (и с ДРУГОЙ стороны) — та же беседа, без дублей.
    r2 = client.post(f"/web/messenger/chats/direct/{a_id}", headers=b)
    assert r2.status_code == 200 and r2.json()["conversation_id"] == conv


def test_open_direct_rejects_self_and_missing(client):
    _, (a_id, a), _, _ = _setup(client)
    assert client.post(f"/web/messenger/chats/direct/{a_id}", headers=a).status_code == 400
    assert client.post("/web/messenger/chats/direct/stud:nobody", headers=a).status_code == 404


# ── Отправка и история ───────────────────────────────────────────────────────────────
def test_send_and_history_server_timestamp(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": "Привет, Боб!"}, headers=a)
    assert r.status_code == 200, r.text
    msg = r.json()
    assert msg["body"] == "Привет, Боб!" and msg["sender_id"] == a_id
    assert msg["created_at"], "сервер обязан проставить метку времени"
    #Собеседник видит сообщение в истории.
    hist = client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"]
    assert [m["body"] for m in hist] == ["Привет, Боб!"]


def test_empty_message_rejected(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "   "}, headers=a).status_code == 400


# ── Роль-скоуп: не-участник не имеет доступа ─────────────────────────────────────────
def test_outsider_cannot_read_or_write(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "секрет"}, headers=a)
    #C не участник этого чата.
    assert client.get(f"/web/messenger/chats/{conv}/messages", headers=c).status_code == 403
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "влезаю"}, headers=c).status_code == 403


# ── Список чатов и непрочитанные ─────────────────────────────────────────────────────
def test_chat_list_unread_and_read(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "раз"}, headers=a)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "два"}, headers=a)

    #У Боба два непрочитанных; заголовок = имя собеседника (A).
    chats_b = client.get("/web/messenger/chats", headers=b).json()["chats"]
    assert len(chats_b) == 1
    assert chats_b[0]["unread"] == 2
    assert chats_b[0]["last_message"]["body"] == "два"

    #Отправитель свои же сообщения непрочитанными не считает.
    chats_a = client.get("/web/messenger/chats", headers=a).json()["chats"]
    assert chats_a[0]["unread"] == 0

    #Боб прочитал — непрочитанных ноль.
    client.post(f"/web/messenger/chats/{conv}/read", json={}, headers=b)
    chats_b = client.get("/web/messenger/chats", headers=b).json()["chats"]
    assert chats_b[0]["unread"] == 0


# ── Опрос новых по ?after= ───────────────────────────────────────────────────────────
def test_poll_after_returns_only_new(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    m1 = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "первое"}, headers=a).json()
    #after=0 → всё; after=m1 → только новое.
    got = client.get(f"/web/messenger/chats/{conv}/messages?after=0", headers=b).json()["messages"]
    assert [m["id"] for m in got] == [m1["id"]]
    m2 = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "второе"}, headers=a).json()
    got = client.get(f"/web/messenger/chats/{conv}/messages?after={m1['id']}", headers=b).json()["messages"]
    assert [m["body"] for m in got] == ["второе"] and got[0]["id"] == m2["id"]


# ── Каталог/поиск людей и профиль ────────────────────────────────────────────────────
def test_directory_search_role_and_safe_fields(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    #Студенты — Боб и Кэрол (себя и преподавателя в списке нет).
    r = client.get("/web/messenger/users?role=student", headers=a).json()
    ids = {u["id"] for u in r["users"]}
    assert ids == {b_id, c_id}
    #Поиск по ФИО (кириллица, регистронезависимо).
    r = client.get("/web/messenger/users?role=student&q=боб", headers=a).json()
    assert [u["id"] for u in r["users"]] == [b_id]
    #Вкладка преподавателей.
    r = client.get("/web/messenger/users?role=teacher", headers=b).json()
    assert a_id in {u["id"] for u in r["users"]}
    #Безопасные поля: НИКАКИХ логина/хэша/почты (§9).
    u = client.get("/web/messenger/users?role=student", headers=a).json()["users"][0]
    for leak in ("login", "password_hash", "email", "prefs"):
        assert leak not in u, f"каталог не должен отдавать {leak}"


def test_profile_safe_fields(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    p = client.get(f"/web/messenger/users/{b_id}/profile", headers=a).json()["profile"]
    assert p["full_name"] == "Боб Бобов" and p["group_name"] == "К-24"
    assert "password_hash" not in p and "login" not in p


def test_mine_flag(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "моё"}, headers=a)
    assert client.get(f"/web/messenger/chats/{conv}/messages", headers=a).json()["messages"][0]["mine"] is True
    assert client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"][0]["mine"] is False


# ── Ответ на сообщение ───────────────────────────────────────────────────────────────
def test_reply_links_valid_message_only(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    base = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "вопрос"}, headers=a).json()
    #Валидный ответ — связь сохраняется.
    rep = client.post(f"/web/messenger/chats/{conv}/messages",
                      json={"body": "ответ", "reply_to_id": base["id"]}, headers=b).json()
    assert rep["reply_to_id"] == base["id"]
    #Ответ на сообщение из ДРУГОЙ беседы — связь отбрасывается (reply_to = None).
    conv2 = client.post(f"/web/messenger/chats/direct/{c_id}", headers=a).json()["conversation_id"]
    rep2 = client.post(f"/web/messenger/chats/{conv2}/messages",
                       json={"body": "чужой ответ", "reply_to_id": base["id"]}, headers=a).json()
    assert rep2["reply_to_id"] is None


# ── Фаза 3: действия над сообщением ──────────────────────────────────────────────────
def _conv(client, headers, peer_id):
    return client.post(f"/web/messenger/chats/direct/{peer_id}", headers=headers).json()["conversation_id"]


def test_delete_self_hides_only_for_me(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    mid = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "текст"}, headers=a).json()["id"]
    #Боб скрывает у себя — у него сообщение исчезает, у А остаётся.
    assert client.delete(f"/web/messenger/messages/{mid}?scope=self", headers=b).status_code == 200
    assert client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"] == []
    assert len(client.get(f"/web/messenger/chats/{conv}/messages", headers=a).json()["messages"]) == 1


def test_delete_all_author_only_in_direct(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    mid = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "секрет"}, headers=a).json()["id"]
    #Боб (не автор, обычный участник) не может удалить у всех.
    assert client.delete(f"/web/messenger/messages/{mid}?scope=all", headers=b).status_code == 403
    #Автор может — сообщение становится тумбстоуном у обоих.
    assert client.delete(f"/web/messenger/messages/{mid}?scope=all", headers=a).status_code == 200
    got = client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"][0]
    assert got["deleted"] is True and got["body"] == ""


def test_pin_unpin_and_list(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    mid = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "важное"}, headers=a).json()["id"]
    #В личном чате закреплять может любой участник.
    assert client.post(f"/web/messenger/messages/{mid}/pin", headers=b).json()["pinned"] is True
    pinned = client.get(f"/web/messenger/chats/{conv}/pinned", headers=a).json()["pinned"]
    assert [p["id"] for p in pinned] == [mid]
    #Открепить.
    assert client.delete(f"/web/messenger/messages/{mid}/pin", headers=a).status_code == 200
    assert client.get(f"/web/messenger/chats/{conv}/pinned", headers=a).json()["pinned"] == []


def test_forward_carries_source_snapshot(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv_ab = _conv(client, a, b_id)
    conv_ac = _conv(client, a, c_id)
    mid = client.post(f"/web/messenger/chats/{conv_ab}/messages", json={"body": "перешлю"}, headers=a).json()["id"]
    r = client.post("/web/messenger/messages/forward",
                    json={"message_ids": [mid], "to_conversation_ids": [conv_ac]}, headers=a)
    assert r.status_code == 200 and r.json()["forwarded"] == 1
    fwd = client.get(f"/web/messenger/chats/{conv_ac}/messages", headers=a).json()["messages"][-1]
    assert fwd["body"] == "перешлю" and fwd["forwarded_from"] == "Преподаватель"


def test_forward_skips_unauthorized_target(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv_ab = _conv(client, a, b_id)
    mid = client.post(f"/web/messenger/chats/{conv_ab}/messages", json={"body": "x"}, headers=a).json()["id"]
    #C пытается переслать в чат A-B, где он не участник → 0 переслано.
    conv_ac = _conv(client, a, c_id)
    r = client.post("/web/messenger/messages/forward",
                    json={"message_ids": [mid], "to_conversation_ids": [conv_ab]}, headers=c)
    assert r.json()["forwarded"] == 0


def test_report_creates_ticket_with_snapshot(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    mid = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "плохое слово"}, headers=a).json()["id"]
    #На своё жаловаться нельзя.
    assert client.post("/web/messenger/reports",
                       json={"message_id": mid, "reason_code": "spam"}, headers=a).status_code == 400
    #Боб жалуется — тикет создаётся.
    r = client.post("/web/messenger/reports",
                    json={"message_id": mid, "reason_code": "harassment", "description": "оскорбляет"}, headers=b)
    assert r.status_code == 200 and r.json()["report_id"]
    #Снимок текста сохранён даже после удаления сообщения у всех.
    from app.db import SessionLocal
    from app.models import MessageReport
    db = SessionLocal()
    try:
        rep = db.query(MessageReport).first()
        assert rep.message_snapshot == "плохое слово" and rep.reason_code == "harassment"
        assert rep.reported_user_id == a_id and rep.status == "open"
    finally:
        db.close()


def test_edit_own_message_only(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    mid = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "опечтка"}, headers=a).json()["id"]
    r = client.patch(f"/web/messenger/messages/{mid}", json={"body": "опечатка"}, headers=a)
    assert r.status_code == 200 and r.json()["body"] == "опечатка" and r.json()["edited_at"]
    #Чужое править нельзя.
    assert client.patch(f"/web/messenger/messages/{mid}", json={"body": "взлом"}, headers=b).status_code == 403


# ── Фаза 4: модерация ────────────────────────────────────────────────────────────────
def test_moderation_chat_user_and_admin_reply(client):
    admin, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.get("/web/messenger/moderation", headers=b).json()["conversation_id"]
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "помогите"}, headers=b)
    #Админ читает беседу и отвечает.
    msgs = client.get(f"/web/admin/messenger/conversations/{conv}/messages", headers=admin).json()["messages"]
    assert [x["body"] for x in msgs] == ["помогите"]
    assert client.post(f"/web/admin/messenger/conversations/{conv}/reply",
                       json={"body": "разберёмся"}, headers=admin).status_code == 200
    #Пользователь видит ответ модерации в своём чате.
    msgs = client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"]
    assert [x["body"] for x in msgs] == ["помогите", "разберёмся"]


def test_report_queue_and_resolve(client):
    admin, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    mid = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "грубость"}, headers=a).json()["id"]
    rid = client.post("/web/messenger/reports",
                      json={"message_id": mid, "reason_code": "harassment"}, headers=b).json()["report_id"]
    q = client.get("/web/admin/messenger/reports?status=open", headers=admin).json()["reports"]
    assert any(t["id"] == rid and t["message_snapshot"] == "грубость"
               and t["reported_name"] == "Преподаватель" for t in q)
    assert client.post(f"/web/admin/messenger/reports/{rid}/resolve",
                       json={"status": "resolved", "resolution_note": "предупреждение"},
                       headers=admin).status_code == 200
    left = client.get("/web/admin/messenger/reports?status=open", headers=admin).json()["reports"]
    assert all(t["id"] != rid for t in left)


def test_moderation_requires_admin(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    assert client.get("/web/admin/messenger/reports", headers=a).status_code == 403
    assert client.get("/web/admin/messenger/reports", headers=b).status_code == 403


def test_moderation_view_writes_audit(client):
    admin, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "x"}, headers=a)
    client.get(f"/web/admin/messenger/conversations/{conv}/messages", headers=admin)
    from app.db import SessionLocal
    from app.models import AuditEvent
    db = SessionLocal()
    try:
        n = (db.query(AuditEvent)
             .filter(AuditEvent.action == "msg.moderation.view", AuditEvent.target == conv).count())
        assert n >= 1, "просмотр переписки модерацией обязан писаться в аудит"
    finally:
        db.close()


# ── Фазы 5–6: группы и каналы ────────────────────────────────────────────────────────
def test_create_group_send_and_names(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = client.post("/web/messenger/chats/group",
                       json={"title": "Проект", "member_ids": [b_id, c_id]}, headers=a).json()["conversation_id"]
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "привет всем"}, headers=a)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "ответ"}, headers=b)
    msgs = client.get(f"/web/messenger/chats/{conv}/messages", headers=c).json()["messages"]
    assert [m["body"] for m in msgs] == ["привет всем", "ответ"]
    assert msgs[0]["sender_name"] == "Преподаватель"        # автор виден в группе
    info = client.get(f"/web/messenger/chats/{conv}", headers=b).json()
    assert info["kind"] == "group" and info["my_role"] == "member" and info["subscribers"] == 3


def test_group_member_management_permissions(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = client.post("/web/messenger/chats/group",
                       json={"title": "Г", "member_ids": [b_id]}, headers=a).json()["conversation_id"]
    #Обычный участник не может добавлять.
    assert client.post(f"/web/messenger/chats/{conv}/members",
                       json={"user_ids": [c_id]}, headers=b).status_code == 403
    #Владелец добавляет и назначает b админом.
    assert client.post(f"/web/messenger/chats/{conv}/members",
                       json={"user_ids": [c_id]}, headers=a).json()["added"] == 1
    assert client.post(f"/web/messenger/chats/{conv}/members/{b_id}/role",
                       json={"role": "admin"}, headers=a).status_code == 200
    #Теперь b (админ) может убрать c.
    assert client.delete(f"/web/messenger/chats/{conv}/members/{c_id}", headers=b).status_code == 200
    assert client.get(f"/web/messenger/chats/{conv}/messages", headers=c).status_code == 403
    #b покидает группу сам.
    assert client.post(f"/web/messenger/chats/{conv}/leave", headers=b).status_code == 200


def test_channel_reader_cannot_post_writer_can(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = client.post("/web/messenger/chats/channel",
                       json={"title": "Новости", "is_public": True, "writer_ids": [b_id]},
                       headers=a).json()["conversation_id"]
    assert client.post(f"/web/messenger/chats/{conv}/join", headers=c).status_code == 200
    #Читатель не пишет, писатель и владелец — пишут.
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "я читатель"}, headers=c).status_code == 403
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "пост"}, headers=b).status_code == 200
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "от owner"}, headers=a).status_code == 200
    #Канал появился в списке чатов читателя.
    chats = client.get("/web/messenger/chats", headers=c).json()["chats"]
    assert any(x["conversation_id"] == conv for x in chats)


def test_public_channel_catalog_and_join(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post("/web/messenger/chats/channel",
                       json={"title": "Объявления", "is_public": True}, headers=a).json()["conversation_id"]
    cat = client.get("/web/messenger/channels", headers=b).json()["channels"]
    row = [c for c in cat if c["conversation_id"] == conv][0]
    assert row["title"] == "Объявления" and row["joined"] is False
    client.post(f"/web/messenger/chats/{conv}/join", headers=b)
    cat = client.get("/web/messenger/channels", headers=b).json()["channels"]
    assert [c for c in cat if c["conversation_id"] == conv][0]["joined"] is True


# ── Фаза 7: presence + WebSocket ─────────────────────────────────────────────────────
def test_presence_online_flag(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    #Боб делает авторизованный запрос → отмечается онлайн (get_current_user → events.touch).
    client.get("/web/messenger/chats", headers=b)
    users = client.get("/web/messenger/users?role=student", headers=a).json()["users"]
    bob = [u for u in users if u["id"] == b_id][0]
    assert bob["online"] is True


def test_ws_connect_with_valid_token(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    token = a["Authorization"].split(" ", 1)[1]
    #Валидный токен → соединение открывается; typing не роняет сервер.
    with client.websocket_connect(f"/web/messenger/ws?token={token}") as wsconn:
        wsconn.send_json({"type": "typing", "conversation_id": "nope"})
    #Контекст закрылся без исключений — соединение жило.


def test_ws_connect_with_subprotocol(client):
    """Токен через Sec-WebSocket-Protocol (['bearer', <jwt>]) — не светит в URL/логах."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    token = a["Authorization"].split(" ", 1)[1]
    with client.websocket_connect("/web/messenger/ws",
                                  subprotocols=["bearer", token]) as wsconn:
        wsconn.send_json({"type": "typing", "conversation_id": "nope"})


def test_ws_rejects_bad_subprotocol_token(client):
    """Мусорный токен в сабпротоколе → соединение отклоняется (не открывается)."""
    import pytest
    from starlette.websockets import WebSocketDisconnect
    _setup(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/web/messenger/ws",
                                      subprotocols=["bearer", "not-a-jwt"]):
            pass


# ── Защита от злоупотребления: анти-флуд, мьют, гейт создания, границы модерации ──────
def test_flood_limit_blocks_burst(client):
    """Всплеск отправки упирается в 429 (анти-флуд). Живой темп в порог не бьётся, автомат —
    бьётся. Первые сообщения проходят, дальше сервер просит не частить."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    codes = []
    for i in range(15):
        codes.append(client.post(f"/web/messenger/chats/{conv}/messages",
                                 json={"body": f"m{i}"}, headers=a).status_code)
    assert 200 in codes and 429 in codes, codes
    #429 приходит именно ПОСЛЕ пачки успешных, а не сразу.
    assert codes[0] == 200 and codes[-1] == 429


def test_global_mute_blocks_send_and_create(client):
    """Замьюченный модерацией не может ни писать, ни создавать беседы; снятие мьюта — снова может."""
    admin, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    #Мьютим преподавателя A глобально.
    r = client.post(f"/web/admin/messenger/users/{a_id}/mute", json={"muted": True}, headers=admin)
    assert r.status_code == 200 and r.json()["muted"] is True
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "нельзя"}, headers=a).status_code == 403
    assert client.post("/web/messenger/chats/group",
                       json={"title": "Х"}, headers=a).status_code == 403
    #Снимаем мьют — запись снова доступна.
    client.post(f"/web/admin/messenger/users/{a_id}/mute", json={"muted": False}, headers=admin)
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "снова можно"}, headers=a).status_code == 200


def test_mute_requires_admin_and_not_admin_target(client):
    """Мьютить может только админ; замьютить администратора нельзя."""
    admin, (a_id, a), (b_id, b), _ = _setup(client)
    #Преподаватель не может мьютить (require_admin → 403).
    assert client.post(f"/web/admin/messenger/users/{b_id}/mute",
                       json={"muted": True}, headers=a).status_code == 403
    #Замьютить администратора нельзя (модераторы не глушат друг друга) → 400.
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        admin_uid = db.query(User).filter(User.role == "admin").first().id
    finally:
        db.close()
    assert client.post(f"/web/admin/messenger/users/{admin_uid}/mute",
                       json={"muted": True}, headers=admin).status_code == 400


def test_muted_user_flag_visible_to_admin_only(client):
    """Флаг мьюта видит модерация (в жалобе), но каталог рядовому пользователю его не «зажигает»."""
    admin, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    mid = client.post(f"/web/messenger/chats/{conv}/messages",
                      json={"body": "грубо"}, headers=a).json()["id"]
    client.post("/web/messenger/reports",
                json={"message_id": mid, "reason_code": "harassment"}, headers=b)
    client.post(f"/web/admin/messenger/users/{a_id}/mute", json={"muted": True}, headers=admin)
    rep = client.get("/web/admin/messenger/reports?status=open", headers=admin).json()["reports"][0]
    assert rep["reported"]["muted"] is True
    #В обычном каталоге муты чужого аккаунта всегда False (не палим модерационное состояние).
    cat = client.get("/web/messenger/users?role=teacher", headers=b).json()["users"]
    assert all(u["muted"] is False for u in cat)


def test_only_teachers_create_groups_and_channels(client):
    """Группы и каналы создаёт только преподаватель/админ; студент — 403 (личные чаты ему ок)."""
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    assert client.post("/web/messenger/chats/group",
                       json={"title": "Студгруппа"}, headers=b).status_code == 403
    assert client.post("/web/messenger/chats/channel",
                       json={"title": "Студканал"}, headers=b).status_code == 403
    assert client.post("/web/messenger/chats/group",
                       json={"title": "Проект", "member_ids": [b_id]}, headers=a).status_code == 200
    #Студент всё ещё может открыть личный чат.
    assert client.post(f"/web/messenger/chats/direct/{c_id}", headers=b).status_code == 200


def test_mod_reply_only_into_moderation_chat(client):
    """Ответ модерации разрешён только в чат обращений (kind='moderation'), не в чужой личный."""
    admin, (a_id, a), (b_id, b), _ = _setup(client)
    direct = _conv(client, a, b_id)
    #В приватный 1-на-1 чужих людей админ вписать сообщение НЕ может.
    assert client.post(f"/web/admin/messenger/conversations/{direct}/reply",
                       json={"body": "влезаю в личку"}, headers=admin).status_code == 403
    #А в официальный чат обращений — может.
    mod = client.get("/web/messenger/moderation", headers=b).json()["conversation_id"]
    assert client.post(f"/web/admin/messenger/conversations/{mod}/reply",
                       json={"body": "ответ поддержки"}, headers=admin).status_code == 200


def test_delete_conversation_hides_only_for_me(client):
    """Удаление переписки — ЛИЧНОЕ действие: у меня чат исчезает вместе с историей,
    у собеседника остаётся целиком."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "старое"}, headers=a)
    assert client.delete(f"/web/messenger/chats/{conv}", headers=b).status_code == 200
    #У Боба чата нет и история пуста…
    assert all(c["conversation_id"] != conv for c in
               client.get("/web/messenger/chats", headers=b).json()["chats"])
    assert client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"] == []
    #…а у собеседника всё на месте.
    assert [m["body"] for m in
            client.get(f"/web/messenger/chats/{conv}/messages", headers=a).json()["messages"]] == ["старое"]


def test_deleted_conversation_returns_on_new_message(client):
    """Новое сообщение возвращает удалённый чат, но СТАРУЮ историю не воскрешает."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "до удаления"}, headers=a)
    client.delete(f"/web/messenger/chats/{conv}", headers=b)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "после"}, headers=a)
    chats = client.get("/web/messenger/chats", headers=b).json()["chats"]
    row = [c for c in chats if c["conversation_id"] == conv]
    assert row and row[0]["last_message"]["body"] == "после"
    got = [m["body"] for m in
           client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"]]
    assert got == ["после"], "старая история не должна возвращаться"


def test_clear_history_keeps_chat_in_list(client):
    """clear_only=1 — история скрыта, но сам чат остаётся в списке."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "текст"}, headers=a)
    assert client.delete(f"/web/messenger/chats/{conv}?clear_only=true",
                         headers=b).json()["cleared"] is True
    assert client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"] == []
    assert any(c["conversation_id"] == conv
               for c in client.get("/web/messenger/chats", headers=b).json()["chats"])


def test_delete_group_chat_also_leaves(client):
    """Удаление группы у себя = выход из неё: доступ к беседе пропадает."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post("/web/messenger/chats/group",
                       json={"title": "Проект", "member_ids": [b_id]}, headers=a).json()["conversation_id"]
    assert client.delete(f"/web/messenger/chats/{conv}", headers=b).status_code == 200
    assert client.get(f"/web/messenger/chats/{conv}/messages", headers=b).status_code == 403


def test_admin_deletes_any_message_with_audit(client):
    """Модерация удаляет ЛЮБОЕ сообщение у всех (даже в чужой личке) — с записью в аудит."""
    admin, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    mid = client.post(f"/web/messenger/chats/{conv}/messages",
                      json={"body": "нарушение"}, headers=a).json()["id"]
    assert client.delete(f"/web/admin/messenger/messages/{mid}", headers=admin).status_code == 200
    got = client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"][0]
    assert got["deleted"] is True and got["body"] == ""
    #Не-админу такой эндпоинт закрыт.
    assert client.delete(f"/web/admin/messenger/messages/{mid}", headers=b).status_code == 403
    from app.db import SessionLocal
    from app.models import AuditEvent
    db = SessionLocal()
    try:
        assert db.query(AuditEvent).filter(AuditEvent.action == "msg.moderation.delete").count() >= 1
    finally:
        db.close()


def test_public_profile_fields_are_clamped_and_shared(client):
    """«О себе» режется по лимиту на СЕРВЕРЕ (клиента можно обойти) и виден другим."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    client.post("/me/prefs", json={"bio": "x" * 900, "profile_color": "violet"}, headers=a)
    card = client.get(f"/web/messenger/users/{a_id}/profile", headers=b).json()["profile"]
    assert len(card["bio"]) == 400 and card["profile_color"] == "violet"


def test_conversation_info_lists_owner_first_with_avatars(client):
    """Инфо о беседе: владелец первым, у карточек есть поля для аватарки и контекста."""
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = client.post("/web/messenger/chats/group",
                       json={"title": "Г", "member_ids": [b_id, c_id]}, headers=a).json()["conversation_id"]
    info = client.get(f"/web/messenger/chats/{conv}", headers=b).json()
    assert info["owner_id"] == a_id
    people = info["participants"]
    assert people[0]["user_id"] == a_id and people[0]["role"] == "owner"
    for p in people:
        assert "avatar" in p and "user_role" in p


def test_mute_conversation_endpoint_and_push_suppression(client, monkeypatch):
    """Мьют беседы у себя: флаг отражается в списке чатов и глушит пуш по этой беседе."""
    import app.rustore_push as rp
    calls = []
    monkeypatch.setattr(rp, "notify_login",
                        lambda db, login, title, body, data=None: calls.append(login) or 1)
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    #Боб мьютит беседу — флаг виден в его списке чатов.
    assert client.post(f"/web/messenger/chats/{conv}/mute",
                       json={"muted": True}, headers=b).json()["muted"] is True
    row = [x for x in client.get("/web/messenger/chats", headers=b).json()["chats"]
           if x["conversation_id"] == conv][0]
    assert row["muted"] is True
    #Гасим presence Боба (мьют-запрос отметил его онлайн) и шлём — пуш не должен уйти из-за мьюта.
    from app import events
    events.reset()
    calls.clear()
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "тук-тук"}, headers=a)
    assert "bob" not in calls


# ── Фаза 8: пуш офлайн-получателю ────────────────────────────────────────────────────
def test_push_to_offline_recipient(client, monkeypatch):
    import app.rustore_push as rp
    calls = []
    monkeypatch.setattr(rp, "notify_login",
                        lambda db, login, title, body, data=None: calls.append(login) or 1)
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    #Боб офлайн (не делал авторизованных запросов) → пуш уходит.
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "привет"}, headers=a)
    assert "bob" in calls


def test_no_push_to_online_recipient(client, monkeypatch):
    import app.rustore_push as rp
    calls = []
    monkeypatch.setattr(rp, "notify_login",
                        lambda db, login, title, body, data=None: calls.append(login) or 1)
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = _conv(client, a, b_id)
    client.get("/web/messenger/chats", headers=b)   #Боб онлайн
    calls.clear()
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "привет"}, headers=a)
    assert "bob" not in calls
