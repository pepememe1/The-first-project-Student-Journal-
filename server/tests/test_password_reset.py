"""test_password_reset.py — восстановление пароля ПО ССЫЛКЕ, а не сразу.

Главная проверка тут одна и она обратная: запрос восстановления НЕ ДОЛЖЕН менять пароль.
Раньше менял — и это была настоящая дыра: знающий почту студента (а почта у нас и есть
логин) выкидывал его из журнала сколько угодно раз подряд. Тест на «письмо ушло» такого
не поймал бы вовсе, поэтому проверяем, что старый пароль ПРОДОЛЖАЕТ работать.
"""
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import AuthSession, PasswordReset, User
from app.security import hash_password

from conftest import make_admin

STUDENT = "ivanov@esstu.ru"
OLD_PW = "oldpassword1"


def _add_student(client, admin_headers, login=STUDENT, password=OLD_PW):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password(password), "full_name": "Иванов Иван",
        "surname": "Иванов", "name": "Иван", "group_name": "К74/1",
    }]}}, headers=admin_headers)
    assert r.status_code == 200, r.text


def _last_token(login=STUDENT) -> str:
    db = SessionLocal()
    try:
        row = (db.query(PasswordReset)
               .filter(PasswordReset.login == login, PasswordReset.used_at == "")
               .order_by(PasswordReset.created_at.desc()).first())
        return row.token if row else ""
    finally:
        db.close()


def _login_works(client, password, login=STUDENT) -> bool:
    return client.post("/auth/login",
                       json={"login": login, "password": password}).status_code == 200


# ── Главное свойство ───────────────────────────────────────────────────────────────
def test_recover_request_does_not_change_the_password(client):
    """🔥 Регрессия на найденную дыру. Запрос восстановления — это ПРОСЬБА, а не действие."""
    admin = make_admin(client)
    _add_student(client, admin)
    assert _login_works(client, OLD_PW)

    assert client.post("/auth/recover", json={"email": STUDENT}).status_code == 200
    assert _login_works(client, OLD_PW), (
        "запрос восстановления сменил пароль — это и есть та дыра, ради которой всё писалось")


def test_password_changes_only_after_following_the_link(client):
    admin = make_admin(client)
    _add_student(client, admin)
    client.post("/auth/recover", json={"email": STUDENT})

    token = _last_token()
    assert token, "ссылка не заведена"

    r = client.post("/auth/recover/confirm",
                    json={"token": token, "password": "brandnewpass9"})
    assert r.status_code == 200, r.text
    assert _login_works(client, "brandnewpass9")
    assert not _login_works(client, OLD_PW), "старый пароль обязан перестать работать"


# ── Свойства самой ссылки ──────────────────────────────────────────────────────────
def test_link_is_single_use(client):
    """Ссылка из почтового ящика не должна оставаться вечным ключом от аккаунта."""
    admin = make_admin(client)
    _add_student(client, admin)
    client.post("/auth/recover", json={"email": STUDENT})
    token = _last_token()

    assert client.post("/auth/recover/confirm",
                       json={"token": token, "password": "firstpass12"}).status_code == 200
    r = client.post("/auth/recover/confirm",
                    json={"token": token, "password": "secondpass12"})
    assert r.status_code == 400
    assert _login_works(client, "firstpass12"), "второй проход по ссылке не должен ничего менять"


def test_expired_link_is_rejected(client):
    admin = make_admin(client)
    _add_student(client, admin)
    client.post("/auth/recover", json={"email": STUDENT})
    token = _last_token()

    db = SessionLocal()
    try:
        row = db.query(PasswordReset).filter(PasswordReset.token == token).first()
        row.expires_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.commit()
    finally:
        db.close()

    assert client.post("/auth/recover/confirm",
                       json={"token": token, "password": "newpass1234"}).status_code == 400
    assert _login_works(client, OLD_PW)


def test_unknown_token_is_rejected(client):
    make_admin(client)
    r = client.post("/auth/recover/confirm",
                    json={"token": "ниоткуда", "password": "newpass1234"})
    assert r.status_code == 400


def test_new_request_invalidates_the_previous_link(client):
    """Иначе каждый повторный запрос добавлял бы ещё один действующий ключ, и их
    накапливалось бы столько, сколько писем ушло."""
    admin = make_admin(client)
    _add_student(client, admin)
    client.post("/auth/recover", json={"email": STUDENT})
    first = _last_token()
    #Остуда по почте — час; для второго запроса её надо снять, иначе он тихо не сработает.
    from app import throttle
    throttle._recover.clear()
    client.post("/auth/recover", json={"email": STUDENT})
    second = _last_token()

    assert first and second and first != second
    assert client.post("/auth/recover/confirm",
                       json={"token": first, "password": "newpass1234"}).status_code == 400
    assert client.post("/auth/recover/confirm",
                       json={"token": second, "password": "newpass1234"}).status_code == 200


