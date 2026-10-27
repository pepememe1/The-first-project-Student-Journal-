"""
test_messenger_directory_groups.py — тёзки в каталоге мессенджера различимы по группе.

Живой прогон 27.10.2026: в окне «Новая группа» два «Иванов Иван Сергеевич» из разных групп
стояли без подписи, выбрать нужного было нельзя. Студенту в выдаче каталога приходит его
группа — та же, что видна в карточке.
"""
from conftest import make_admin


def _student(client, admin, login, group):
    r = client.post("/web/admin/groups", json={"name": group, "subjects": ["Математика"]}, headers=admin)
    assert r.status_code in (200, 409), r.text
    r = client.post("/web/admin/students", json={
        "login": login, "surname": "Иванов", "name": "Иван Сергеевич", "group": group,
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text


def test_namesakes_carry_their_group(client):
    admin = make_admin(client)
    _student(client, admin, "ivanov1", "К64/2")
    _student(client, admin, "ivanov2", "К74/1")
    r = client.get("/web/messenger/users", params={"role": "student", "q": "Иванов"}, headers=admin)
    assert r.status_code == 200, r.text
    groups = sorted(tuple(u.get("groups") or []) for u in r.json()["users"])
    assert groups == [("К64/2",), ("К74/1",)], groups
