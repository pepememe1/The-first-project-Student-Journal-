"""
test_me_prefs.py — Личные настройки пользователя (POST/GET /me/prefs).

Проверяем, что:
  • пользователь сохраняет СВОИ prefs и видит их обратно;
  • prefs уезжают через обычный /sync/pull (чтобы тема «роумилась» между ПК);
  • слияние ключей prefs не теряет ранее сохранённые;
  • без авторизации эндпоинт закрыт (нельзя править чужой/анонимный профиль).
"""
from conftest import make_admin, make_teacher


def test_set_and_get_own_prefs(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    r = client.post("/me/prefs", json={"theme": {"id": "violet"}}, headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["theme"] == {"id": "violet"}

    r = client.get("/me/prefs", headers=teacher)
    assert r.status_code == 200
    assert r.json()["prefs"]["theme"] == {"id": "violet"}


def test_prefs_merge_keeps_existing(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    client.post("/me/prefs", json={"theme": {"id": "blue"}}, headers=teacher)
    client.post("/me/prefs", json={"foo": "bar"}, headers=teacher)

    prefs = client.get("/me/prefs", headers=teacher).json()["prefs"]
    assert prefs["theme"] == {"id": "blue"}   #старый ключ не потерян
    assert prefs["foo"] == "bar"


def test_prefs_roam_via_pull(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)

    client.post("/me/prefs", json={"theme": {"id": "amber"}}, headers=teacher)

    #Любой авторизованный pull отдаёт пользователей со столбцом prefs.
    data = client.get("/sync/pull", headers=admin).json()
    users = data["changes"]["users"]
    me = next(u for u in users if u["login"] == "teacher1")
    assert me["prefs"]["theme"] == {"id": "amber"}


def test_prefs_requires_auth(client):
    r = client.post("/me/prefs", json={"theme": {"id": "blue"}})
    assert r.status_code == 401
