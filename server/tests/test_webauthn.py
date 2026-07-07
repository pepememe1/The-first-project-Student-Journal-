"""
test_webauthn.py — Passkeys (WebAuthn): базовые проверки эндпоинтов.

Полную церемонию (create/get с реальной подписью) без аппаратного аутентификатора не
воспроизвести, поэтому проверяем контракт: выдачу опций, защиту register'а токеном,
корректные отказы. Проверка подписи — код py_webauthn (доверяем библиотеке + ручной
тест на устройстве).
"""
from conftest import make_admin


def test_login_begin_is_public_and_returns_challenge(client):
    r = client.post("/auth/webauthn/login/begin", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("challenge"), "должен вернуться challenge для входа"
    assert data.get("rpId"), "должен вернуться rpId"


def test_register_begin_requires_auth(client):
    #Регистрация ключа — только вошедшему пользователю.
    assert client.post("/auth/webauthn/register/begin").status_code == 401
    h = make_admin(client)
    r = client.post("/auth/webauthn/register/begin", headers=h)
    assert r.status_code == 200, r.text
    assert r.json().get("challenge")
    assert r.json().get("rp", {}).get("id"), "опции регистрации содержат rp.id"


def test_login_complete_unknown_credential_is_rejected(client):
    #Начали вход (создали challenge), но ключ неизвестен — понятный 400, не 500.
    client.post("/auth/webauthn/login/begin", json={})
    r = client.post("/auth/webauthn/login/complete", json={"credential": {"id": "unknown-key"}})
    assert r.status_code == 400
    assert "не найден" in r.json()["detail"].lower()


def test_credentials_list_requires_auth_and_starts_empty(client):
    assert client.get("/auth/webauthn/credentials").status_code == 401
    h = make_admin(client)
    r = client.get("/auth/webauthn/credentials", headers=h)
    assert r.status_code == 200
    assert r.json() == {"credentials": []}
