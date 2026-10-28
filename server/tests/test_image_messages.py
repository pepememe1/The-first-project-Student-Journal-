# -*- coding: utf-8 -*-
"""
test_image_messages.py — сообщение-изображение (27.10.2026, требование Влада).

«Поделиться» аватаркой беседы: выбрал чат — картинка уходит туда изображением. Аватарка
беседы — data:URL, а вложения-картинки на бою выключены, поэтому завели свой вид
сообщения `image`. Здесь держится:
  • тело — только растровый data:URL (без SVG и мусора) и с потолком размера;
  • в ленте и в списке чатов вместо картинки — подписанная ссылка (`media_refs`, вид «m»):
    иначе сотня килобайт ехала бы в каждом ответе ленты;
  • по ссылке отдаётся сама картинка, а удалённое у всех сообщение — 404;
  • пересылка переносит изображение изображением;
  • в поиск картинка не попадает (её тело — не текст).
Обратный ход проверен: отдать в `_msg_out` сырое тело — краснеет «ссылка вместо
картинки»; убрать проверку `media_refs.decode` — краснеет «без SVG».
"""
import base64
import os
import re

from conftest import make_admin
from test_messenger import _make_student

#Настоящий PNG 1×1: декодер обязан его принять.
PNG = ("data:image/png;base64,"
       "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def _trio(client):
    admin = make_admin(client)
    a_id, a = _make_student(client, admin, "ann", "Анна Аннова")
    b_id, b = _make_student(client, admin, "bob", "Боб Бобов")
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    return conv, a, b, admin, a_id, b_id


def _pair(client):
    conv, a, b, *_rest = _trio(client)
    return conv, a, b


def _send(client, conv, headers, body, kind="image"):
    return client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": body, "kind": kind}, headers=headers)


def test_image_goes_out_as_a_signed_link_and_opens(client):
    conv, a, b = _pair(client)
    r = _send(client, conv, a, PNG)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "image"
    link = r.json()["body"]
    assert link.startswith("/media/avatar?") and "k=m" in link, "в ленту — ссылка, а не картинка"
    hist = client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"]
    assert hist[-1]["body"] == link
    chats = client.get("/web/messenger/chats", headers=b).json()
    rows = chats if isinstance(chats, list) else chats.get("chats", [])
    last = next(c for c in rows if c["conversation_id"] == conv)["last_message"]
    assert "base64" not in last["body"], "в список чатов картинка уезжать не должна"
    got = client.get(link)
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert got.content == base64.b64decode(PNG.split(",", 1)[1])


def test_only_raster_data_url_within_the_limit(client):
    conv, a, _b = _pair(client)
    svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode()
    for bad in (svg, "data:image/png;base64,@@@", "https://evil.example/x.png", "привет",
                "data:image/png;base64," + "A" * 800_000):
        assert _send(client, conv, a, bad).status_code == 400, bad[:40]


def test_deleted_for_all_image_is_gone(client):
    conv, a, _b = _pair(client)
    r = _send(client, conv, a, PNG)
    mid, link = r.json()["id"], r.json()["body"]
    assert client.delete(f"/web/messenger/messages/{mid}", params={"scope": "all"},
                         headers=a).status_code == 200
    assert client.get(link).status_code == 404


def test_forward_keeps_it_an_image(client):
    conv, a, b = _pair(client)
    mid = _send(client, conv, a, PNG).json()["id"]
    saved = client.post("/web/messenger/chats/saved", headers=a).json()["conversation_id"]
    r = client.post("/web/messenger/messages/forward",
                    json={"message_ids": [mid], "to_conversation_ids": [saved]}, headers=a)
    assert r.status_code == 200 and r.json()["forwarded"] == 1, r.text
    last = client.get(f"/web/messenger/chats/{saved}/messages", headers=a).json()["messages"][-1]
    assert last["kind"] == "image" and client.get(last["body"]).status_code == 200


def test_image_is_not_searchable(client):
    conv, a, _b = _pair(client)
    _send(client, conv, a, PNG)
    r = client.get(f"/web/messenger/chats/{conv}/messages/search", params={"q": "iVBOR"},
                   headers=a)
    assert r.status_code == 200 and r.json()["messages"] == []


def test_saved_tab_carries_a_link_not_the_picture(client):
    """Вкладка «Избранное» отдавала тело сообщения как есть — data:URL каждой сохранённой
    картинки целиком (Полковник, 28.10.2026)."""
    conv, a, _b = _pair(client)
    mid = _send(client, conv, a, PNG).json()["id"]
    saved = client.post("/web/messenger/chats/saved", headers=a).json()["conversation_id"]
    client.post("/web/messenger/messages/forward",
                json={"message_ids": [mid], "to_conversation_ids": [saved]}, headers=a)
    #Вкладка беседы-источника: что из неё унесено в «Избранное».
    r = client.get(f"/web/messenger/chats/{conv}/saved", headers=a)
    assert r.status_code == 200, r.text
    items = r.json()["saved"]
    assert items and all("base64" not in (it["body"] or "") for it in items)
    assert items[0]["kind"] == "image" and client.get(items[0]["body"]).status_code == 200


# ── Проверка конфликтов со старыми ручками (28.10.2026) ────────────────────────────────
#Новый вид сообщения встретился с ручками, написанными до него: жалоба, напоминание,
#история правок, окно модератора, вкладка «Медиа». Каждая брала `m.body` как есть.

def _unique_png():
    """data:URL с УНИКАЛЬНЫМ телом: кусок его base64 не может случайно оказаться в ответе,
    и находка этого куска значит, что картинка уехала целиком. Декодер сверяет только
    base64, поэтому достаточно заголовка PNG и случайного хвоста."""
    raw = b"\x89PNG\r\n\x1a\n" + os.urandom(3000)
    body = "data:image/png;base64," + base64.b64encode(raw).decode()
    return body, body[200:260]


def test_report_on_an_image_keeps_a_label_not_the_picture(client):
    conv, a, b, admin, *_ids = _trio(client)
    body, needle = _unique_png()
    mid = _send(client, conv, a, body).json()["id"]
    r = client.post("/web/messenger/reports", json={"message_id": mid, "reason_code": "spam"},
                    headers=b)
    assert r.status_code == 200, r.text
    queue = client.get("/web/admin/messenger/reports", headers=admin)
    assert queue.status_code == 200, queue.text
    assert needle not in queue.text, "в очередь модерации уехала картинка целиком"
    rep = next(x for x in queue.json()["reports"] if x["message_id"] == mid)
    assert rep["message_snapshot"] == "[изображение]"
    from app.db import SessionLocal
    from app.models import MessageReport
    db = SessionLocal()
    try:
        assert db.get(MessageReport, rep["id"]).message_snapshot == "[изображение]", (
            "снимком в базу лёг data:URL — сотни КБ на каждую жалобу")
    finally:
        db.close()


def test_reminder_on_an_image_keeps_a_label(client):
    conv, a, _b = _pair(client)
    body, needle = _unique_png()
    mid = _send(client, conv, a, body).json()["id"]
    r = client.post(f"/web/messenger/messages/{mid}/reminder",
                    json={"when": "2031-01-10T10:00:00"}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["reminder"]["text"] == "[изображение]"
    listed = client.get("/web/messenger/reminders", headers=a)
    assert needle not in listed.text and listed.json()["reminders"][0]["text"] == "[изображение]"


def test_reminder_rows_saved_before_the_fix_read_as_a_label(client):
    """Напоминание на картинку, поставленное кодом 4.1.6 ДО правки, держит data:URL в тексте.
    Подпись обязана стоять и на чтении: в списке напоминаний и в письме о срабатывании
    (нашёл Полковник 28.10.2026 — сторож-свойство создавал напоминание уже после правки).
    Обратный ход (проверен): убрать `text_or_label` из `notify_reminder` — краснеет."""
    conv, a, _b = _pair(client)
    body, needle = _unique_png()
    mid = _send(client, conv, a, body).json()["id"]
    from app.db import SessionLocal
    from app.models import Reminder
    db = SessionLocal()
    try:
        db.add(Reminder(login="ann", conversation_id=conv, message_id=mid, text=body[:1000],
                        remind_at="2020-01-01T00:00:00+00:00",
                        created_at="2020-01-01T00:00:00+00:00", fired_at=""))
        db.commit()
    finally:
        db.close()
    listed = client.get("/web/messenger/reminders", headers=a)
    assert listed.status_code == 200 and needle[:40] not in listed.text
    assert listed.json()["reminders"][0]["text"] == "[изображение]"
    #Срабатывание: напоминание становится письмом во вкладке «Уведомления».
    fired = client.get("/me/events", headers=a)
    assert fired.status_code == 200, fired.text
    assert "[изображение]" in fired.text, "письмо о напоминании не дошло — проверка ослепла"
    assert needle[:40] not in fired.text, "в письмо о напоминании ушёл обрывок base64"


def test_history_is_closed_for_deleted_and_hidden_and_shows_an_image_as_a_link(client):
    """`/messages/{mid}/history` брала сообщение мимо границ ленты: любой участник по
    номеру читал текст, удалённый у всех, и прежние правки. Дыра старая, но с 4.1.6
    через неё уезжал бы и data:URL удалённой картинки."""
    conv, a, b = _pair(client)
    mid = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "секрет"},
                      headers=a).json()["id"]
    assert client.patch(f"/web/messenger/messages/{mid}", json={"body": "исправлено"},
                        headers=a).status_code == 200
    seen = client.get(f"/web/messenger/messages/{mid}/history", headers=b)
    assert seen.status_code == 200 and "секрет" in seen.text, "история правок пропала"
    #«Удалить у себя» — только у b; у автора история остаётся.
    assert client.delete(f"/web/messenger/messages/{mid}", params={"scope": "self"},
                         headers=b).status_code == 200
    assert client.get(f"/web/messenger/messages/{mid}/history", headers=b).status_code == 404
    assert client.get(f"/web/messenger/messages/{mid}/history", headers=a).status_code == 200
    #Удалено у всех — не видно никому из участников.
    assert client.delete(f"/web/messenger/messages/{mid}", params={"scope": "all"},
                         headers=a).status_code == 200
    gone = client.get(f"/web/messenger/messages/{mid}/history", headers=a)
    assert gone.status_code == 404 and "секрет" not in gone.text
    #Изображение — ссылкой, как в ленте.
    body, needle = _unique_png()
    img = _send(client, conv, a, body).json()["id"]
    hist = client.get(f"/web/messenger/messages/{img}/history", headers=b)
    assert hist.status_code == 200 and needle not in hist.text
    assert hist.json()["versions"][-1]["body"].startswith("/media/avatar?")


