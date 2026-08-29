# -*- coding: utf-8 -*-
"""Второй фактор входа: заведение, проверка, обязательность для администратора.

⚠️ Тесты гоняют НАСТОЯЩИЙ алгоритм, а не заглушку. Крипту нельзя замокать
осмысленно: подменив проверку кода, мы проверили бы собственную подмену. Коды
считаются тем же `totp`, что и в продукте, — как их считает телефон.
"""

import time

import pytest

from app import config, totp
from app.db import SessionLocal
from app.models import UserMFA
from conftest import make_admin, make_teacher


def _next_code(secret):
    """Код СЛЕДУЮЩЕГО шага времени.

    ⚠️ Нужен потому, что защита от повтора работает: код, которым только что
    подтвердили настройку, тем же кодом войти уже не даст — его шаг погашен.
    В жизни это правильно (человек подождёт полминуты), в тесте — просто берём
    следующий шаг. Он попадает в окно допуска ±1, поэтому сервер его примет.
    """
    return totp.code(secret, at=time.time() + totp.STEP_SECONDS)


def _enable_mfa(client, headers):
    """Пройти путь человека целиком: получить секрет, подтвердить кодом."""
    r = client.post("/auth/mfa/setup", headers=headers)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = client.post("/auth/mfa/confirm", headers=headers,
                    json={"code": totp.code(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


# ─────────────────────────────────────────────────────────────────────────────────
# Алгоритм
# ─────────────────────────────────────────────────────────────────────────────────

def test_code_from_the_phone_is_accepted_and_a_wrong_one_is_not():
    secret = totp.new_secret()
    assert totp.verify(secret, totp.code(secret)) is not None
    assert totp.verify(secret, "000000") is None
    assert totp.verify(secret, "12345") is None       # не шесть цифр
    assert totp.verify(secret, "абвгде") is None


def test_clock_drift_of_half_a_minute_is_tolerated():
    """Часы телефона и сервера расходятся ВСЕГДА.

    Без запаса половина людей не войдёт с исправным приложением, и виноватым
    окажется «сломанный вход», а не время на телефоне.
    """
    secret = totp.new_secret()
    now = 1_700_000_000
    for shift in (-totp.STEP_SECONDS, 0, totp.STEP_SECONDS):
        code = totp.code(secret, at=now + shift)
        assert totp.verify(secret, code, at=now) is not None, f"сдвиг {shift} с отвергнут"
    #А вот две минуты — уже нет: окно перебора растёт линейно с запасом.
    far = totp.code(secret, at=now + 120)
    assert totp.verify(secret, far, at=now) is None


def test_the_same_code_never_works_twice():
    """🔒 Подсмотренный через плечо код живёт 30 секунд. Второй раз — нельзя."""
    secret = totp.new_secret()
    code = totp.code(secret)
    step = totp.verify(secret, code)
    assert step is not None
    assert totp.verify(secret, code, after_step=step) is None


def test_recovery_codes_are_stored_only_as_hashes():
    codes = totp.new_recovery_codes(3)
    stored = [totp.hash_recovery(c) for c in codes]
    for raw, h in zip(codes, stored, strict=True):
        assert raw not in h, "код восстановления виден в хеше — это второй пароль открытым текстом"
        assert totp.check_recovery(raw, h)
    assert not totp.check_recovery(codes[0], stored[1])


# ─────────────────────────────────────────────────────────────────────────────────
# Заведение
# ─────────────────────────────────────────────────────────────────────────────────

def test_factor_does_not_work_until_confirmed(client):
    """Начал настройку и закрыл вкладку — вход обязан остаться прежним.

    Иначе человек запер бы себя навсегда: секрет в базе есть, в телефоне нет.
    """
    headers = make_admin(client)
    client.post("/auth/mfa/setup", headers=headers)
    assert client.get("/auth/mfa/status", headers=headers).json()["enabled"] is False

    r = client.post("/auth/login", json={"login": "admin", "password": "adminpass1"})
    assert r.status_code == 200
    assert "access_token" in r.json(), "неподтверждённый фактор не должен мешать входу"


def test_recovery_codes_are_shown_once_and_never_again(client):
    headers = make_admin(client)
    _secret, codes = _enable_mfa(client, headers)
    assert len(codes) == totp.RECOVERY_COUNT

    #Второго способа их увидеть нет по построению — в базе только хеши.
    with SessionLocal() as db:
        row = db.query(UserMFA).first()
        blob = " ".join(row.recovery_hashes or [])
    for c in codes:
        assert c not in blob


def test_setup_cannot_be_restarted_while_the_factor_is_on(client):
    """🔒 Иначе добравшийся до открытой сессии просто перезаведёт фактор на себя."""
    headers = make_admin(client)
    _enable_mfa(client, headers)
    r = client.post("/auth/mfa/setup", headers=headers)
    assert r.status_code == 409


# ─────────────────────────────────────────────────────────────────────────────────
# Вход
# ─────────────────────────────────────────────────────────────────────────────────

def test_login_with_the_factor_gives_no_token_at_all(client):
    """🔥 Главное свойство: пока фактор не пройден, токена НЕ СУЩЕСТВУЕТ.

    Не «токен с пометкой», которую пришлось бы проверять в двух сотнях ручек, —
    а именно отсутствие токена.
    """
    headers = make_admin(client)
    _enable_mfa(client, headers)

    r = client.post("/auth/login", json={"login": "admin", "password": "adminpass1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("mfa_required") is True
    assert body.get("challenge")
    assert "access_token" not in body
    assert "refresh_token" not in body


def test_the_challenge_is_not_a_working_access_token(client):
    """🔒 Подпись у него та же — годиться как пропуск он не должен."""
    headers = make_admin(client)
    _enable_mfa(client, headers)
    challenge = client.post("/auth/login",
                            json={"login": "admin", "password": "adminpass1"}).json()["challenge"]

    #⚠️ Спрашиваем НАСТОЯЩУЮ защищённую ручку. Первая версия теста стучалась в «/me»,
    #а такого маршрута нет — запрос уходил в SPA-заглушку и возвращал 200 (страницу).
    #Тест «краснел» на пустом месте и точно так же мог бы позеленеть на пустом месте.
    r = client.get("/me/prefs", headers={"Authorization": f"Bearer {challenge}"})
    assert r.status_code in (401, 403), "challenge пустили как обычный токен"


def test_correct_code_completes_the_login(client):
    headers = make_admin(client)
    secret, _codes = _enable_mfa(client, headers)
    challenge = client.post("/auth/login",
                            json={"login": "admin", "password": "adminpass1"}).json()["challenge"]

    r = client.post("/auth/mfa/verify", json={"challenge": challenge, "code": _next_code(secret)})
    assert r.status_code == 200, r.text
    assert r.json().get("access_token")


def test_wrong_code_does_not_complete_the_login(client):
    headers = make_admin(client)
    _enable_mfa(client, headers)
    challenge = client.post("/auth/login",
                            json={"login": "admin", "password": "adminpass1"}).json()["challenge"]
    r = client.post("/auth/mfa/verify", json={"challenge": challenge, "code": "000000"})
    assert r.status_code == 400


def test_a_recovery_code_works_exactly_once(client):
    """Потерянный телефон — это то, ради чего коды и заведены."""
    headers = make_admin(client)
    _secret, codes = _enable_mfa(client, headers)

    def login_challenge():
        return client.post("/auth/login",
                           json={"login": "admin", "password": "adminpass1"}).json()["challenge"]

    r = client.post("/auth/mfa/verify", json={"challenge": login_challenge(), "code": codes[0]})
    assert r.status_code == 200, r.text
    assert r.json().get("access_token")

    #Тот же код второй раз — нет. Иначе утёкший список работает вечно.
    r = client.post("/auth/mfa/verify", json={"challenge": login_challenge(), "code": codes[0]})
    assert r.status_code == 400


def test_turning_the_factor_off_requires_a_working_code(client):
    """Пароля мало: сессия уже открыта под паролем, проверять его нечего."""
    headers = make_admin(client)
    secret, _codes = _enable_mfa(client, headers)

    assert client.post("/auth/mfa/disable", headers=headers,
                       json={"code": "000000"}).status_code == 400
    assert client.get("/auth/mfa/status", headers=headers).json()["enabled"] is True

    r = client.post("/auth/mfa/disable", headers=headers, json={"code": _next_code(secret)})
    assert r.status_code == 200, r.text
    assert client.get("/auth/mfa/status", headers=headers).json()["enabled"] is False


# ─────────────────────────────────────────────────────────────────────────────────
# Обязательность для администратора
# ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def as_production(monkeypatch):
    """Притвориться боевым сервером.

    Признак «бой» выводится из настроек (`config.IS_PROD`), отдельного флага в
    продукте нет намеренно — он бы разошёлся с действительностью. Здесь подменяем
    именно его, а не заводим тестовый режим: тестовый режим проверял бы сам себя.
    """
    monkeypatch.setattr(config, "IS_PROD", True)


def test_admin_without_the_factor_gets_nothing_on_production(client, as_production):
    """🔒 Пароль администратора — единственная дверь к ПДн всего колледжа."""
    headers = make_admin(client)
    r = client.get("/web/admin/groups", headers=headers)
    assert r.status_code == 403, r.text
    assert r.headers.get("X-Gb-Reason") == "mfa_setup_required", (
        "отказ обязан быть машиночитаемым: иначе интерфейс покажет «нет прав», и "
        "администратор пойдёт искать, кто отобрал доступ, вместо настройки за минуту"
    )


def test_the_lock_still_has_a_door(client, as_production):
    """Настроить фактор администратор обязан мочь — иначе это замок без двери."""
    headers = make_admin(client)
    assert client.post("/auth/mfa/setup", headers=headers).status_code == 200
    assert client.get("/auth/mfa/status", headers=headers).status_code == 200


def test_admin_with_the_factor_works_normally(client, as_production):
    headers = make_admin(client)
    _enable_mfa(client, headers)
    assert client.get("/web/admin/groups", headers=headers).status_code == 200


def test_the_requirement_does_not_apply_to_the_local_desktop_server(client, monkeypatch):
    """Обратный ход политики: без `IS_PROD` замка нет.

    Секрет фактора намеренно не синхронизируется на компьютеры, а журнал обязан
    открываться офлайн. Замок здесь означал бы, что администратор с отключённым
    интернетом не может работать вовсе.
    """
    #⚠️ Подменяем ЯВНО, а не полагаемся на окружение прогона. На машине разработчика
    #рядом лежит `server/.env`, и `config.IS_PROD` там ИСТИННО — то есть тест,
    #опирающийся на окружение, у одного человека проверял бы одно, у другого другое.
    monkeypatch.setattr(config, "IS_PROD", False)
    headers = make_admin(client)
    assert client.get("/web/admin/groups", headers=headers).status_code == 200


def test_the_requirement_does_not_touch_other_roles(client, as_production):
    """Преподавателю фактор не навязываем.

    Решение осознанное и его цена названа: у преподавателя доступ к своим группам,
    а не ко всему колледжу, и обязательный второй фактор для полусотни человек —
    это полсотни потерянных телефонов и очередь к администратору. Понадобится —
    правится ОДНА строка `mfa.required_for`.
    """
    admin_headers = make_admin(client)
    #Заводим преподавателя, пока у админа ещё нет фактора… но на «бою» админ уже
    #заперт, поэтому фактор ему сначала включаем.
    _enable_mfa(client, admin_headers)
    teacher_headers = make_teacher(client, admin_headers)
    r = client.get("/me/prefs", headers=teacher_headers)
    assert r.status_code == 200
    assert client.get("/auth/mfa/status", headers=teacher_headers).json()["required"] is False


def test_admin_without_the_factor_is_stopped_everywhere_not_just_in_admin_sections(
        client, as_production):
    """🔥 Проверка стоит в `get_current_user`, а не в `require_admin`, — и вот почему.

    `require_admin` закрывает административные РАЗДЕЛЫ. Но админские полномочия
    живут и внутри обычных ручек: в активностях админ распоряжается чужой
    активностью (восемь мест с `user.role == "admin"` прямо в теле), в мессенджере
    попадает в получатели обращений. Через `require_admin` эти ветки не проходят
    вовсе — то есть админ без второго фактора сохранял бы часть полномочий по
    одному паролю, а докстринг утверждал бы обратное.
    """
    headers = make_admin(client)
    #Обычная, НЕ административная ручка: раньше она была бы доступна.
    r = client.get("/web/messenger/chats", headers=headers)
    assert r.status_code == 403, r.text
    assert r.headers.get("X-Gb-Reason") == "mfa_setup_required"


def test_the_allowed_list_is_exactly_enough_to_set_the_factor_up(client, as_production):
    """Замок обязан оставлять дверь — и ровно дверь, не шире.

    Настройка идёт со страницы настроек: ей нужны свой статус, ручки фактора и
    настройки профиля, чтобы страница вообще отрисовалась. Всё остальное закрыто.
    """
    headers = make_admin(client)
    for path in ("/auth/mfa/status", "/me/prefs"):
        assert client.get(path, headers=headers).status_code == 200, path
    assert client.post("/auth/mfa/setup", headers=headers).status_code == 200
