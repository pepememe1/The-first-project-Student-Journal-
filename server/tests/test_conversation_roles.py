"""
test_conversation_roles.py — роли и права внутри беседы (§ролей): кастомные роли групп/
каналов, право kick на remove_member, /mute и /clear как команды, личный игнор.

Права — фиксированный набор (kick/manage_roles/cmd_mute/cmd_clear), см.
routers/messenger.py::_permissions_for. Билдовые owner/admin по умолчанию получают все
четыре (обратная совместимость — беседы без единой кастомной роли работают как раньше).
"""
from conftest import make_admin, make_teacher
from test_messenger import _make_student


def _setup(client):
    admin = make_admin(client)
    a = make_teacher(client, admin)
    b_id, b = _make_student(client, admin, "bob", "Боб Бобов")
    c_id, c = _make_student(client, admin, "carol", "Кэрол Кэрова")
    return admin, ("teach:teacher1", a), (b_id, b), (c_id, c)


def _group(client, owner_headers, member_ids, title="Группа"):
    return client.post("/web/messenger/chats/group",
                       json={"title": title, "member_ids": member_ids},
                       headers=owner_headers).json()["conversation_id"]


def test_default_permissions_owner_admin_vs_member(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id, c_id])
    info_owner = client.get(f"/web/messenger/chats/{conv}", headers=a).json()
    assert set(info_owner["my_permissions"]) == {"kick", "manage_roles", "cmd_mute", "cmd_clear"}
    info_member = client.get(f"/web/messenger/chats/{conv}", headers=b).json()
    assert info_member["my_permissions"] == []


def test_create_update_delete_custom_role_and_assignment(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id, c_id])
    #Обычный участник не может создавать роли.
    assert client.post(f"/web/messenger/chats/{conv}/roles",
                       json={"name": "Староста", "permissions": ["kick"]}, headers=b).status_code == 403
    r = client.post(f"/web/messenger/chats/{conv}/roles",
                    json={"name": "Староста", "permissions": ["kick", "cmd_mute"]}, headers=a)
    assert r.status_code == 200
    role_id = r.json()["id"]
    #Владелец назначает роль b — теперь у b есть kick и cmd_mute, но не manage_roles.
    assert client.post(f"/web/messenger/chats/{conv}/members/{b_id}/role",
                       json={"custom_role_id": role_id}, headers=a).status_code == 200
    info_b = client.get(f"/web/messenger/chats/{conv}", headers=b).json()
    assert set(info_b["my_permissions"]) == {"kick", "cmd_mute"}
    #b теперь может выгнать c (право kick), но не может создавать роли.
    assert client.post(f"/web/messenger/chats/{conv}/roles",
                       json={"name": "X", "permissions": []}, headers=b).status_code == 403
    assert client.delete(f"/web/messenger/chats/{conv}/members/{c_id}", headers=b).status_code == 200
    #Правка роли — сразу отражается на правах участника (право вычисляется на лету).
    assert client.put(f"/web/messenger/chats/{conv}/roles/{role_id}",
                      json={"permissions": ["cmd_clear"]}, headers=a).status_code == 200
    info_b2 = client.get(f"/web/messenger/chats/{conv}", headers=b).json()
    assert set(info_b2["my_permissions"]) == {"cmd_clear"}
    #Удаление роли — участник откатывается на обычную member (без прав).
    assert client.delete(f"/web/messenger/chats/{conv}/roles/{role_id}", headers=a).status_code == 200
    info_b3 = client.get(f"/web/messenger/chats/{conv}", headers=b).json()
    assert info_b3["my_role"] == "member" and info_b3["my_permissions"] == []


def test_owner_permissions_cannot_be_taken_away(client):
    """owner всегда полный набор прав, даже без кастомной роли и даже если бы кто-то
    попытался понизить его через set_member_role (эндпоинт и так это запрещает)."""
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id])
    assert client.post(f"/web/messenger/chats/{conv}/members/{a_id}/role",
                       json={"role": "member"}, headers=a).status_code == 400
    info = client.get(f"/web/messenger/chats/{conv}", headers=a).json()
    assert set(info["my_permissions"]) == {"kick", "manage_roles", "cmd_mute", "cmd_clear"}


