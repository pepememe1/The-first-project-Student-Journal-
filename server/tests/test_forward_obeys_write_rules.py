"""
test_forward_obeys_write_rules.py — пересылка подчиняется тем же правилам, что отправка
(аудит 17.10.2026).

━━ ЧТО БЫЛО ━━
`forward_messages` проверяла участие и блокировку лички, а запреты обычной отправки —
нет. Читатель канала публиковал в канал пересылкой, заглушённый в группе (`/mute`)
продолжал писать ею же. Списки не очищались от повторов и ничем не ограничивались, а
счётчик флуда видел запрос одним сообщением: 50 повторов одного id на двух одинаковых
адресатов давали 100 строк при одном вызове ограничителя. Пересланный файл терял
`attachment_id`: отправителю «переслано», у получателя пустая карточка.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть прежний `forward_messages` — краснеют тесты на канал,
заглушку, повторы, пределы, объём и файл.
"""
from conftest import make_admin, make_teacher
from app.security import hash_password


def _student(client, admin, login, name):
    surname, given = name.split(" ", 1)
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": name,
        "surname": surname, "name": given, "group_name": "К-24",
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert r.status_code == 200, r.text
    return f"stud:{login}", {"Authorization": f"Bearer {r.json()['access_token']}"}


def _world(client):
    admin = make_admin(client)
    a = make_teacher(client, admin)
    b_id, b = _student(client, admin, "bob", "Боб Бобов")
    c_id, c = _student(client, admin, "carol", "Кэрол Кэрова")
    return admin, ("teach:teacher1", a), (b_id, b), (c_id, c)