def test_short_password_is_rejected_and_link_survives(client):
    """Отказ по слабому паролю не должен сжигать ссылку: человек введёт нормальный."""
    admin = make_admin(client)
    _add_student(client, admin)
    client.post("/auth/recover", json={"email": STUDENT})
    token = _last_token()

    assert client.post("/auth/recover/confirm",
                       json={"token": token, "password": "1234"}).status_code == 400
    assert client.post("/auth/recover/confirm",
                       json={"token": token, "password": "goodpass123"}).status_code == 200


def test_reset_revokes_all_sessions(client):
    """Смена пароля — в том числе реакция на «кажется, меня взломали». Старый токен
    обязан умереть вместе со старым паролем."""
    admin = make_admin(client)
    _add_student(client, admin)
    r = client.post("/auth/login", json={"login": STUDENT, "password": OLD_PW})
    assert r.status_code == 200
    stud_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/me/prefs", headers=stud_headers).status_code == 200

    client.post("/auth/recover", json={"email": STUDENT})
    client.post("/auth/recover/confirm",
                json={"token": _last_token(), "password": "afterreset12"})

    assert client.get("/me/prefs", headers=stud_headers).status_code == 401, (
        "старый токен пережил смену пароля")


def test_unknown_email_leaks_nothing(client):
    """Ответ на несуществующую почту неотличим от ответа на существующую."""
    make_admin(client)
    a = client.post("/auth/recover", json={"email": "nobody@esstu.ru"})
    assert a.status_code == 200 and a.json() == {"ok": True}
    db = SessionLocal()
    try:
        assert db.query(PasswordReset).count() == 0, "для несуществующей почты ссылка не заводится"
    finally:
        db.close()


def test_deleted_account_kills_the_link(client):
    """Аккаунт удалили между запросом и переходом — ссылка не должна вести никуда."""
    admin = make_admin(client)
    _add_student(client, admin)
    client.post("/auth/recover", json={"email": STUDENT})
    token = _last_token()

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == STUDENT).first()
        u.deleted = True
        db.commit()
    finally:
        db.close()

    assert client.post("/auth/recover/confirm",
                       json={"token": token, "password": "newpass1234"}).status_code == 400
    db = SessionLocal()
    try:
        row = db.query(PasswordReset).filter(PasswordReset.token == token).first()
        assert row.used_at, "ссылка на удалённый аккаунт обязана погаснуть"
        assert db.query(AuthSession).count() >= 0
    finally:
        db.close()


# ── Разрыв ЖИВОГО сокета ───────────────────────────────────────────────────────────
def test_close_user_actually_closes_and_forgets_the_socket():
    """🔒 Сам механизм разрыва. Проверяем ДВА следствия: сокету пришёл close() и он ушёл
    из реестра — второе не менее важно, иначе `send_users` продолжал бы в него писать."""
    import asyncio
    from app.routers.messenger import ws_manager

    closed = []

    class _FakeWS:
        async def close(self, code=1000):
            closed.append(code)

    ws = _FakeWS()
    ws_manager._by_user.setdefault("u:1", set()).add(ws)
    asyncio.run(ws_manager.close_user("u:1"))

    assert closed, "сокету не пришёл close()"
    assert "u:1" not in ws_manager._by_user, "сокет остался в реестре и будет получать сигналы"


def test_close_user_survives_a_dead_socket():
    """Клиент мог закрыть вкладку миллисекундой раньше — это штатная гонка, а не сбой.
    Важно, что реестр всё равно чистится."""
    import asyncio
    from app.routers.messenger import ws_manager

    class _DeadWS:
        async def close(self, code=1000):
            raise RuntimeError("соединение уже закрыто")

    ws_manager._by_user.setdefault("u:2", set()).add(_DeadWS())
    asyncio.run(ws_manager.close_user("u:2"))
    assert "u:2" not in ws_manager._by_user


def test_logout_asks_to_tear_down_sockets(client, monkeypatch):
    """А здесь — что выход РЕАЛЬНО зовёт разрыв, и зовёт с id того самого человека.

    До починки не звал вовсе: проверка отзыва стояла только на подключении, и уже
    открытый сокет продолжал получать карту активности бесед часами после «Выйти».
    """
    from app.routers import auth as auth_router

    admin = make_admin(client)
    _add_student(client, admin)
    r = client.post("/auth/login", json={"login": STUDENT, "password": OLD_PW})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    db = SessionLocal()
    try:
        uid = db.query(User).filter(User.login == STUDENT).first().id
    finally:
        db.close()

    kicked = []
    monkeypatch.setattr(auth_router, "_kick_sockets", lambda u: kicked.append(u))
    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert kicked == [uid], f"выход не разорвал сокеты нужного человека: {kicked}"


