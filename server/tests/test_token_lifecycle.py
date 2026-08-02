"""
test_token_lifecycle.py — Жизненный цикл токена: refresh, logout, чёрный список,
админский отзыв сессий.

Проверяем ключевые для 152-ФЗ вещи:
  • login выдаёт пару access + refresh;
  • refresh тихо обновляет access (и гасит прежний access этой пары);
  • logout отзывает токен — сервер сразу перестаёт его принимать;
  • админ видит активные сессии и может отозвать их по логину (экстренная блокировка);
  • отозванный токен получает 401, даже если по подписи/сроку он ещё «живой»;
  • АБСОЛЮТНЫЙ потолок сессии (5 ч от РЕАЛЬНОГО входа) держится даже если refresh-токен
    по своему собственному exp ещё не истёк (см. auth.py::refresh, живой баг 3.5.5).
"""
from datetime import datetime, timedelta, timezone

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


def test_refresh_rejected_past_absolute_ceiling_even_if_token_itself_not_expired(client):
    """Живой баг 3.5.5: refresh-токен НЕ ротируется, поэтому его собственный `exp`
    держит потолок сессии, ТОЛЬКО пока JWT_REFRESH_TTL_MIN равен JWT_TTL_MIN. Токен,
    выданный до того, как это значение когда-то сузили (например, с 30 дней до 5
    часов), продолжал бы обновляться ещё месяц — простое повторное открытие сайта
    держало сессию намного дольше 5 часов. Эмулируем это НАПРЯМУЮ (не ждать реальные
    5 часов): подделываем `issued_at` в БД на 6 часов назад — по exp токен всё ещё
    валиден (JWT_REFRESH_TTL_MIN в тестах намного больше 6 часов дефолтом), но по
    РЕАЛЬНОМУ времени входа сессия обязана быть отклонена и отозвана."""
    from app.db import SessionLocal
    from app.models import AuthSession
    from app.security import decode_token

    make_admin(client)
    data = _login(client, "admin", "adminpass1")
    refresh_token = data["refresh_token"]
    jti = decode_token(refresh_token)["jti"]

    db = SessionLocal()
    try:
        sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
        assert sess is not None
        sess.issued_at = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        db.commit()
    finally:
        db.close()

    r = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 401, r.text

    # Сессия помечена отозванной — повторная попытка тоже 401 (не только «протухла»).
    db = SessionLocal()
    try:
        sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
        assert sess.revoked is True
    finally:
        db.close()


def test_refresh_allowed_well_within_absolute_ceiling(client):
    """Обратная сторона предыдущего теста: свежий вход (секунды назад) обязан
    обновляться штатно — потолок не должен ложно срабатывать на реальных сессиях."""
    make_admin(client)
    data = _login(client, "admin", "adminpass1")
    r = client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r.status_code == 200, r.text


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