def _direct(client, headers, peer_id):
    r = client.post(f"/web/messenger/chats/direct/{peer_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


def _group(client, owner, member_ids, title="Группа"):
    r = client.post("/web/messenger/chats/group",
                    json={"title": title, "member_ids": member_ids}, headers=owner)
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


def _say(client, headers, conv, body):
    r = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": body},
                    headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _forward(client, headers, mids, targets):
    return client.post("/web/messenger/messages/forward",
                       json={"message_ids": mids, "to_conversation_ids": targets},
                       headers=headers)


def _bodies(client, headers, conv):
    r = client.get(f"/web/messenger/chats/{conv}/messages", headers=headers)
    assert r.status_code == 200, r.text
    return [m["body"] for m in r.json()["messages"] if m.get("kind") != "system"]


def test_channel_reader_cannot_publish_by_forwarding(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _world(client)
    channel = client.post("/web/messenger/chats/channel",
                          json={"title": "Новости", "is_public": True},
                          headers=a).json()["conversation_id"]
    assert client.post(f"/web/messenger/chats/{channel}/join", headers=c).status_code == 200
    #Обычной отправкой читатель не пишет — это давно так.
    assert client.post(f"/web/messenger/chats/{channel}/messages",
                       json={"body": "я читатель"}, headers=c).status_code == 403
    own = _direct(client, c, b_id)
    mid = _say(client, c, own, "реклама в канал")

    r = _forward(client, c, [mid], [channel])
    assert r.status_code == 403, f"читатель опубликовал в канал пересылкой: {r.text}"
    assert "реклама в канал" not in _bodies(client, a, channel)


def test_silenced_member_cannot_write_by_forwarding(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _world(client)
    group = _group(client, a, [b_id, c_id])
    assert client.post(f"/web/messenger/chats/{group}/messages",
                       json={"body": "/mute @Боб"}, headers=a).status_code == 200
    own = _direct(client, b, c_id)
    mid = _say(client, b, own, "всё равно скажу")

    r = _forward(client, b, [mid], [group])
    assert r.status_code == 403, f"заглушённый написал в группу пересылкой: {r.text}"
    assert "всё равно скажу" not in _bodies(client, a, group)


def test_refusal_for_one_target_forwards_nothing_anywhere(client):
    """Отказ по любому адресату отменяет всю пересылку: половина пачки в одних чатах и
    тишина в других хуже честного отказа."""
    _, (a_id, a), (b_id, b), (c_id, c) = _world(client)
    channel = client.post("/web/messenger/chats/channel",
                          json={"title": "Новости", "is_public": True},
                          headers=a).json()["conversation_id"]
    client.post(f"/web/messenger/chats/{channel}/join", headers=c)
    src = _direct(client, c, b_id)
    other = _direct(client, c, a_id)
    mid = _say(client, c, src, "пачка")
    assert _forward(client, c, [mid], [other, channel]).status_code == 403
    assert "пачка" not in _bodies(client, c, other)


def test_repeated_ids_do_not_multiply_messages(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _world(client)
    src = _direct(client, a, b_id)
    dst = _direct(client, a, c_id)
    mid = _say(client, a, src, "одно")

    r = _forward(client, a, [mid] * 50, [dst, dst])
    assert r.status_code == 200, r.text
    assert r.json()["forwarded"] == 1, "повторы id размножили сообщение"
    assert _bodies(client, a, dst).count("одно") == 1


def test_batch_size_is_limited(client, monkeypatch):
    from app.routers.messenger import messages as mod
    _, (a_id, a), (b_id, b), (c_id, c) = _world(client)
    src = _direct(client, a, b_id)
    dst = _direct(client, a, c_id)
    mid = _say(client, a, src, "x")

    too_many_sources = list(range(1, mod._FORWARD_MAX_SOURCES + 2))
    assert _forward(client, a, too_many_sources, [dst]).status_code == 400
    too_many_targets = [f"conv:{i}" for i in range(mod._FORWARD_MAX_TARGETS + 1)]
    assert _forward(client, a, [mid], too_many_targets).status_code == 400

    #Предел на ПРОИЗВЕДЕНИЕ: проверяем правило, а не боевое число (иначе тест заводил бы
    #две сотни бесед ради того же вывода).
    monkeypatch.setattr(mod, "_FORWARD_MAX_TOTAL", 3)
    mid2 = _say(client, a, src, "y")
    dst2 = _group(client, a, [c_id])
    r = _forward(client, a, [mid, mid2], [dst, dst2])
    assert r.status_code == 400, f"пачка 2×2 прошла при пределе 3: {r.text}"
    assert "x" not in _bodies(client, a, dst), "часть пачки всё же легла"


def test_forward_volume_counts_messages_not_requests(client, monkeypatch):
    from app import msg_limit
    _, (a_id, a), (b_id, b), (c_id, c) = _world(client)
    src = _direct(client, a, b_id)
    d1 = _direct(client, a, c_id)
    d2 = _group(client, a, [c_id])
    m1 = _say(client, a, src, "раз")
    m2 = _say(client, a, src, "два")
    monkeypatch.setitem(msg_limit._BUCKETS, "forward", ((60.0, 5),))

    assert _forward(client, a, [m1, m2], [d1, d2]).status_code == 200      #4 сообщения
    r = _forward(client, a, [m1, m2], [d1, d2])                             #ещё 4 — уже 8
    assert r.status_code == 429, f"объём пересылки не учитывается: {r.text}"
    assert "Retry-After" in r.headers


def test_forwarded_file_keeps_the_file_and_recipient_can_open_it(client, monkeypatch):
    from app import storage
    for k, v in (("MODE", "s3"), ("ENDPOINT", "https://s3.example"), ("BUCKET", "gb"),
                 ("ACCESS_KEY", "key"), ("SECRET_KEY", "secret")):
        monkeypatch.setattr(storage, k, v)
    monkeypatch.setattr(storage, "head_object", lambda key: {"size": 100, "mime": "application/pdf"})
    admin, (a_id, a), (b_id, b), (c_id, c) = _world(client)
    d_id, d = _student(client, admin, "dave", "Дейв Дейвов")
    ab = _direct(client, a, b_id)
    ac = _direct(client, a, c_id)
    att = client.post("/web/messenger/uploads/sign", headers=a,
                      json={"conversation_id": ab, "name": "лекция.pdf", "size": 100,
                            "mime": "application/pdf"}).json()["attachment_id"]
    assert client.post(f"/web/messenger/uploads/{att}/done", headers=a).status_code == 200
    mid = client.post(f"/web/messenger/chats/{ab}/messages", headers=a,
                      json={"body": "", "attachment_id": att}).json()["id"]

    assert _forward(client, a, [mid], [ac]).json()["forwarded"] == 1
    got = [m for m in client.get(f"/web/messenger/chats/{ac}/messages", headers=c)
           .json()["messages"] if m.get("kind") == "file"]
    assert got and got[-1]["attachment"] and got[-1]["attachment"]["id"] == att, \
        "пересланное сообщение пришло без файла"

    #Кэрол не участник исходной беседы — открыть файл ей позволяет пересланная копия.
    assert client.get(f"/web/messenger/attachments/{att}/url", headers=c).status_code == 200
    #Посторонний — ни там, ни там.
    assert client.get(f"/web/messenger/attachments/{att}/url", headers=d).status_code == 403
    #Копию удалили у всех — доступ через неё закрылся.
    copy_id = got[-1]["id"]
    assert client.delete(f"/web/messenger/messages/{copy_id}?scope=all", headers=a).status_code == 200
    assert client.get(f"/web/messenger/attachments/{att}/url", headers=c).status_code == 403


def test_muted_user_can_still_forward_evidence_to_moderation(client):
    """Глобальный мьют не закрывает чат с модерацией (§ обжалование) — и пересылкой тоже:
    «вот, разберитесь» без единого слова — законное обращение."""
    admin, (a_id, a), (b_id, b), (c_id, c) = _world(client)
    src = _direct(client, a, b_id)
    mid = _say(client, a, src, "оскорбление")
    r = client.post(f"/web/admin/messenger/users/{b_id}/mute",
                    json={"muted": True, "hours": 3}, headers=admin)
    assert r.status_code == 200, r.text
    mod_chat = client.get("/web/messenger/moderation", headers=b).json()["conversation_id"]
    assert _forward(client, b, [mid], [mod_chat]).status_code == 200
    #А в обычную беседу — нельзя: мьют есть мьют.
    other = _direct(client, b, c_id)
    assert _forward(client, b, [mid], [other]).status_code == 403
