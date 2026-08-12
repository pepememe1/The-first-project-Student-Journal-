"""
test_mobile_session.py — срок жизни сессии МОБИЛЬНОГО приложения.

Мобильная сессия кончается не «через неделю после входа», а в ближайший ПОНЕДЕЛЬНИК
00:00 по времени колледжа: у всех один понятный рубеж вместо личного у каждого.

⚠️ Здесь проверяется ровно то, на чём такая схема ломается, если сделать её наивно.
Рубеж зависит от ДАТЫ ВХОДА, а прежняя проверка на /auth/refresh сравнивала возраст
сессии с ПОСТОЯННЫМ потолком политики. Одной этой проверки мало: в воскресенье возраст
недельной сессии честно меньше недели, понедельник наступает, а сессия живёт дальше.
И наоборот — если считать «до понедельника» прямо на обновлении, то в понедельник утром
формула вернёт «ещё неделя», и сессия будет продлевать себя вечно. Поэтому величин две
и они разного смысла: `issue_ttl_min` (срок конкретной сессии, считается ОДИН РАЗ при
входе) и `session_ttl_min` (потолок политики, постоянен). Тесты держат обе.
"""
from datetime import datetime, timedelta, timezone

from conftest import make_admin

from app.config import (JWT_MOBILE_FLOOR_MIN, JWT_MOBILE_TTL_MIN, JWT_TTL_MIN,
                        issue_ttl_min, minutes_until_next_monday)

WEEK_MIN = 7 * 24 * 60


def _utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def _login(client, login="admin", password="adminpass1", android=False):
    headers = {"X-Client": "android"} if android else {}
    r = client.post("/auth/login", json={"login": login, "password": password},
                    headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _session_row(refresh_token):
    """Строка auth_sessions для refresh-токена (там и лежит назначенный срок)."""
    from app.db import SessionLocal
    from app.models import AuthSession
    from app.security import decode_token
    jti = decode_token(refresh_token)["jti"]
    db = SessionLocal()
    try:
        return db.query(AuthSession).filter(AuthSession.jti == jti).first(), jti
    finally:
        db.close()


def _patch_session(jti, **fields):
    from app.db import SessionLocal
    from app.models import AuthSession
    db = SessionLocal()
    try:
        sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
        assert sess is not None
        for k, v in fields.items():
            setattr(sess, k, v)
        db.commit()
    finally:
        db.close()


# ───────────────────────── сама граница ─────────────────────────

def test_monday_midnight_gets_a_full_week():
    """Ровно в понедельник 00:00 сессия обязана получить неделю, а не ноль.

    Иначе вход в этот момент выдавал бы мертворождённый токен."""
    # понедельник 00:00 по Улан-Удэ (+8) = воскресенье 16:00 UTC
    assert minutes_until_next_monday(_utc(2026, 8, 9, 16, 0)) == WEEK_MIN


def test_boundary_is_local_monday_not_utc_monday():
    """Понедельник МЕСТНЫЙ. Считай мы его по UTC — рубеж уехал бы на сутки.

    Берём воскресенье 23:00 по Улан-Удэ (= воскресенье 15:00 UTC). До местного
    понедельника час; до понедельника ПО UTC — девять часов. Разница видна только
    на таком времени суток, поэтому тест и стоит именно здесь."""
    assert minutes_until_next_monday(_utc(2026, 8, 9, 15, 0)) == 60


def test_boundary_shrinks_as_the_week_goes_on():
    """Чем ближе к понедельнику, тем меньше остаток — и он всегда положительный."""
    # среда 12:00 местного = среда 04:00 UTC
    wed = minutes_until_next_monday(_utc(2026, 8, 5, 4, 0))
    # пятница 12:00 местного
    fri = minutes_until_next_monday(_utc(2026, 8, 7, 4, 0))
    assert WEEK_MIN > wed > fri > 0
    assert wed - fri == 2 * 24 * 60


def test_sunday_evening_login_still_gets_a_full_day():
    """Нижняя граница. «До понедельника» в воскресенье вечером — это пара часов:
    человек открыл бы приложение утром и увидел форму входа, то есть получил ровно ту
    проблему, ради которой длинную сессию и заводили."""
    sunday_late = _utc(2026, 8, 9, 15, 0)          # воскресенье 23:00 местного
    assert minutes_until_next_monday(sunday_late) == 60
    assert issue_ttl_min("android", sunday_late) == JWT_MOBILE_FLOOR_MIN


def test_issued_span_never_exceeds_the_policy_ceiling():
    """Выданный срок обязан укладываться в потолок политики — иначе первая же проверка
    на /auth/refresh отвергала бы совершенно законную свежую сессию."""
    start = _utc(2026, 8, 3, 0, 0)
    for hours in range(0, 24 * 8, 5):
        assert issue_ttl_min("android", start + timedelta(hours=hours)) <= JWT_MOBILE_TTL_MIN


def test_web_and_desktop_sessions_are_untouched():
    """Правило только для приложения. Сайт и десктоп — прежние пять часов."""
    assert issue_ttl_min("web") == JWT_TTL_MIN
    assert issue_ttl_min("") == JWT_TTL_MIN
    assert issue_ttl_min("ANDROID".lower()) != JWT_TTL_MIN


# ───────────────────────── живой вход ─────────────────────────

def test_android_login_gets_the_monday_boundary(client):
    make_admin(client)
    data = _login(client, android=True)
    sess, _ = _session_row(data["refresh_token"])
    assert sess.client == "android"
    expected = issue_ttl_min("android")
    got_min = (int(sess.expires_at) - int(datetime.now(timezone.utc).timestamp())) / 60
    assert abs(got_min - expected) < 5, f"назначено {got_min} мин, ожидалось ~{expected}"


def test_web_login_still_gets_five_hours(client):
    make_admin(client)
    data = _login(client)
    sess, _ = _session_row(data["refresh_token"])
    got_min = (int(sess.expires_at) - int(datetime.now(timezone.utc).timestamp())) / 60
    assert abs(got_min - JWT_TTL_MIN) < 5


# ───────────────────────── рубеж реально держит ─────────────────────────

def test_passed_boundary_ends_the_session_even_though_it_is_younger_than_a_week(client):
    """🔥 ГЛАВНЫЙ тест. Возраст сессии — шесть дней, потолок политики — неделя, то есть
    проверка «возраст против потолка» её пропускает. Отклонить обязана ВТОРАЯ проверка,
    по назначенному при входе сроку. Без неё понедельник наступал бы, а сессия жила."""
    make_admin(client)
    data = _login(client, android=True)
    _, jti = _session_row(data["refresh_token"])
    now = datetime.now(timezone.utc)
    _patch_session(jti,
                   issued_at=(now - timedelta(days=6)).isoformat(),
                   expires_at=int((now - timedelta(hours=1)).timestamp()))

    r = client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]},
                    headers={"X-Client": "android"})
    assert r.status_code == 401, r.text
    sess, _ = _session_row(data["refresh_token"])
    assert sess.revoked is True, "истёкшую сессию мало отклонить — её надо погасить"


