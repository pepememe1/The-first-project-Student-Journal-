"""
test_forward_side_effects.py — пересылка ничего не делает с беседой, куда не попала
(находка ревью M05, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
`forward_messages` отбирает адресатов в первом проходе (чужая беседа, отчёт не от
преподавателя, карточка активности, удалённый источник — всё это пропускается), а
рассылку и хук модерации звал вторым проходом ПО ИСХОДНОМУ СПИСКУ, то есть по тому, что
прислал клиент.

🔥 Цена обходила границу доступа. Достаточно подставить id ЧУЖОГО чата поддержки:
пересылка честно «не удаётся» (`forwarded: 0`), а тикет в нём заводится или обновляется —
с репликой автоответчика и сдвинутой меткой «человек написал». Посторонний двигал чужое
обращение в очереди модерации, ничего в него не отправив; владелец чата видел у себя
разговор, которого не вёл.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть второй проход по `targets` — краснеют первый и второй
тесты. Третий и четвёртый зелены и стерегут от «починки», которая перестала бы
доставлять законную пересылку и заводить по ней тикет.
"""
from app.security import hash_password

from conftest import make_admin


def _student(client, admin, login, surname="Боб"):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:" + login, "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": f"{surname} Бобов",
        "surname": surname, "name": "Бобов", "group_name": "К-24",
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    return "stud:" + login, {"Authorization": "Bearer " + r.json()["access_token"]}


def _moderation_chat(client, headers):
    r = client.get("/web/messenger/moderation", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


def _direct(client, headers, peer_id):
    r = client.post(f"/web/messenger/chats/direct/{peer_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


def _say(client, headers, conv, body):
    r = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": body},
                    headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _tickets(client, admin):
    r = client.get("/web/admin/messenger/support", headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()
    return data.get("tickets", data.get("items", data))


def test_forwarding_into_someone_elses_support_chat_changes_nothing_there(client):
    admin = make_admin(client)
    victim_id, victim = _student(client, admin, "victim", surname="Жертвин")
    _, stranger = _student(client, admin, "stranger", surname="Чужов")

    victim_chat = _moderation_chat(client, victim)      #чат поддержки ЖЕРТВЫ
    before = _tickets(client, admin)

    #Постороннему нужно что-то своё, чтобы было чем «пересылать».
    own = _direct(client, stranger, victim_id)
    mid = _say(client, stranger, own, "своё сообщение")

    r = client.post("/web/messenger/messages/forward", json={
        "message_ids": [mid], "to_conversation_ids": [victim_chat],
    }, headers=stranger)
    assert r.status_code == 200, r.text
    assert r.json().get("forwarded") == 0, "сообщение попало в чужой чат поддержки"

    after = _tickets(client, admin)
    assert len(after) == len(before), \
        "посторонний завёл/обновил обращение в ЧУЖОМ чате поддержки, ничего туда не отправив"

    #И в самой беседе не появилось ни строки — ни пересланной, ни от автоответчика.
    r = client.get(f"/web/messenger/chats/{victim_chat}/messages", headers=victim)
    assert r.status_code == 200, r.text
    assert r.json().get("messages") == [], "в чужом чате поддержки появились сообщения"


def test_a_mixed_batch_only_touches_the_targets_that_took_the_message(client):
    admin = make_admin(client)
    victim_id, victim = _student(client, admin, "victim2", surname="Жертвин")
    _, stranger = _student(client, admin, "stranger2", surname="Чужов")

    victim_chat = _moderation_chat(client, victim)
    own = _direct(client, stranger, victim_id)
    mid = _say(client, stranger, own, "исходное")
    mine = _moderation_chat(client, stranger)           #СВОЙ чат поддержки — сюда можно

    r = client.post("/web/messenger/messages/forward", json={
        "message_ids": [mid], "to_conversation_ids": [victim_chat, mine],
    }, headers=stranger)
    assert r.status_code == 200, r.text
    assert r.json().get("forwarded") == 1, "законный адресат в смешанном списке пропущен"

    r = client.get(f"/web/messenger/chats/{victim_chat}/messages", headers=victim)
    assert r.json().get("messages") == [], "чужой адресат в смешанном списке всё равно затронут"
    r = client.get(f"/web/messenger/chats/{mine}/messages", headers=stranger)
    assert any((m.get("body") or "") == "исходное" for m in r.json().get("messages", [])), \
        "пересылка в свой чат не доехала"


def test_forwarding_into_your_own_support_chat_still_opens_a_ticket(client):
    """Обратная сторона: пересылка «вот, разберитесь» — самый частый способ пожаловаться,
    и тикет по ней обязан заводиться (это починка от 12.09.2026, её нельзя отменить)."""
    admin = make_admin(client)
    peer_id, _peer = _student(client, admin, "peer3", surname="Соседов")
    _, me = _student(client, admin, "me3", surname="Ямов")

    own = _direct(client, me, peer_id)
    mid = _say(client, me, own, "оскорбление")
    mine = _moderation_chat(client, me)
    before = len(_tickets(client, admin))

    r = client.post("/web/messenger/messages/forward", json={
        "message_ids": [mid], "to_conversation_ids": [mine],
    }, headers=me)
    assert r.status_code == 200, r.text
    assert r.json().get("forwarded") == 1
    assert len(_tickets(client, admin)) == before + 1, \
        "пересылка в свой чат модерации перестала заводить обращение"


def test_a_repeated_target_is_handled_once(client):
    """Дубль в списке адресатов не должен давать два прохода хука по одной беседе."""
    admin = make_admin(client)
    peer_id, _peer = _student(client, admin, "peer4", surname="Соседов")
    _, me = _student(client, admin, "me4", surname="Ямов")

    own = _direct(client, me, peer_id)
    mid = _say(client, me, own, "текст")
    mine = _moderation_chat(client, me)
    before = len(_tickets(client, admin))

    r = client.post("/web/messenger/messages/forward", json={
        "message_ids": [mid], "to_conversation_ids": [mine, mine],
    }, headers=me)
    assert r.status_code == 200, r.text
    assert len(_tickets(client, admin)) == before + 1, "дубль адресата завёл второе обращение"
