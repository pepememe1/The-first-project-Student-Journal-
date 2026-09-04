# -*- coding: utf-8 -*-
"""test_mfa_step_up.py — второй фактор ЗА ПРЕДЕЛАМИ входа (03.09.2026).

Требование Ярослава дословно: «этот код будет проситься при восстановлении пароля,
а также допустим если за пользователем замечена подозрительная активность когда он
много раз не мог зайти в аккаунт».

━━ ЧТО ИМЕННО ЗДЕСЬ ЗАЩИЩАЕТСЯ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
До этой правки включённый второй фактор обходился ЦЕЛИКОМ и двумя способами, причём
оба выглядели как штатная работа продукта:

  1. восстановление пароля. Ссылка из письма меняла пароль, не спросив кода ни разу.
     Получивший доступ к почтовому ящику входил в журнал, а человек был уверен, что
     защищён приложением на телефоне;
  2. продление сессии. Укравший refresh-токен продлевал его тихо и бесконечно —
     второй фактор спрашивается только на входе, а входа он не совершает.

⚠️ Каждая проверка ниже идёт В ПАРЕ с обратной: «с кодом пускает» бессмысленно без
«без кода не пускает», и наоборот. Односторонний тест здесь зелен и при полностью
снятой защите, и при защите, запирающей человека навсегда.
"""

import time

import pytest

from app import throttle, totp
from app.db import SessionLocal
from app.models import PasswordReset, User
from app.security import hash_password

from conftest import make_admin

STUDENT = "petrov@esstu.ru"
OLD_PW = "oldpassword1"
NEW_PW = "brandnewpass9"


# ─────────────────────────────────────────────────────────────────────────────────
# Помощники
# ─────────────────────────────────────────────────────────────────────────────────

def _add_student(client, admin_headers, login=STUDENT, password=OLD_PW):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password(password), "full_name": "Петров Пётр",
        "surname": "Петров", "name": "Пётр", "group_name": "К74/1",
    }]}}, headers=admin_headers)
    assert r.status_code == 200, r.text


def _login(client, login, password):
    return client.post("/auth/login", json={"login": login, "password": password})


