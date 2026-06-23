"""
test_auth.py — Авторизация и анти-брутфорс серверного API.
"""
from conftest import make_admin
from app import throttle


def test_health(client):
    assert client.get("/health").status_code == 200


def test_bootstrap_then_blocked(client):
    h = make_admin(client)
    assert "Authorization" in h
    #повторный bootstrap запрещён — администратор уже есть
    r = client.post("/auth/bootstrap-admin",
                    json={"login": "a2", "password": "adminpass1", "full_name": "X"})
    assert r.status_code == 409


def test_bootstrap_rejects_short_password(client):
    r = client.post("/auth/bootstrap-admin",
                    json={"login": "admin", "password": "short", "full_name": "X"})
    assert r.status_code == 400


def test_login_ok_and_bad(client):
    make_admin(client)
    assert client.post("/auth/login",
                       json={"login": "admin", "password": "adminpass1"}).status_code == 200
    assert client.post("/auth/login",
                       json={"login": "admin", "password": "wrong"}).status_code == 401


def test_bruteforce_locks_after_threshold(client):
    """После MAX_FAILS неверных попыток вход блокируется (429), и даже ВЕРНЫЙ пароль
    в окне блокировки не пускает — это и есть защита от перебора."""
    make_admin(client)
    #истощаем лимит неверными попытками
    for _ in range(throttle.MAX_FAILS):
        r = client.post("/auth/login", json={"login": "admin", "password": "nope"})
        assert r.status_code == 401
    #следующая попытка — уже блокировка, даже с правильным паролем
    r = client.post("/auth/login", json={"login": "admin", "password": "adminpass1"})
    assert r.status_code == 429
    assert r.headers.get("Retry-After")
    assert int(r.headers["Retry-After"]) > 0


def test_success_resets_failure_counter(client):
    """Удачный вход обнуляет счётчик: несколько неудач, затем успех — и снова есть
    полный лимит попыток, блокировки нет."""
    make_admin(client)
    for _ in range(throttle.MAX_FAILS - 1):
        client.post("/auth/login", json={"login": "admin", "password": "nope"})
    #успешный вход сбрасывает счётчик
    assert client.post("/auth/login",
                       json={"login": "admin", "password": "adminpass1"}).status_code == 200
    #счётчик обнулён — снова неверный пароль даёт 401, а не 429
    assert client.post("/auth/login",
                       json={"login": "admin", "password": "nope"}).status_code == 401
