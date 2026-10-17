"""
test_media_refs.py — аватарка ссылкой, а не картинкой внутри JSON (17.10.2026).

Своя аватарка (data:URL 256×256) уезжала целиком в каждом ответе, где есть человек, —
список чатов и «О беседе» перечитываются на каждом тике и сигнале сокета. Клиент,
приславший `X-Gb-Features: avatar-refs`, получает подписанную ссылку `/media/avatar`,
которую можно кэшировать (см. `app/media_refs.py`). Проверяем:
  • старый клиент (без заголовка) получает data:URL, как раньше — его нельзя сломать;
  • ссылка открывается БЕЗ входа (у `<img>` нет заголовка Authorization) и отдаёт ту же
    картинку, что лежит в профиле, с честным сроком кэша и ETag;
  • подделанная подпись, сменённая или снятая картинка, удалённый человек — 404;
  • локальный сервер программы ссылок не выдаёт (`ENABLED = False`).

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: верни в `_common._safe_user` прежнее
`prefs.get("avatar", "")` — краснеют проверки ссылок в каталоге и в списке чатов.
"""
import base64

from conftest import make_admin, make_teacher
from app import media_refs
from app.security import hash_password

FEATURE = {"X-Gb-Features": "avatar-refs"}
RAW = b"\xff\xd8\xff\xe0" + b"gradebook-avatar" * 64
JPEG = "data:image/jpeg;base64," + base64.b64encode(RAW).decode()


def _student(client, admin, login, name):
    uid = f"stud:{login}"
    surname, given = name.split(" ", 1)
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": uid, "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": name,
        "surname": surname, "name": given, "group_name": "К-24",
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert r.status_code == 200, r.text
    return uid, {"Authorization": f"Bearer {r.json()['access_token']}"}


def _with(headers):
    return {**headers, **FEATURE}


def _setup(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    b_id, b = _student(client, admin, "bob", "Бобов Боб")
    r = client.post("/me/prefs", json={"prefs": {"avatar": JPEG}}, headers=b)
    assert r.status_code == 200, r.text
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=teacher).json()["conversation_id"]
    return admin, teacher, (b_id, b), conv


def _peer_avatar(client, headers):
    chats = client.get("/web/messenger/chats", headers=headers).json()["chats"]
    return next(c for c in chats if c["kind"] == "direct")["peer"]["avatar"]


def test_old_client_still_gets_the_picture_inline(client):
    _, teacher, _, _ = _setup(client)
    assert _peer_avatar(client, teacher) == JPEG


def test_new_client_gets_a_short_link_that_opens_without_login(client):
    _, teacher, (b_id, _), _ = _setup(client)
    url = _peer_avatar(client, _with(teacher))
    assert url.startswith("/media/avatar?") and len(url) < 200, url
    r = client.get(url)                              #без Authorization — как у <img>
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == RAW
    assert r.headers["cache-control"] == "private, max-age=86400"
    etag = r.headers["etag"]
    again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 304 and not again.content


def test_every_place_with_a_person_gives_the_link(client):
    _, teacher, (b_id, _), conv = _setup(client)
    h = _with(teacher)
    found = {
        "каталог": next(u for u in client.get("/web/messenger/users?q=Бобов", headers=h).json()["users"]
                        if u["id"] == b_id)["avatar"],
        "профиль": client.get(f"/web/messenger/users/{b_id}/profile", headers=h).json()["profile"]["avatar"],
        "о беседе": next(p for p in client.get(f"/web/messenger/chats/{conv}", headers=h).json()["participants"]
                         if p["user_id"] == b_id)["avatar"],
    }
    for where, value in found.items():
        assert value.startswith("/media/avatar?"), (where, value[:40])


def test_group_picture_is_a_link_too(client):
    _, teacher, (b_id, _), _ = _setup(client)
    r = client.post("/web/messenger/chats/group", json={"title": "Кружок", "member_ids": [b_id]},
                    headers=teacher)
    assert r.status_code == 200, r.text
    gid = r.json()["conversation_id"]
    assert client.patch(f"/web/messenger/chats/{gid}", json={"avatar": JPEG},
                        headers=teacher).status_code == 200
    chats = client.get("/web/messenger/chats", headers=_with(teacher)).json()["chats"]
    url = next(c for c in chats if c["conversation_id"] == gid)["avatar"]
    assert url.startswith("/media/avatar?k=c&"), url
    assert client.get(url).content == RAW


def test_forged_changed_removed_and_deleted_all_give_404(client):
    admin, teacher, (b_id, b), _ = _setup(client)
    url = _peer_avatar(client, _with(teacher))
    forged = url[:-3] + ("AAA" if not url.endswith("AAA") else "BBB")
    assert client.get(forged).status_code == 404
    other = url.replace("i=stud%3Abob", "i=stud%3Acarol")
    assert other != url and client.get(other).status_code == 404

    #Сменил картинку — старая ссылка мертва сразу, новая работает.
    other_pic = "data:image/jpeg;base64," + base64.b64encode(RAW + b"new").decode()
    client.post("/me/prefs", json={"prefs": {"avatar": other_pic}}, headers=b)
    gone = client.get(url)
    assert gone.status_code == 404 and gone.headers["cache-control"] == "no-store"
    fresh = _peer_avatar(client, _with(teacher))
    assert fresh != url and client.get(fresh).status_code == 200

    #Снял картинку — ссылки нет вовсе.
    client.post("/me/prefs", json={"prefs": {"avatar": ""}}, headers=b)
    assert _peer_avatar(client, _with(teacher)) == ""
    assert client.get(fresh).status_code == 404


def test_gif_avatar_stays_a_cdn_link(client):
    _, teacher, (_, b), _ = _setup(client)
    gif = "https://static.klipy.com/ii/abc/def.gif"
    client.post("/me/prefs", json={"prefs": {"avatar": gif}}, headers=b)
    assert _peer_avatar(client, _with(teacher)) == gif


def test_desktop_local_server_never_issues_links(client, monkeypatch):
    _, teacher, _, _ = _setup(client)
    monkeypatch.setattr(media_refs, "ENABLED", False)
    assert _peer_avatar(client, _with(teacher)) == JPEG


def test_unknown_media_path_is_a_real_404_not_the_site():
    from app.main import _is_api_path, _is_private_api_path
    assert _is_api_path("/media/whatever")
    assert not _is_private_api_path("/media/avatar")


def test_signature_does_not_open_another_owner_or_kind():
    url = media_refs.ref_url("u", "stud:bob", JPEG)
    q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
    assert media_refs.verify("u", "stud:bob", q["v"], q["s"])
    assert not media_refs.verify("c", "stud:bob", q["v"], q["s"])
    assert not media_refs.verify("u", "stud:bob2", q["v"], q["s"])
    assert not media_refs.verify("x", "stud:bob", q["v"], q["s"])
