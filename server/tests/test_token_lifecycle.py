"""
test_token_lifecycle.py — Жизненный цикл токена: refresh, logout, чёрный список,
админский отзыв сессий.

Проверяем ключевые для 152-ФЗ вещи:
  • login выдаёт пару access + refresh;
  • refresh тихо обновляет access (и гасит прежний access этой пары);
  • logout отзывает токен — сервер сразу перестаёт его принимать;
  • админ видит активные сессии и может отозвать их по логину (экстренная блокировка);
  • отозванный токен получает 401, даже если по подписи/сроку он ещё «живой».
"""
from conftest import make_admin, make_teacher


def _login(client, login, password):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_login_returns_access_and_refresh(client):
    make_admin(client)
    data = _login(client, "admin", "adminpass1")
    assert data["access_token"] and data["refresh_token"]
    assert data["access_token"] != data["refresh_token"]


def test_refresh_issues_new_access_and_revokes_old(client):
    make_admin(client)
    data = _login(client, "admin", "adminpass1")
    old_access = data["access_token"]
    # прежний access работает
    assert client.get("/admin/online",
                      headers={"Authorization": f"Bearer {old_access}"}).status_code == 200
    # обновляемся по refresh
    r = client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r.status_code == 200, r.text
    new_access = r.json()["access_token"]
    assert new_access != old_access
    # новый access работает
    assert client.get("/admin/online",
                      headers={"Authorization": f"Bearer {new_access}"}).status_code == 200
    # СТАРЫЙ access этой пары после refresh отозван (чёрный список)
    assert client.get("/admin/online",
                      headers={"Authorization": f"Bearer {old_access}"}).status_code == 401


def test_logout_revokes_token(client):
    make_admin(client)
    data = _login(client, "admin", "adminpass1")
    h = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get("/admin/online", headers=h).status_code == 200
    assert client.post("/auth/logout", headers=h).status_code == 200
    # после выхода токен мгновенно недействителен
    assert client.get("/admin/online", headers=h).status_code == 401
    # и refresh этой пары тоже отозван — тихо обновиться уже нельзя
    assert client.post("/auth/refresh",
                       json={"refresh_token": data["refresh_token"]}).status_code == 401


def test_refresh_rejected_when_revoked(client):
    make_admin(client)
    data = _login(client, "admin", "adminpass1")
    # админ отзывает все свои сессии по логину
    r = client.post("/admin/sessions/revoke", json={"login": "admin"},
                    headers={"Authorization": f"Bearer {data['access_token']}"})
    # access уже отозван — запрос отзыва мог пройти по прежнему токену: делаем через новый вход
    # (проверяем именно, что refresh после отзова не работает)
    assert client.post("/auth/refresh",
                       json={"refresh_token": data["refresh_token"]}).status_code == 401


def test_admin_lists_and_revokes_sessions(client):
    admin_h = make_admin(client)
    teacher_h = make_teacher(client, admin_h)
    # преподаватель вошёл — админ видит его активную сессию
    r = client.get("/admin/sessions", headers=admin_h)
    assert r.status_code == 200, r.text
    logins = {s["login"] for s in r.json()["sessions"]}
    assert "teacher1" in logins
    # преподаватель работает
    assert client.get("/me/prefs", headers=teacher_h).status_code in (200, 404)
    # админ блокирует преподавателя (все его сессии)
    rr = client.post("/admin/sessions/revoke", json={"login": "teacher1"}, headers=admin_h)
    assert rr.status_code == 200 and rr.json()["revoked"] >= 1
    # токен преподавателя мгновенно недействителен
    assert client.get("/me/prefs", headers=teacher_h).status_code == 401
