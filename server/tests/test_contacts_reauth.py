# -*- coding: utf-8 -*-
"""
test_contacts_reauth.py — почту и телефон для защиты входа меняет только тот, кто заново
назвал текущий пароль (OWASP ASVS V7.5.1; решение Ярослава 07.10.2026 «требовать пароль»).

━━ ЧТО БЫЛО ━━
Три ручки — телефон, привязка почты, удаление почты — не спрашивали ничего, кроме живой
сессии. На подтверждённую почту приходит код входа с нового устройства и письмо о смене
пароля; по телефону администратор сверяет человека перед выдачей нового пароля. Открытая
вкладка на общем компьютере аудитории (или украденный токен) позволяла подменить оба
контакта на свои — и аккаунт уходил надолго, а владелец узнавал об этом последним.

━━ ЧТО ПРОВЕРЯЕТСЯ ━━
Каждая из трёх дверей: без пароля — отказ и НИЧЕГО не изменилось; с неверным — отказ и
попытка засчитана тому же счётчику, что считает вход; с верным — действие выполнено.
Плюс «проверяй вызов»: второй фактор спрашивается той же дверью, что у смены пароля.
"""
import re

import pytest

from conftest import make_admin

WEB = {"X-Client": "web", "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"}
PASSWORD = "studpass1"


@pytest.fixture
def mail(monkeypatch):
    from app import mailer
    box = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, body, html="": box.append({"to": to, "body": body}) or True)
    return box


@pytest.fixture
def me(client):
    admin = make_admin(client)
    r = client.post("/web/admin/students", json={
        "login": "s1", "surname": "Иванова", "name": "Мария", "group": "К-1",
        "password": PASSWORD}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": "s1", "password": PASSWORD}, headers=WEB)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", **WEB}


def _contacts(client, me):
    return client.get("/me/contacts", headers=me).json()


def _bind_email(client, me, mail, email="ivanova@yandex.ru"):
    r = client.post("/me/contacts/email/start", json={"email": email, "current": PASSWORD},
                    headers=me)
    assert r.status_code == 200, r.text
    code = re.search(r"Код: (\d{6})", mail[-1]["body"]).group(1)
    r = client.post("/me/contacts/email/confirm", json={"code": code}, headers=me)
    assert r.status_code == 200 and r.json()["self_email_verified"] is True, r.text


#Дверь → (метод, адрес, тело без пароля). Удаление почты — обе формы: новая POST и
#прежний DELETE, которым ходит программа прежней версии.
DOORS = {
    "телефон": ("post", "/me/contacts/phone", {"phone": "+7 900 111-22-33"}),
    "привязка почты": ("post", "/me/contacts/email/start", {"email": "thief@example.org"}),
    "удаление почты": ("post", "/me/contacts/email/remove", {}),
    "удаление почты, прежний адрес": ("delete", "/me/contacts/email", None),
}


def _call(client, me, door, extra=None):
    method, url, body = DOORS[door]
    if method == "delete":
        return client.request("DELETE", url, headers=me, json=extra) if extra \
            else client.delete(url, headers=me)
    return client.post(url, json={**body, **(extra or {})}, headers=me)


@pytest.mark.parametrize("door", list(DOORS))
def test_without_the_password_nothing_changes(client, me, mail, door):
    _bind_email(client, me, mail)
    before, letters = _contacts(client, me), len(mail)
    r = _call(client, me, door)
    assert r.status_code == 400, r.text
    assert r.headers.get("X-Gb-Reason") == "password_required"
    assert "текущий пароль" in r.json()["detail"].lower()
    assert _contacts(client, me) == before, "отказ, а контакты изменились"
    assert len(mail) == letters, "отказ, а письмо с кодом на чужой адрес ушло"


@pytest.mark.parametrize("door", list(DOORS))
def test_a_wrong_password_is_refused_and_counted(client, me, mail, door):
    from app import throttle
    _bind_email(client, me, mail)
    before, letters = _contacts(client, me), len(mail)
    r = _call(client, me, door, {"current": "не-тот-пароль"})
    assert r.status_code == 400 and r.json()["detail"] == "Текущий пароль неверен", r.text
    assert _contacts(client, me) == before and len(mail) == letters
    #Счётчик ОБЩИЙ со входом: иначе эти ручки стали бы обходной дорогой к перебору пароля
    #из украденной сессии. Добиваем до порога входа — и дверь запирается на всех.
    for _ in range(throttle.MAX_FAILS):
        last = _call(client, me, door, {"current": "не-тот-пароль"})
    assert last.status_code == 429, last.text
    locked = client.post("/auth/login", json={"login": "s1", "password": PASSWORD}, headers=WEB)
    assert locked.status_code == 429, "перебор через ручку контактов не запер вход"