def test_moderator_sees_a_deleted_image_by_its_own_link(client):
    conv, a, b, admin, *_ids = _trio(client)
    body, needle = _unique_png()
    sent = _send(client, conv, a, body).json()
    mid, member_link = sent["id"], sent["body"]
    rid = client.post("/web/messenger/reports", json={"message_id": mid, "reason_code": "spam"},
                      headers=b).json()["report_id"]
    assert client.delete(f"/web/messenger/messages/{mid}", params={"scope": "all"},
                         headers=a).status_code == 200
    view = client.get(f"/web/admin/messenger/conversations/{conv}/messages",
                      params={"report_id": rid}, headers=admin)
    assert view.status_code == 200, view.text
    assert needle not in view.text, "окну модератора ушёл data:URL удалённой картинки"
    row = next(x for x in view.json()["messages"] if x["id"] == mid)
    link = row["body"]
    assert link.startswith("/media/avatar?") and "k=d" in link, link
    got = client.get(link)
    assert got.status_code == 200 and got.content == base64.b64decode(body.split(",", 1)[1])
    #Участникам удалённое по-прежнему не открывается.
    assert client.get(member_link).status_code == 404
    #Подпись вида «d» к виду «m» не подходит: ссылку участника из ссылки модератора не
    #подделать.
    assert client.get(link.replace("k=d", "k=m")).status_code == 404
    #Уборка стёрла тело — ссылка модератора гаснет вместе с ним.
    from app import retention
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        assert retention.blank_deleted_bodies(db, days=0) >= 1
        db.commit()
    finally:
        db.close()
    assert client.get(link).status_code == 404


