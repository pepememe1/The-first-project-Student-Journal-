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

from conftest import make_admin
from test_messenger import _make_student

#Настоящий PNG 1×1: декодер обязан его принять.
PNG = ("data:image/png;base64,"
       "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def _pair(client):
    admin = make_admin(client)
    a_id, a = _make_student(client, admin, "ann", "Анна Аннова")
    b_id, b = _make_student(client, admin, "bob", "Боб Бобов")
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
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