def test_the_right_password_opens_every_door(client, me, mail):
    r = _call(client, me, "телефон", {"current": PASSWORD})
    assert r.status_code == 200 and r.json()["self_phone"], r.text
    _bind_email(client, me, mail)
    assert _contacts(client, me)["self_email"] == "ivanova@yandex.ru"
    r = _call(client, me, "удаление почты", {"current": PASSWORD})
    assert r.status_code == 200 and not r.json()["self_email"], r.text
    #И прежний адрес удаления работает, если пароль всё-таки прислали.
    _bind_email(client, me, mail)
    r = _call(client, me, "удаление почты, прежний адрес", {"current": PASSWORD})
    assert r.status_code == 200 and not r.json()["self_email"], r.text


def test_changes_leave_a_trace_and_refusals_too(client, me, mail):
    from app.db import SessionLocal
    from app.models import AuditEvent
    _call(client, me, "телефон", {"current": "не-тот-пароль"})
    _call(client, me, "телефон", {"current": PASSWORD})
    db = SessionLocal()
    try:
        actions = [e.action for e in db.query(AuditEvent).filter(AuditEvent.actor == "s1").all()]
    finally:
        db.close()
    assert "contact.change.reject" in actions and "contact.phone_set" in actions, actions


def test_the_second_factor_is_asked_through_the_same_door(client, me, mail, monkeypatch):
    """Проверяем ВЫЗОВ: у кого второй фактор включён, код спрашивает `mfa.guard_action` —
    та же дверь, что у смены пароля. Строку вызова убрать — тест покраснеет."""
    from app.routers import mfa
    asked = []
    real = mfa.guard_action

    def spy(db, user, code, request, what):
        asked.append((what, code))
        return real(db, user, code, request, what)

    monkeypatch.setattr(mfa, "guard_action", spy)
    _call(client, me, "телефон", {"current": PASSWORD, "code": "123456"})
    _call(client, me, "привязка почты", {"current": PASSWORD})
    _call(client, me, "удаление почты", {"current": PASSWORD})
    assert asked == [("смена телефона", "123456"), ("смена почты", ""), ("удаление почты", "")]
    #А с неверным паролем до второго фактора дело не доходит вовсе.
    asked.clear()
    _call(client, me, "телефон", {"current": "не-тот-пароль", "code": "123456"})
    assert asked == []


# ── смена пароля идёт той же дверью — и прежнее поведение на месте ─────────────────────

def test_password_change_still_needs_the_current_password(client, me):
    r = client.post("/me/password", json={"current": "не-тот-пароль", "new": "новыйПароль42"},
                    headers=me)
    assert r.status_code == 400 and r.json()["detail"] == "Текущий пароль неверен", r.text
    r = client.post("/me/password", json={"new": "новыйПароль42"}, headers=me)
    assert r.status_code == 400 and r.headers.get("X-Gb-Reason") == "password_required"
    assert client.post("/auth/login", json={"login": "s1", "password": PASSWORD},
                       headers=WEB).status_code == 200, "отказ, а пароль сменился"
    r = client.post("/me/password", json={"current": PASSWORD, "new": "новыйПароль42"}, headers=me)
    assert r.status_code == 200, r.text
    assert client.post("/auth/login", json={"login": "s1", "password": PASSWORD},
                       headers=WEB).status_code == 401
    assert client.post("/auth/login", json={"login": "s1", "password": "новыйПароль42"},
                       headers=WEB).status_code == 200


def test_a_long_passphrase_is_accepted_whole(client, me):
    """ASVS V6.2.9: длинная парольная фраза принимается целиком, без обрезки — вход
    усечённой её частью не проходит."""
    phrase = "конь батарея скрепка верный " * 5          # 140 символов, с пробелами
    r = client.post("/me/password", json={"current": PASSWORD, "new": phrase}, headers=me)
    assert r.status_code == 200, r.text
    login = lambda pw: client.post("/auth/login", json={"login": "s1", "password": pw},  # noqa: E731
                                   headers=WEB).status_code
    assert login(phrase) == 200
    assert login(phrase[:72]) == 401 and login(phrase[:-1]) == 401