def test_mute_command_toggles_and_blocks_sending(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id, c_id])
    #Без права cmd_mute — команда отклоняется, а НЕ публикуется как обычный текст.
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "/mute @Боб"}, headers=c).status_code == 403
    #Владелец глушит Боба.
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": '/mute "@Боб"'}, headers=a)
    assert r.status_code == 200 and r.json()["kind"] == "system"
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "я не могу писать"}, headers=b).status_code == 403
    #Повторный /mute снимает заглушку.
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "/mute @Боб"}, headers=a).status_code == 200
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "снова могу"}, headers=b).status_code == 200


def test_mute_cannot_target_owner(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id])
    assert client.post(f"/web/messenger/chats/{conv}/members/{b_id}/role",
                       json={"role": "admin"}, headers=a).status_code == 200
    #b (теперь admin, есть cmd_mute) пытается замьютить владельца (a, "Преподаватель").
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "/mute @Преподаватель"}, headers=b).status_code == 400


def test_clear_command_tombstones_last_n_and_respects_limit(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id, c_id])
    for i in range(5):
        client.post(f"/web/messenger/chats/{conv}/messages", json={"body": f"msg{i}"}, headers=b)
    #Без права — 403 (c ничего не слал — проверяем чистым от анти-флуда пользователем).
    assert client.post(f"/web/messenger/chats/{conv}/messages",
                       json={"body": "/clear 2"}, headers=c).status_code == 403
    r = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": '/clear "2"'}, headers=a)
    assert r.status_code == 200 and r.json()["kind"] == "system"
    left = client.get(f"/web/messenger/chats/{conv}/messages", headers=a).json()["messages"]
    bodies = [m["body"] for m in left if not m["deleted"] and m["kind"] == "text"]
    assert bodies == ["msg0", "msg1", "msg2"]        #последние 2 удалены (msg3, msg4)


def test_clear_respects_max_limit(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id])
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "only one"}, headers=b)
    r = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "/clear 99999"}, headers=a)
    assert r.status_code == 200          #лимит клампится, а не 500/зависание


def test_ignore_and_unignore_roundtrip(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id, c_id])
    assert client.post(f"/web/messenger/chats/{conv}/ignore/{b_id}", headers=c).status_code == 200
    info = client.get(f"/web/messenger/chats/{conv}", headers=c).json()
    assert info["my_ignored_user_ids"] == [b_id]
    #Игнор ЛИЧНЫЙ — у a его нет.
    info_a = client.get(f"/web/messenger/chats/{conv}", headers=a).json()
    assert info_a["my_ignored_user_ids"] == []
    assert client.delete(f"/web/messenger/chats/{conv}/ignore/{b_id}", headers=c).status_code == 200
    info2 = client.get(f"/web/messenger/chats/{conv}", headers=c).json()
    assert info2["my_ignored_user_ids"] == []


def test_kick_available_to_custom_role_not_only_owner_admin(client):
    """До этой сессии remove_member проверял ТОЛЬКО owner/admin — теперь любая роль с
    правом kick тоже может выгонять, что и было целью §ролей."""
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id, c_id])
    r = client.post(f"/web/messenger/chats/{conv}/roles",
                    json={"name": "Модератор", "permissions": ["kick"]}, headers=a)
    role_id = r.json()["id"]
    client.post(f"/web/messenger/chats/{conv}/members/{b_id}/role",
               json={"custom_role_id": role_id}, headers=a)
    assert client.delete(f"/web/messenger/chats/{conv}/members/{c_id}", headers=b).status_code == 200


def test_roles_list_includes_templates(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id])
    r = client.get(f"/web/messenger/chats/{conv}/roles", headers=a)
    assert r.status_code == 200
    data = r.json()
    assert data["roles"] == []
    names = {t["name"] for t in data["templates"]}
    assert {"Студент", "Староста", "Преподаватель"} <= names
    assert set(data["all_permissions"]) == {"kick", "manage_roles", "cmd_mute", "cmd_clear"}


def test_conversation_info_includes_my_user_id(client):
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id])
    info = client.get(f"/web/messenger/chats/{conv}", headers=a).json()
    assert info["my_user_id"] == a_id