def test_media_tab_lists_images_by_link(client):
    """Вкладка «Медиа» собирала только гифки и ссылки на видео — присланная картинка в
    неё не попадала вовсе."""
    conv, a, b = _pair(client)
    body, needle = _unique_png()
    mid = _send(client, conv, a, body).json()["id"]
    r = client.get(f"/web/messenger/chats/{conv}/media", headers=b)
    assert r.status_code == 200 and needle not in r.text
    item = next(x for x in r.json()["media"] if x["message_id"] == mid)
    assert item["kind"] == "image" and client.get(item["url"]).status_code == 200


def test_no_messenger_answer_carries_the_picture_itself(client):
    """СВОЙСТВО, а не список ручек: тело изображения уходит наружу только подписанной
    ссылкой (§4.47). Обходим КАЖДУЮ GET-ручку мессенджера и модерации — автором, вторым
    участником и модератором — и ищем в ответе кусок base64 картинки. Новая ручка,
    отдавшая тело мимо `_msg_out`, покраснеет здесь сама, без дописывания в список.
    Обратный ход (проверен): вернуть в `message_history` сырое `m.body` — краснеет."""
    from test_messenger_routes import _routes
    conv, a, b, admin, a_id, _b_id = _trio(client)
    body, needle = _unique_png()
    mid = _send(client, conv, a, body).json()["id"]
    #Вокруг картинки — всё, что старые ручки умеют с сообщением: ответ, закреп, реакция,
    #напоминание, жалоба, пересылка в «Избранное», вторая картинка — удалённая у всех.
    client.post(f"/web/messenger/chats/{conv}/messages",
                json={"body": "ответ на картинку", "reply_to_id": mid}, headers=b)
    client.post(f"/web/messenger/messages/{mid}/pin", headers=b)
    client.post(f"/web/messenger/messages/{mid}/reactions", json={"emoji": "👍"}, headers=b)
    client.post(f"/web/messenger/messages/{mid}/reminder",
                json={"when": "2031-01-10T10:00:00"}, headers=b)
    rid = client.post("/web/messenger/reports", json={"message_id": mid, "reason_code": "spam"},
                      headers=b).json()["report_id"]
    saved = client.post("/web/messenger/chats/saved", headers=a).json()["conversation_id"]
    client.post("/web/messenger/messages/forward",
                json={"message_ids": [mid], "to_conversation_ids": [saved]}, headers=a)
    gone = _send(client, conv, a, body).json()["id"]
    client.delete(f"/web/messenger/messages/{gone}", params={"scope": "all"}, headers=a)

    values = {"conv_id": conv, "mid": str(mid), "message_id": str(mid), "report_id": str(rid),
              "uid": a_id, "user_id": a_id}
    query = {"q": "iVBOR", "report_id": str(rid), "status": ""}
    paths = sorted({p for m, p in _routes()
                    if m == "GET" and p.startswith(("/web/messenger", "/web/admin/messenger"))})
    assert len(paths) > 40, "обход маршрутов сломан — сторож проверял бы пустоту"
    answered, leaked = 0, []
    for path in paths:
        names = re.findall(r"\{([^}:]+)(?::[^}]*)?\}", path)
        if any(n not in values for n in names):
            continue                        #id активности, файла, доски — не про картинку
        url = re.sub(r"\{([^}:]+)(?::[^}]*)?\}", lambda m: values[m.group(1)], path)
        for who in (a, b, admin):
            r = client.get(url, params=query, headers=who)
            if r.status_code == 200:
                answered += 1
            if needle in r.text:
                leaked.append(f"{url} ({r.status_code})")
    for chat in (conv, saved):
        r = client.get(f"/web/messenger/chats/{chat}/messages", headers=a)
        assert needle not in r.text, chat
    assert not leaked, "тело изображения ушло наружу мимо подписанной ссылки: " + ", ".join(leaked)
    assert answered >= 40, f"ответили только {answered} — обход не дошёл до ручек"
