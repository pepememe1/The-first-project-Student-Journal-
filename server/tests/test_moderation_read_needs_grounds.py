"""
test_moderation_read_needs_grounds.py — чужую переписку модерация открывает только по
основанию (находка ревью M01, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
`report_id` у ручки чтения был НЕОБЯЗАТЕЛЬНЫМ, а `_require_live_ticket` звался только
когда параметр пришёл. То есть замок открывался тем, что его не трогают: убрал параметр
из адреса — и читаешь любую личную переписку колледжа целиком, вместе с удалёнными
сообщениями и всеми прежними редакциями. Правило «по закрытой жалобе переписку не
смотрят» при этом выглядело действующим, было записано в документах и держалось тестом
(`test_closed_ticket_blocks_punishment_on_the_server`) — тест проверял ветку С тикетом и
про обход ничего не знал.

Вторая половина того же дефекта — список бесед: без параметра `kind` он отдавал ВСЕ
беседы, то есть участников поимённо и текст последнего сообщения каждой личной
переписки.

━━ ОСНОВАНИЙ ДВА, И ВТОРОЕ НЕ ЛАЗЕЙКА ━━
Живой тикет на эту беседу — расследование жалобы. Беседа С САМОЙ МОДЕРАЦИЕЙ
(`kind == "moderation"`) — человек писал туда ровно затем, чтобы его прочитали.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть в `moderation.py` прежнее `if report_id:` без ветки
`elif` — краснеет первый тест; вернуть список без фильтра по `kind` — краснеет
четвёртый. Второй и третий остаются зелёными и стерегут от «починки», которая просто
закрыла бы модерации доступ к её собственной работе.
"""
from test_moderation_role import _setup, _direct, _make_user


def test_private_chat_is_not_readable_without_a_ticket(client):
    """Главное: без основания чужая личная переписка не открывается."""
    admin, (_, mod), (b_id, b), (c_id, c) = _setup(client)
    conv = _direct(client, b, c_id)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "личное"}, headers=b)

    r = client.get(f"/web/admin/messenger/conversations/{conv}/messages", headers=mod)
    assert r.status_code == 403, f"переписка открылась без тикета: {r.status_code}"
    #И у администратора тоже: дверь одна, роль здесь ничего не добавляет.
    assert client.get(f"/web/admin/messenger/conversations/{conv}/messages",
                      headers=admin).status_code == 403


def test_live_ticket_opens_exactly_its_own_conversation(client):
    """С живым тикетом — открывается; чужой беседы тот же тикет не открывает."""
    admin, (_, mod), (b_id, b), (c_id, c) = _setup(client)
    conv = _direct(client, b, c_id)
    mid = client.post(f"/web/messenger/chats/{conv}/messages",
                      json={"body": "грубость"}, headers=b).json()["id"]
    rid = client.post("/web/messenger/reports",
                      json={"message_id": mid, "reason_code": "harassment"},
                      headers=c).json()["report_id"]

    r = client.get(f"/web/admin/messenger/conversations/{conv}/messages?report_id={rid}",
                   headers=mod)
    assert r.status_code == 200, r.text
    assert any(m.get("body") == "грубость" for m in r.json()["messages"])

    #Тот же тикет, ДРУГАЯ беседа — 404: тикет привязан к своей переписке.
    d_id, d = _make_user(client, admin, "stud:dave", "dave", "student", "Дэйв Дэйвов")
    other = _direct(client, c, d_id)
    assert client.get(
        f"/web/admin/messenger/conversations/{other}/messages?report_id={rid}",
        headers=mod).status_code == 404


def test_support_chat_stays_readable_without_a_ticket(client):
    """Обращение в модерацию читается без тикета — иначе очередь обращений не работает."""
    admin, (_, mod), (b_id, b), _ = _setup(client)
    r = client.get("/web/messenger/moderation", headers=b)
    assert r.status_code == 200, r.text
    conv = r.json()["conversation_id"]
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "помогите"}, headers=b)

    r = client.get(f"/web/admin/messenger/conversations/{conv}/messages", headers=mod)
    assert r.status_code == 200, f"обращение обязано открываться: {r.text}"
    assert any(m.get("body") == "помогите" for m in r.json()["messages"])


def test_conversation_list_never_exposes_private_chats(client):
    """Список бесед модерации не показывает личные переписки — ни по умолчанию, ни явно."""
    admin, (_, mod), (b_id, b), (c_id, c) = _setup(client)
    private = _direct(client, b, c_id)
    client.post(f"/web/messenger/chats/{private}/messages", json={"body": "личное"}, headers=b)

    rows = client.get("/web/admin/messenger/conversations", headers=mod).json()["conversations"]
    assert all(x["conversation_id"] != private for x in rows), \
        "личная переписка попала в список модерации"
    assert all((x.get("kind") or "") == "moderation" for x in rows)

    #Произвольный тип запросить нельзя: «фильтр» не должен снова означать «всё подряд».
    assert client.get("/web/admin/messenger/conversations?kind=direct",
                      headers=mod).status_code == 400