def test_ws_kick_never_breaks_logout(client, monkeypatch):
    """Отзыв сессии обязан состояться, даже если мессенджер недоступен: закрыть доступ
    важнее, чем оборвать уведомления."""
    import app.routers.messenger as msg

    admin = make_admin(client)
    _add_student(client, admin)
    r = client.post("/auth/login", json={"login": STUDENT, "password": OLD_PW})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    def _boom(_uid):
        raise RuntimeError("мессенджер недоступен")

    monkeypatch.setattr(msg.ws_manager, "kick_user", _boom)

    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert client.get("/me/prefs", headers=headers).status_code == 401, (
        "сессия обязана быть отозвана независимо от судьбы сокета")


# ── Анти-энумерация ПО ВРЕМЕНИ ─────────────────────────────────────────────────────
def test_all_three_paths_take_the_same_time(client):
    """🔥 Возражение Полковника: тела ответов были одинаковыми, а ВРЕМЯ — нет.

    Путей три, и раньше они расходились в десятки раз: несуществующая почта спала 350 мс,
    существующая под остудой выходила мгновенно (~5 мс), существующая без остуды ждала
    SMTP (сотни мс — секунды). Порога тут не нужно: 70-кратная разница читается с одного
    замера, а доменов всего три — список живых логинов колледжа собирается перебором
    фамилий, без единого подобранного пароля.

    Проверяем НИЖНЮЮ границу у всех трёх путей: верхнюю на общей машине мерить нечестно
    (прогон могут потеснить), а вот «вышли мгновенно» ловится надёжно.
    """
    import time as _t
    from app.routers import auth as auth_router

    admin = make_admin(client)
    _add_student(client, admin)
    floor = auth_router._RECOVER_BUDGET_S * 0.9

    def _timed(email):
        t0 = _t.monotonic()
        r = client.post("/auth/recover", json={"email": email})
        return _t.monotonic() - t0, r

    #1. Почты нет вовсе.
    d_unknown, r1 = _timed("nobody@esstu.ru")
    #2. Почта есть, остуды ещё нет — заводится ссылка и уходит письмо.
    d_first, r2 = _timed(STUDENT)
    #3. Почта есть, но остуда уже стоит — раньше ЭТОТ путь и выдавал аккаунт мгновенно.
    d_cooled, r3 = _timed(STUDENT)

    assert r1.json() == r2.json() == r3.json() == {"ok": True}
    for name, d in (("несуществующая", d_unknown), ("первая", d_first), ("остуда", d_cooled)):
        assert d >= floor, f"путь «{name}» ответил за {d:.3f} c — быстрее общего бюджета"


def test_mail_is_sent_off_the_request_path(client, monkeypatch):
    """Письмо уходит ПОСЛЕ ответа, в отдельном потоке: SMTP — это сотни миллисекунд, и
    они возникают только когда аккаунт существует. Синхронная отправка вернула бы оракул
    с другой стороны, и никакой общий бюджет времени её бы не покрыл."""
    import time as _t
    from app import mailer

    admin = make_admin(client)
    _add_student(client, admin)

    def _slow_send(*_a, **_kw):
        _t.sleep(1.5)          #заведомо больше бюджета ответа
        return True

    monkeypatch.setattr(mailer, "send_email", _slow_send)
    t0 = _t.monotonic()
    assert client.post("/auth/recover", json={"email": STUDENT}).status_code == 200
    assert _t.monotonic() - t0 < 1.0, "ответ ждал SMTP — значит время выдаёт существование почты"


def test_link_is_never_mailed_over_plain_http(client, monkeypatch):
    """Ссылка несёт одноразовый ключ от аккаунта. Отдать её в открытый канал — подарить
    доступ тому, кто в середине. Та же заслонка, что у автообновления десктопа.

    Адрес не задаётся руками, а ВЫЧИСЛЯЕТСЯ из ALLOWED_ORIGINS — достаточно поставить
    туда первым http-адрес, чтобы письма молча начали рассылать токены по открытому каналу.
    """
    from app.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "SITE_URL", "http://esstu-gradebook.ru")
    sent = []
    monkeypatch.setattr(auth_router.mailer, "send_email",
                        lambda *a, **k: sent.append(a) or True)

    assert auth_router._send_reset_link("kto@esstu.ru", "секрет") is False
    assert not sent, "письмо с одноразовым токеном ушло по http"