def _headers(client, login, password):
    r = _login(client, login, password)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _enable_mfa(client, headers):
    """Пройти путь человека целиком: секрет → подтверждение кодом."""
    r = client.post("/auth/mfa/setup", headers=headers)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = client.post("/auth/mfa/confirm", headers=headers, json={"code": totp.code(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def _next_code(secret, steps: int = 1):
    """Код шага «+steps» вперёд.

    ⚠️ Шаг, которым только что вошли, ПОГАШЕН и второй раз не принимается — это защита
    от подсмотренного через плечо кода. Поэтому во втором подряд действии за тот же
    тест приходится брать шаг дальше (`steps=2`), а не повторять предыдущий.
    """
    return totp.code(secret, at=time.time() + steps * totp.STEP_SECONDS)


def _reset_token(login=STUDENT) -> str:
    db = SessionLocal()
    try:
        row = (db.query(PasswordReset)
               .filter(PasswordReset.login == login, PasswordReset.used_at == "")
               .order_by(PasswordReset.created_at.desc()).first())
        return row.token if row else ""
    finally:
        db.close()


def _ask_reset(client, login=STUDENT) -> str:
    assert client.post("/auth/recover", json={"email": login}).status_code == 200
    token = _reset_token(login)
    assert token, "ссылка восстановления не заведена"
    return token


# ─────────────────────────────────────────────────────────────────────────────────
# Признак подозрительной активности
# ─────────────────────────────────────────────────────────────────────────────────

def test_a_handful_of_typos_from_one_place_is_not_suspicious():
    """Живой человек, забывший раскладку, — НЕ атака.

    Порог обязан быть выше бытовой опечатки: признак, который поднимается на каждого
    невыспавшегося преподавателя, начнут игнорировать вместе с настоящими случаями.
    """
    throttle.reset()
    for _ in range(throttle.SUSPICION_FAILS - 1):
        throttle.register_login_attack("ivan", "10.0.0.1")
    assert throttle.is_suspicious("ivan") is False


def test_a_series_of_failures_raises_the_flag():
    throttle.reset()
    for _ in range(throttle.SUSPICION_FAILS):
        throttle.register_login_attack("ivan", "10.0.0.1")
    assert throttle.is_suspicious("ivan") is True
    assert throttle.suspicion("ivan")["fails"] == throttle.SUSPICION_FAILS


def test_two_different_addresses_are_enough_by_themselves():
    """🔥 Ради этого признак и ключуется ЛОГИНОМ, а не парой (адрес, логин).

    Перебор, размазанный по адресам, пара (IP, логин) не видит по построению: у
    каждого адреса своя запись, и ни одна не доходит до порога. А два разных адреса
    за час по одному логину — это уже точно не один забывчивый человек.
    """
    throttle.reset()
    throttle.register_login_attack("ivan", "10.0.0.1")
    throttle.register_login_attack("ivan", "10.0.0.2")
    assert throttle.is_suspicious("ivan") is True


def test_the_flag_outlives_the_five_minute_lock():
    """Замок анти-брутфорса снимается через пять минут и всё забывает.

    Если бы признак жил столько же, подобравший пароль входил бы через шесть минут в
    полной тишине — то есть ровно в тот момент, ради которого след и ведётся.
    """
    assert throttle.SUSPICION_WINDOW > throttle.LOCK_SECONDS


def test_only_a_confirmed_code_clears_the_flag():
    """⚠️ Удачный вход снимать признак НЕ имеет права.

    Подобравший пароль входит удачно по определению, и «вошёл — значит свой» стирало
    бы след того самого события, ради которого он ведётся.
    """
    throttle.reset()
    for _ in range(throttle.SUSPICION_FAILS):
        throttle.register_login_attack("ivan", "10.0.0.1")
    throttle.register_success("10.0.0.1", "ivan")
    assert throttle.is_suspicious("ivan") is True, (
        "обычный удачный вход снял признак — подобравший пароль стирает след сам собой")
    throttle.clear_suspicion("ivan")
    assert throttle.is_suspicious("ivan") is False


def test_the_flag_is_recorded_by_a_real_failed_login(client):
    """Сторож ВЫЗОВА, а не поведения: без строки в auth.py признак не поднимет никто."""
    admin = make_admin(client)
    _add_student(client, admin)
    throttle.reset()
    for _ in range(throttle.SUSPICION_FAILS):
        _login(client, STUDENT, "wrong-password")
    assert throttle.is_suspicious(STUDENT) is True, (
        "неудачные входы не оставляют следа по логину — признак подозрительной "
        "активности не поднимется НИКОГДА, и вся защита ниже мертва")


# ─────────────────────────────────────────────────────────────────────────────────
# Восстановление пароля
# ─────────────────────────────────────────────────────────────────────────────────

def test_reset_without_mfa_still_works_without_any_code(client):
    """⚠️ Главный обратный ход всей затеи.

    Восстановление — последняя дверь для потерявшего доступ. Потребовать код у того,
    кто его не заводил, значит запереть человека навсегда: взять код неоткуда.
    """
    admin = make_admin(client)
    _add_student(client, admin)
    token = _ask_reset(client)
    r = client.post("/auth/recover/confirm", json={"token": token, "password": NEW_PW})
    assert r.status_code == 200, r.text
    assert _login(client, STUDENT, NEW_PW).status_code == 200


def test_reset_with_mfa_demands_the_code(client):
    """🔒 Дыра, которую эта правка закрывает: почта давала полный обход второго фактора."""
    admin = make_admin(client)
    _add_student(client, admin)
    headers = _headers(client, STUDENT, OLD_PW)
    _enable_mfa(client, headers)

    token = _ask_reset(client)
    r = client.post("/auth/recover/confirm", json={"token": token, "password": NEW_PW})
    assert r.status_code == 401, (
        "пароль сменился по одной ссылке из письма — включённый второй фактор "
        "обходится целиком через восстановление")
    assert r.headers.get("X-Gb-Reason") == "mfa_required", (
        "отказ без признака: страница покажет «ссылка не подошла» вместо поля кода, "
        "и человек не догадается, чего от него хотят")
    #И пароль обязан остаться прежним — иначе отказ косметический.
    assert _login(client, STUDENT, OLD_PW).status_code == 200


def test_reset_with_mfa_goes_through_with_the_code(client):
    admin = make_admin(client)
    _add_student(client, admin)
    headers = _headers(client, STUDENT, OLD_PW)
    secret, _codes = _enable_mfa(client, headers)

    token = _ask_reset(client)
    r = client.post("/auth/recover/confirm",
                    json={"token": token, "password": NEW_PW, "code": _next_code(secret)})
    assert r.status_code == 200, r.text
    #Вход с новым паролем теперь снова требует второй фактор — он никуда не делся.
    r = _login(client, STUDENT, NEW_PW)
    assert r.status_code == 200 and r.json().get("mfa_required") is True


def test_a_wrong_code_does_not_change_the_password(client):
    admin = make_admin(client)
    _add_student(client, admin)
    headers = _headers(client, STUDENT, OLD_PW)
    _enable_mfa(client, headers)

    token = _ask_reset(client)
    r = client.post("/auth/recover/confirm",
                    json={"token": token, "password": NEW_PW, "code": "000000"})
    assert r.status_code == 401
    assert _login(client, STUDENT, OLD_PW).status_code == 200, "пароль всё-таки сменился"


def test_a_recovery_code_works_here_too(client):
    """Телефон потерян — запасной ключ обязан открывать ту же дверь.

    Иначе потерявший телефон не может ни войти, ни восстановить пароль, и остаётся
    только правка базы руками — то есть ровно то, от чего коды восстановления и заведены.
    """
    admin = make_admin(client)
    _add_student(client, admin)
    headers = _headers(client, STUDENT, OLD_PW)
    _secret, codes = _enable_mfa(client, headers)

    token = _ask_reset(client)
    r = client.post("/auth/recover/confirm",
                    json={"token": token, "password": NEW_PW, "code": codes[0]})
    assert r.status_code == 200, r.text
    assert _login(client, STUDENT, NEW_PW).status_code == 200


def test_the_reset_link_survives_a_wrong_code(client):
    """⚠️ Ошибка в коде не должна сжигать ссылку.

    Ссылка одноразовая, и если бы неверный код её гасил, промах в шести цифрах
    означал бы «запрашивайте восстановление заново» — а оно ещё и с часовой остудой
    по почте. Человек застрял бы на час из-за опечатки.
    """
    admin = make_admin(client)
    _add_student(client, admin)
    headers = _headers(client, STUDENT, OLD_PW)
    secret, _codes = _enable_mfa(client, headers)

    token = _ask_reset(client)
    client.post("/auth/recover/confirm",
                json={"token": token, "password": NEW_PW, "code": "000000"})
    r = client.post("/auth/recover/confirm",
                    json={"token": token, "password": NEW_PW, "code": _next_code(secret)})
    assert r.status_code == 200, "ссылка сгорела от неверного кода"


# ─────────────────────────────────────────────────────────────────────────────────
# Продление сессии
# ─────────────────────────────────────────────────────────────────────────────────

def _refresh(client, token):
    return client.post("/auth/refresh", json={"refresh_token": token})


def test_refresh_is_stopped_when_the_account_is_under_attack(client):
    """🔒 Тихое продление — единственное действие БЕЗ участия человека.

    Укравший refresh-токен живёт на нём столько же, сколько владелец, и второй фактор
    его не касается: входа он не совершает. Признак атаки обязан это прерывать.
    """
    admin = make_admin(client)
    _add_student(client, admin)
    headers = _headers(client, STUDENT, OLD_PW)
    secret, _codes = _enable_mfa(client, headers)

    r = _login(client, STUDENT, OLD_PW)
    challenge = r.json()["challenge"]
    r = client.post("/auth/mfa/verify",
                    json={"challenge": challenge, "code": _next_code(secret)})
    assert r.status_code == 200, r.text
    refresh_token = r.json()["refresh_token"]

    #Пока тихо — продление работает.
    assert _refresh(client, refresh_token).status_code == 200

    #Теперь по логину идёт перебор.
    for _ in range(throttle.SUSPICION_FAILS):
        _login(client, STUDENT, "wrong-password")
    r = _refresh(client, refresh_token)
    assert r.status_code == 401, "сессия продлилась молча, пока к аккаунту подбирали пароль"
    assert r.headers.get("X-Gb-Reason") == "reauth_required", (
        "отказ без причины читается как сбой продукта в середине рабочего дня, "
        "а не как защита")


def test_a_user_without_the_second_factor_is_never_locked_out_this_way(client):
    """⚠️ Цена признака: поднять его может ПОСТОРОННИЙ.

    Достаточно поспамить неверным паролем по чужому логину. Для того, у кого второго
    фактора нет, отказ в продлении не даёт НИЧЕГО (он введёт тот самый пароль,
    который и подбирают), зато даёт атакующему готовый способ выбивать человека из
    журнала. Поэтому у таких продление обязано работать как обычно.
    """
    admin = make_admin(client)
    _add_student(client, admin)
    r = _login(client, STUDENT, OLD_PW)
    refresh_token = r.json()["refresh_token"]

    for _ in range(throttle.SUSPICION_FAILS + 3):
        _login(client, STUDENT, "wrong-password")
    assert throttle.is_suspicious(STUDENT) is True
    assert _refresh(client, refresh_token).status_code == 200, (
        "человека без второго фактора выбило из журнала чужим перебором — "
        "признак превратился в способ отключить кому угодно доступ")


def test_passing_the_code_clears_the_flag_and_refresh_works_again(client):
    """Владелец подтвердил, что это он, — дальше не мешаем.

    Без этого жертва чужого перебора получала бы требование кода при КАЖДОМ продлении
    ещё час после того, как всё уже подтвердила.
    """
    admin = make_admin(client)
    _add_student(client, admin)
    headers = _headers(client, STUDENT, OLD_PW)
    secret, _codes = _enable_mfa(client, headers)

    for _ in range(throttle.SUSPICION_FAILS):
        _login(client, STUDENT, "wrong-password")
    assert throttle.is_suspicious(STUDENT) is True

    r = _login(client, STUDENT, OLD_PW)
    challenge = r.json()["challenge"]
    r = client.post("/auth/mfa/verify",
                    json={"challenge": challenge, "code": _next_code(secret)})
    assert r.status_code == 200, r.text
    assert throttle.is_suspicious(STUDENT) is False, "признак пережил подтверждение кодом"
    assert _refresh(client, r.json()["refresh_token"]).status_code == 200


# ─────────────────────────────────────────────────────────────────────────────────
# Строка для аутентификатора и её QR
# ─────────────────────────────────────────────────────────────────────────────────

def test_setup_gives_both_ways_to_add_the_account(client):
    """Двух путей ровно два, и оба обязаны приехать в одном ответе.

    На телефоне работает ссылка `otpauth://` (приложение перехватывает схему и заводит
    запись само), на компьютере — QR с экрана. Замечание Ярослава дословно: «если
    куаркод на экране то чтобы его отсканить нужен другой телефон, а вот на пк да
    нужен куаркод».
    """
    admin = make_admin(client)
    r = client.post("/auth/mfa/setup", headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["uri"].startswith("otpauth://totp/"), "ссылки для телефона нет"
    assert f"secret={data['secret']}" in data["uri"]
    #Параметры обязаны быть в ссылке ЯВНО: аутентификаторы по умолчанию берут SHA1/6/30,
    #но «по умолчанию» у разных приложений разное, и расхождение выглядит как «телефон
    #показывает неправильный код».
    assert "algorithm=SHA1" in data["uri"] and "digits=6" in data["uri"]
    assert "period=30" in data["uri"]

    qr = data["qr"]
    assert qr["size"] > 20 and qr["path"], "QR для компьютера не пришёл"


def test_the_qr_encodes_exactly_the_same_uri(client):
    """🔥 Иначе телефон заведёт запись с ДРУГИМ секретом.

    Отказ был бы отложенным и необъяснимым: настройка «прошла», а первый же вход
    сообщает, что код не подходит, — и починить это человеку уже нечем.
    """
    from test_qr import decode          # независимый декодер, см. соседний файл
    from app import qr as qr_mod

    admin = make_admin(client)
    data = client.post("/auth/mfa/setup", headers=admin).json()
    assert decode(qr_mod.matrix(data["uri"])) == data["uri"]


def test_the_qr_is_not_offered_to_a_third_party(client):
    """🔒 В картинку кодируется СЕКРЕТ второго фактора.

    Поэтому её рисуем мы сами, а не внешний генератор: запрос к чужому сервису — это
    отправка секрета третьей стороне, притом иностранной (п. 5.6.1 политики ВСГУТУ).
    Сторож проверяет ОТСУТСТВИЕ такого пути в продукте.
    """
    from pathlib import Path
    code = (Path(__file__).resolve().parents[1] / "app" / "qr.py").read_text(encoding="utf-8")
    #⚠️ Пояснения ВЫРЕЗАЕМ: докстринг модуля обязан называть отвергнутые сервисы
    #поимённо (иначе следующий читатель решит, что про них просто не подумали), и
    #проверка по всему тексту краснела бы именно на этом объяснении.
    body = "\n".join(line for line in code.splitlines()
                     if not line.strip().startswith("#"))
    body = body.split('""' + '"')[-1]
    for bad in ("requests.", "urllib.request", "httpx.", "socket.", "http://", "https://"):
        assert bad not in body, (
            f"кодировщик QR обращается наружу ({bad}) — в картинку кодируется СЕКРЕТ "
            "второго фактора, и любой внешний адрес здесь означает его передачу "
            "третьей стороне")


# ─────────────────────────────────────────────────────────────────────────────────
# Срок окна подтверждения и длина сессии
# ─────────────────────────────────────────────────────────────────────────────────

def test_login_tells_the_client_how_long_the_code_window_lasts(client):
    """🔥 Без этого числа истечение окна выглядит как «журнал меня выкинул».

    Жалоба Ярослава 03.09.2026, воспроизведена на бою: пока человек ищет нужную
    запись в аутентификаторе, срок выходит, сервер отвечает 401, окно кода пропадает
    — и на экране снова форма входа. Клиент рисует обратный отсчёт по этому полю,
    поэтому оно часть контракта, а не подсказка.
    """
    admin = make_admin(client)
    _add_student(client, admin)
    headers = _headers(client, STUDENT, OLD_PW)
    _enable_mfa(client, headers)

    body = _login(client, STUDENT, OLD_PW).json()
    assert body.get("mfa_required") is True
    assert body.get("expires_in", 0) >= 300, (
        "клиенту не сказали, сколько живёт окно подтверждения — отсчёта не будет, "
        "и человек снова увидит необъяснимый выброс на форму входа")


def test_the_code_window_is_long_enough_to_find_the_entry():
    """Пять минут не хватало на практике — их и не хватило у живого человека.

    ⚠️ Проверяем ПОРОГ, а не точное число: срок можно менять, а вот вернуть его к
    пяти минутам, не заметив, что это ровно та причина жалобы, — нельзя.
    """
    from app.routers import mfa as mfa_router
    assert mfa_router.CHALLENGE_TTL_MIN >= 10


def test_the_second_factor_buys_a_longer_session():
    """Требование Ярослава: «месяц на телефоне и неделю на вебе/десктопе».

    Размен честный: пятичасовой потолок защищает от «отошёл от общего компьютера,
    не выйдя из аккаунта», а со вторым фактором одного пароля для входа мало.
    """
    from app import config
    assert config.session_ttl_min("web", mfa=True) >= 7 * 24 * 60
    assert config.session_ttl_min("android", mfa=True) >= 30 * 24 * 60
    #Обратный ход: без второго фактора прежние сроки не тронуты.
    assert config.session_ttl_min("web") == config.JWT_TTL_MIN
    assert config.session_ttl_min("android") == config.JWT_MOBILE_TTL_MIN


def test_turning_the_second_factor_off_shortens_the_session_at_once(client, monkeypatch):
    """⚠️ Иначе «включу на минуту, получу месяц, выключу» стало бы обходом потолка.

    Потолок обязан считаться от ТЕКУЩЕГО состояния, а не от того, что было при входе,
    — ровно как в 3.5.5, где токен, выданный при щедрой настройке, продолжал жить по
    ней ещё месяц после ужесточения.

    ⚠️ Время здесь ДВИГАЕМ, а не берём «шаг подальше»: окно допуска ±1 шаг, а шаг
    входа уже погашен защитой от повтора — то есть свободных кодов «прямо сейчас» не
    остаётся вовсе. Это не обход проверки, а единственный способ сыграть в тесте те
    полминуты, которые в жизни просто проходят сами.
    """
    admin = make_admin(client)
    _add_student(client, admin)
    headers = _headers(client, STUDENT, OLD_PW)
    secret, _codes = _enable_mfa(client, headers)

    r = _login(client, STUDENT, OLD_PW)
    r = client.post("/auth/mfa/verify",
                    json={"challenge": r.json()["challenge"], "code": _next_code(secret)})
    assert r.status_code == 200, r.text
    long_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    refresh_token = r.json()["refresh_token"]

    class _Later:
        """Часы, ушедшие вперёд на две минуты — и для теста, и для продукта разом."""
        def time(self):
            return time.time() + 120

    monkeypatch.setattr(totp, "time", _Later())
    r = client.post("/auth/mfa/disable", headers=long_headers,
                    json={"code": totp.code(secret)})
    monkeypatch.undo()
    assert r.status_code == 200, r.text

    from app import config
    assert config.session_ttl_min("web", mfa=False) < config.session_ttl_min("web", mfa=True)
    #Сессия ещё молодая, поэтому продление проходит — но судится уже по КОРОТКОМУ
    #потолку: длинный был бы у неё, только пока второй фактор включён.
    assert _refresh(client, refresh_token).status_code == 200