def test_six_day_old_session_before_its_boundary_still_refreshes(client):
    """Обратный тест к предыдущему. Без него проверку можно было бы «починить»,
    отвергая вообще всё, и оба теста остались бы зелёными."""
    make_admin(client)
    data = _login(client, android=True)
    _, jti = _session_row(data["refresh_token"])
    now = datetime.now(timezone.utc)
    _patch_session(jti,
                   issued_at=(now - timedelta(days=6)).isoformat(),
                   expires_at=int((now + timedelta(hours=10)).timestamp()))

    r = client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]},
                    headers={"X-Client": "android"})
    assert r.status_code == 200, r.text


def test_new_access_never_outlives_the_boundary(client):
    """Токен, выданный обновлением, обязан кончиться вместе с сессией.

    Иначе рубеж держался бы только на доброй воле клиента: пока access жив, за
    обновлением он не придёт, а значит и проверки выше не выполнятся ни разу."""
    from app.security import decode_token
    make_admin(client)
    data = _login(client, android=True)
    _, jti = _session_row(data["refresh_token"])
    now = datetime.now(timezone.utc)
    boundary = now + timedelta(hours=3)
    _patch_session(jti, expires_at=int(boundary.timestamp()))

    r = client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]},
                    headers={"X-Client": "android"})
    assert r.status_code == 200, r.text
    exp = decode_token(r.json()["access_token"])["exp"]
    assert exp <= int(boundary.timestamp()) + 60, "access пережил рубеж сессии"


def test_android_header_cannot_stretch_an_existing_web_session(client):
    """Заголовок подделывается тривиально, поэтому он выбирает срок ровно один раз —
    при входе. Прислать его позже и растянуть уже выданную веб-сессию нельзя."""
    make_admin(client)
    data = _login(client)                      # вошли как сайт: пять часов
    _, jti = _session_row(data["refresh_token"])
    now = datetime.now(timezone.utc)
    _patch_session(jti, issued_at=(now - timedelta(hours=6)).isoformat(),
                   expires_at=int((now + timedelta(days=6)).timestamp()))

    r = client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]},
                    headers={"X-Client": "android"})
    assert r.status_code == 401, "веб-сессию растянули заголовком до мобильной"
