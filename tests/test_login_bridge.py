"""
test_login_bridge.py — ВХОД через локальное серверное приложение (local_api).

Это то, что позволяет убрать нативный экран входа и оставить один интерфейс на все
платформы. Логика двухступенчатая и порядок ступеней — не деталь реализации, а само
обещание продукта:

  1) СНАЧАЛА локальная копия базы → человек входит БЕЗ СЕТИ (offline-first);
  2) не вышло → боевой сервер → выдаём СВОЙ токен и запускаем синхронизацию.

Обратный порядок («сначала спросим сервер») выглядит безобиднее, но убивает
offline-first: в колледже без интернета журнал не открылся бы вовсе.

Тесты поднимают НАСТОЯЩЕЕ серверное приложение на временной базе — заглушка не заметила
бы, что маршрут перехвачен заглушкой SPA или что выданный токен не открывает `/web/*`.
"""
import json
import os
import tempfile
import urllib.error
import urllib.request

import pytest

import local_api


#Успешный вход ЗАПОМИНАЕТ сессию: запускает синхронизацию и пишет логин в настройки
#приложения. В тестах это недопустимо — настройки на машине разработчика НАСТОЯЩИЕ, и
#прогон тестов подменял бы в них сохранённый вход выдуманным «loc» (поймано ровно так:
#соседний тест начал видеть чужой логин, а на машине слетела сохранённая сессия).
#Подменяем сам «запомнить», а не его внутренности: так проверяется и то, что мост его
#действительно зовёт, и ничего настоящего не трогается.
_remembered = []
#Оригинал держим отдельно: тест ниже читает ЕГО исходник, а модульный атрибут на время
#прогона подменён заглушкой.
_ORIGINAL_REMEMBER = local_api._remember_session


@pytest.fixture(scope="module", autouse=True)
def _no_real_session():
    original = local_api._remember_session
    local_api._remember_session = lambda login, password, role: _remembered.append(
        (login, role))
    yield
    local_api._remember_session = original


@pytest.fixture(scope="module")
def api(_no_real_session):
    tmp = os.path.join(tempfile.mkdtemp(), "login_bridge_test.db").replace("\\", "/")
    os.environ["GRADEBOOK_DB_URL"] = f"sqlite:///{tmp}"
    srv = local_api.instance()
    if not srv.start():
        pytest.skip(f"серверный пакет недоступен в этом окружении: {srv.error}")
    _add_user(login="loc", password="mypass123")
    yield srv
    srv.stop()


def _add_user(login, password, role="student"):
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password
    db = SessionLocal()
    try:
        db.merge(User(id=f"stud:{login}", login=login, role=role,
                      surname="Тестов", name="Тест", group_name="К74/1", deleted=False,
                      password_hash=hash_password(password),
                      updated_at="2026-07-30T00:00:00+00:00"))
        db.commit()
    finally:
        db.close()


def _post(api, path, payload):
    req = urllib.request.Request(api.url(path), data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _get(api, path, token):
    req = urllib.request.Request(api.url(path), headers={
        "Authorization": f"Bearer {token}", "X-Client": "web"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_login_works_offline_from_local_copy(api):
    """Главное свойство: человек входит, когда сети нет вовсе.

    Хеш владельца сессии в локальной копии есть (чужие сервер вырезает при выдаче),
    поэтому проверка пароля целиком локальная."""
    code, body = _post(api, "/auth/login", {"login": "loc", "password": "mypass123"})
    assert code == 200, body
    assert body.get("access_token") and body.get("role") == "student"


def test_issued_token_opens_the_cabinet(api):
    """Выданный токен обязан открывать `/web/*` ЭТОГО же сервера. Иначе человек «вошёл»,
    а кабинет отвечает «требуется авторизация» — ровно та форма входа во вкладке,
    которую уже ловили в 3.4."""
    _, body = _post(api, "/auth/login", {"login": "loc", "password": "mypass123"})
    assert _get(api, "/web/student/overview", body["access_token"]) == 200


def test_wrong_password_is_refused(api):
    code, _ = _post(api, "/auth/login", {"login": "loc", "password": "не тот"})
    assert code == 401


def test_error_does_not_reveal_whether_login_exists(api):
    """Ответ одинаков для «нет такого логина» и «пароль не тот»: разделение подсказало бы
    подбирающему, какие логины существуют."""
    _, a = _post(api, "/auth/login", {"login": "loc", "password": "не тот"})
    _, b = _post(api, "/auth/login", {"login": "нет-такого-человека", "password": "x"})
    assert a.get("detail") == b.get("detail")


def test_empty_fields_are_rejected(api):
    assert _post(api, "/auth/login", {"login": "", "password": ""})[0] == 400
    assert _post(api, "/auth/login", {"login": "loc", "password": ""})[0] == 400


def test_bridge_route_wins_over_spa_fallback(api):
    """Наш маршрут обязан стоять ПЕРВЫМ. Приложение раздаёт SPA заглушкой «всё
    остальное → index.html»; зарегистрируйся мост позже — сервер честно отвечал бы 200 и
    отдавал HTML вместо токена. Тем же приёмом решён bootstrap-маршрут."""
    import inspect
    src = inspect.getsource(local_api.install_login_bridge)
    assert "routes.insert(0" in src, "маршрут входа должен вставать в начало списка"


def test_local_check_runs_before_network(api):
    """Порядок ступеней закреплён в коде: локальная проверка ВЫШЕ обращения к серверу.
    Перестановка не ломает тесты выше (локальный вход всё равно сработает), но убивает
    offline-first — поэтому проверяем именно порядок."""
    import inspect
    src = inspect.getsource(local_api.install_login_bridge)
    assert src.index("_try_local_login") < src.index("_try_remote_login")


def test_successful_login_starts_sync_and_remembers_who(api):
    """После входа синхронизация обязана получить логин и роль: без этого кабинет открыт,
    а данные не обновляются — со стороны выглядит как «журнал завис на вчерашнем»."""
    _remembered.clear()
    _post(api, "/auth/login", {"login": "loc", "password": "mypass123"})
    assert ("loc", "student") in _remembered


def test_failed_login_remembers_nothing(api):
    """Неудачный вход не имеет права трогать сохранённую сессию: иначе опечатка в пароле
    выбрасывала бы человека из уже открытой сессии."""
    _remembered.clear()
    _post(api, "/auth/login", {"login": "loc", "password": "не тот"})
    assert _remembered == []


def test_password_is_not_persisted_by_the_bridge(api):
    """Инвариант §7: пароль не хранится. Мост передаёт его синхронизации В ПАМЯТЬ (ей он
    нужен, чтобы переполучать 5-часовой токен), но на диск не пишет."""
    import inspect
    src = inspect.getsource(_ORIGINAL_REMEMBER)
    assert "set_saved_session(login" in src, "сохраняем логин и роль"
    assert "password" not in src.split("set_saved_session")[1], "пароль на диск не уходит"
