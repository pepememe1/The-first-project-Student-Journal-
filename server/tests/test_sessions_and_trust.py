# -*- coding: utf-8 -*-
"""test_sessions_and_trust.py — «Сессии», подтверждение входа кодом из письма и
доверенные устройства (4.0).

Что здесь защищается:
  • ЗАКРЫТАЯ СЕССИЯ ОТВЕЧАЕТ 401 НА СЛЕДУЮЩЕМ ЖЕ ЗАПРОСЕ — крестиком и «выйти из всех»
    (кроме текущей: её человек не закрывал).
  • ПОКА КОД НЕ ВВЕДЁН, ТОКЕНА НЕТ: при подтверждённой почте вход с нового устройства
    отдаёт challenge, а не пару токенов; сам challenge пропуском не работает.
  • ПОДТВЕРЖДЕНИЕ — ТОЛЬКО НА СОВПАВШИЙ СПОСОБ: почта разошлась с записью колледжа —
    код туда не уходит.
  • ДОВЕРЕННОЕ УСТРОЙСТВО: вход без кода, 15 дней после выхода — тоже без кода,
    позже — снова с кодом.
  • ДЕСКТОП НЕ ЛОМАЕТСЯ: без `X-Client: web` подтверждения нет вовсе.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

from conftest import make_admin

WEB = {"X-Client": "web", "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"}


@pytest.fixture
def mail(monkeypatch):
    """Почта «настроена», письма складываются в список вместо SMTP."""
    from app import mailer
    box = []
    monkeypatch.setattr(mailer, "configured", lambda: True)

    def fake_send(to, subject, body, html=""):
        box.append({"to": to, "subject": subject, "body": body})
        return True
    monkeypatch.setattr(mailer, "send_email", fake_send)
    return box


def _code(box):
    m = re.search(r"Код: (\d{6})", box[-1]["body"])
    assert m, box[-1]["body"]
    return m.group(1)


def _student(client, admin, login="s1", password="studpass1"):
    r = client.post("/web/admin/students", json={
        "login": login, "surname": "Иванова", "name": "Мария", "group": "К-1",
        "password": password}, headers=admin)
    assert r.status_code == 200, r.text


def _login(client, login="s1", password="studpass1", headers=WEB, **extra):
    return client.post("/auth/login", json={"login": login, "password": password, **extra},
                       headers=headers)


def _auth(tok):
    return {"Authorization": f"Bearer {tok['access_token']}", **WEB}


def _verify_email(client, h, box, email="ivanova@yandex.ru"):
    r = client.post("/me/contacts/email/start", json={"email": email}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/me/contacts/email/confirm", json={"code": _code(box)}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["self_email_verified"] is True


def test_closed_session_gets_401_on_next_request(client):
    admin = make_admin(client)
    _student(client, admin)
    a = _auth(_login(client).json())
    b = _auth(_login(client).json())

    sessions = client.get("/me/sessions", headers=a).json()["sessions"]
    assert len(sessions) == 2
    assert sum(1 for s in sessions if s["current"]) == 1
    other = next(s for s in sessions if not s["current"])
    assert other["device"] == "Chrome · Windows"
    #Местоположение без локальной базы GeoIP — честная пустота, а не догадка.
    assert other["location"] == ""

    assert client.delete(f"/me/sessions/{other['id']}", headers=a).status_code == 200
    assert client.get("/me/prefs", headers=b).status_code == 401, "закрытая сессия жива"
    assert client.get("/me/prefs", headers=a).status_code == 200, "закрыли не ту"


def test_revoke_others_keeps_only_current(client):
    admin = make_admin(client)
    _student(client, admin)
    a = _auth(_login(client).json())
    b = _auth(_login(client).json())
    c = _auth(_login(client).json())
    r = client.post("/me/sessions/revoke-others", headers=a)
    assert r.status_code == 200 and r.json()["revoked"] == 2, r.text
    assert client.get("/me/prefs", headers=b).status_code == 401
    assert client.get("/me/prefs", headers=c).status_code == 401
    assert client.get("/me/prefs", headers=a).status_code == 200
    assert len(client.get("/me/sessions", headers=a).json()["sessions"]) == 1


def test_verified_email_requires_code_from_new_device(client, mail):
    admin = make_admin(client)
    _student(client, admin)
    h = _auth(_login(client).json())
    _verify_email(client, h, mail)

    r = _login(client)
    assert r.status_code == 200, r.text
    data = r.json()
    #Токена НЕТ — есть только challenge и маска адреса.
    assert data.get("mfa_required") is True and data.get("method") == "email"
    assert "access_token" not in data
    assert data["channel"] == "i*****a@yandex.ru"
    challenge = data["challenge"]
    #Сам challenge пропуском не работает.
    assert client.get("/me/prefs", headers={"Authorization": f"Bearer {challenge}",
                                            **WEB}).status_code == 401
    code = _code(mail)
    wrong = "000000" if code != "000000" else "111111"
    assert client.post("/auth/mfa/verify", json={"challenge": challenge,
                                                 "code": wrong}).status_code == 400
    r = client.post("/auth/mfa/verify", json={"challenge": challenge, "code": code})
    assert r.status_code == 200, r.text
    assert client.get("/me/prefs", headers=_auth(r.json())).status_code == 200
    #Тот же challenge второй раз не годится.
    assert client.post("/auth/mfa/verify", json={"challenge": challenge,
                                                 "code": code}).status_code == 401


def test_desktop_login_is_not_asked_for_email_code(client, mail):
    """Десктоп проходит барьер устройства, а мост входа программы код из письма
    показать не умеет — подтверждение для него не включается."""
    admin = make_admin(client)
    _student(client, admin)
    _verify_email(client, _auth(_login(client).json()), mail)
    r = _login(client, headers={})
    assert r.status_code == 200 and "access_token" in r.json(), r.text


def test_mismatched_email_is_not_used_for_confirmation(client, mail):
    """Своя почта разошлась с записью колледжа — код на неё не шлём (возможно, её
    вписал угнавший), а администратор видит расхождение."""
    admin = make_admin(client)
    _student(client, admin)
    _verify_email(client, _auth(_login(client).json()), mail)
    r = client.post("/web/accounts/extra", json={"login": "s1",
                                                 "admin_email": "real@mail.ru",
                                                 "admin_phone": "89001234567"},
                    headers=admin)
    assert r.status_code == 200, r.text
    c = r.json()["contacts"]
    assert c["email_state"] == "mismatch" and c["confirm_channel"] == ""
    sent_before = len(mail)
    r = _login(client)
    assert "access_token" in r.json(), "на разошедшуюся почту код не отправляется"
    assert len(mail) == sent_before


def test_trusted_device_skips_code_and_lives_15_days_after_logout(client, mail):
    admin = make_admin(client)
    _student(client, admin)
    h = _auth(_login(client).json())
    _verify_email(client, h, mail)

    #Первый вход с галочкой — через код, и в ответе секрет устройства.
    data = _login(client, trust_device=True).json()
    r = client.post("/auth/mfa/verify", json={"challenge": data["challenge"],
                                              "code": _code(mail)})
    tok = r.json()
    trust = tok.get("trust_token")
    assert trust, tok

    #Вход с доверенного устройства — без кода.
    sent = len(mail)
    r = _login(client, trust_token=trust, trust_device=True)
    assert "access_token" in r.json(), r.text
    assert len(mail) == sent

    #Вышел — 15 дней доверие держится.
    assert client.post("/auth/logout", headers=_auth(r.json())).status_code == 200
    r = _login(client, trust_token=trust, trust_device=True)
    assert "access_token" in r.json(), "после выхода устройство ещё доверенное"
    client.post("/auth/logout", headers=_auth(r.json()))

    #Прошло 16 дней после выхода — снова с кодом.
    from app.db import SessionLocal
    from app.models import TrustedDevice
    db = SessionLocal()
    try:
        dev = db.get(TrustedDevice, trust.split(".", 1)[0])
        dev.logged_out_at = (datetime.now(timezone.utc) - timedelta(days=16)).isoformat()
        db.commit()
    finally:
        db.close()
    r = _login(client, trust_token=trust, trust_device=True)
    assert r.json().get("mfa_required") is True, r.text


def test_trusted_session_is_not_cut_by_the_five_hour_ceiling(client):
    """«Пока вошёл с доверенного устройства — сессия без срока»: /auth/refresh не
    обрывает её по возрасту, а обычную — обрывает."""
    admin = make_admin(client)
    _student(client, admin)
    plain = _login(client).json()
    trusted = _login(client, trust_device=True).json()
    assert trusted["trust_token"]
    from app.db import SessionLocal
    from app.models import AuthSession
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    db = SessionLocal()
    try:
        for s in db.query(AuthSession).filter(AuthSession.kind == "refresh").all():
            s.issued_at = old
        db.commit()
    finally:
        db.close()
    assert client.post("/auth/refresh", json={"refresh_token": plain["refresh_token"]},
                       headers=WEB).status_code == 401
    r = client.post("/auth/refresh", json={"refresh_token": trusted["refresh_token"]},
                    headers=WEB)
    assert r.status_code == 200, r.text


def test_revoking_a_trusted_session_also_revokes_trust(client, mail):
    """«Закрыть сессию» — реакция на «это не я»: устройство перестаёт быть доверенным,
    иначе сидящий за ним вошёл бы снова без кода."""
    admin = make_admin(client)
    _student(client, admin)
    me = _auth(_login(client).json())
    _verify_email(client, me, mail)
    data = _login(client, trust_device=True).json()
    trust = client.post("/auth/mfa/verify", json={"challenge": data["challenge"],
                                                  "code": _code(mail)}).json()["trust_token"]
    assert client.post("/me/sessions/revoke-others", headers=me).status_code == 200
    r = _login(client, trust_token=trust, trust_device=True)
    assert r.json().get("mfa_required") is True, r.text
