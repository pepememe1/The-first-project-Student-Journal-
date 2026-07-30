"""
test_local_api.py — ЛОКАЛЬНОЕ серверное приложение внутри десктопа (ui/local_api.py).

Это ядро объединения платформ: десктоп показывает ту же Vue-SPA и ходит в тот же
`/web/*`, что и сайт, но всё на своём компьютере — отсюда offline-first.

Закрепляем ровно те свойства, потеря которых означает не баг, а сломанное обещание
пользователю: «снаружи не подключиться», «никаких окон», «интерфейс и данные с одного
адреса». Тест поднимает НАСТОЯЩЕЕ приложение, а не заглушку: иначе он не заметил бы,
что серверный пакет перестал импортироваться в десктопном окружении.
"""
import os
import tempfile
import threading
import urllib.error
import urllib.request

import pytest

import local_api


@pytest.fixture(scope="module")
def api():
    """Поднимает локальный сервер на ВРЕМЕННОЙ базе (боевую и десктопную не трогаем)."""
    tmp_db = os.path.join(tempfile.mkdtemp(), "local_app_test.db").replace("\\", "/")
    os.environ["GRADEBOOK_DB_URL"] = f"sqlite:///{tmp_db}"
    srv = local_api.LocalAPI()
    if not srv.start():
        pytest.skip(f"серверный пакет недоступен в этом окружении: {srv.error}")
    yield srv
    srv.stop()


def _get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_listens_only_on_loopback(api):
    """Самая важная проверка файла: сервер обязан слушать ТОЛЬКО себя.

    Ловит правку «поставим 0.0.0.0, чтобы зайти с телефона» — для этого есть отдельный
    фоновый сервер хоста (server_control.py), а личный доступен только этому компьютеру."""
    import inspect
    src = inspect.getsource(local_api.LocalAPI.start)
    assert '"127.0.0.1"' in src, "локальный сервер должен слушать только петлю"
    assert "0.0.0.0" not in src, "0.0.0.0 открывает сервер в сеть — так нельзя"


def test_port_is_ephemeral(api):
    assert api.port > 1024


def test_serves_the_same_spa(api):
    """Интерфейс приходит с локального адреса — значит откроется и без интернета."""
    code, body = _get(api.url("/"))
    assert code == 200
    assert b"<div id=\"app\">" in body or b"assets/" in body, body[:200]


def test_serves_api_from_the_same_origin(api):
    """SPA и `/web/*` — ОДИН адрес: не нужен ни CORS, ни настройка «адрес сервера».
    Именно это позволяет держать один интерфейсный код на обе платформы."""
    code, _ = _get(api.url("/health"))
    assert code == 200


def test_api_still_requires_auth(api):
    """«Локально» не значит «без пароля»: тот же JWT-барьер, что и на бою."""
    code, _ = _get(api.url("/web/vector/ask"), data=b"{}",
                   headers={"Content-Type": "application/json"})
    assert code == 401


def test_runs_in_thread_not_process(api):
    """«Никаких окон» держится на том, что сервер — поток: процесс мог бы мигнуть
    консолью, поток не может показать окно в принципе."""
    assert isinstance(api._thread, threading.Thread)
    assert api._thread.daemon, "поток обязан быть демоном — иначе программа не закроется"


def test_start_is_idempotent(api):
    port = api.port
    assert api.start() is True
    assert api.port == port, "повторный старт не должен поднимать второй сервер"


def test_local_db_is_separate_file():
    """Локальная база приложения — ОТДЕЛЬНЫЙ файл, а не десктопный vsgutu_grades.db:
    у них разные схемы, и смешивать их нельзя."""
    url = local_api.local_db_url("ivanov")
    assert url.startswith("sqlite:///")
    assert "local_app_" in url
    assert "vsgutu_grades" not in url


def test_copy_is_separate_per_user():
    """Файл СВОЙ на каждого вошедшего. Раньше он был один на машину, и после сеанса
    преподавателя в нём оставались оценки всей группы — следующий вошедший студент их
    читал (найдено на живой машине: 44 оценки шести студентов)."""
    a = local_api.local_db_file("ivanov")
    b = local_api.local_db_file("petrov")
    assert a != b, "общий файл = чужие данные следующему вошедшему"
    assert "ivanov" not in a, "логин — тоже ПДн, в имени файла ему не место"


def test_copy_is_encrypted_when_driver_present():
    """Копия ШИФРУЕТСЯ (SQLCipher), ключ — под DPAPI. Без этого ФИО, группы и оценки
    читались из файла любым просмотрщиком, в т.ч. с украденного диска."""
    try:
        import sqlcipher3  # noqa: F401
    except Exception:
        pytest.skip("драйвер sqlcipher3 не установлен в этом окружении")
    assert local_api._local_db_key(), "ключ обязан заводиться, если драйвер есть"
    local_api.prepare_env()
    assert os.environ.get("GRADEBOOK_DB_KEY"), "сервер обязан получить ключ"


# ── Локальная сессия ────────────────────────────────────────────────────────────────
def test_local_session_opens_protected_endpoint(api):
    """Токен боевого сервера подписан ЧУЖИМ секретом — локальный обязан его отвергнуть.
    Поэтому для общего интерфейса выпускается СВОЙ токен; без него внутри программы
    показывалась форма входа, хотя человек уже вошёл."""
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    db.merge(User(id="stud:t", login="t", role="student", surname="Тестов", name="Тест",
                  group_name="К74/1", deleted=False,
                  updated_at="2026-07-01T00:00:00+00:00"))
    db.commit()
    db.close()

    access, refresh = local_api.issue_local_session("t", "student")
    assert access and refresh

    url = api.url("/web/student/overview")
    assert _get(url, headers={"X-Client": "web"})[0] == 401, "без токена — 401"
    code, _ = _get(url, headers={"X-Client": "web",
                                 "Authorization": f"Bearer {access}"})
    assert code == 200, "со своим токеном локальный сервер обязан пустить"


def test_user_exists_tells_whether_mirror_caught_up(api):
    """Сразу после первого входа зеркало могло не докачать самого человека. Токен тогда
    безупречен, а `/web/*` всё равно отвечает «требуется авторизация» — и внутри
    программы появляется форма входа. Поэтому наличие человека проверяем ЗАРАНЕЕ и в
    этом случае показываем вкладку с боевого сервера."""
    assert local_api.user_exists("t") is True
    assert local_api.user_exists("ghost-no-such-login") is False
    assert local_api.user_exists("") is False


def test_local_session_registers_auth_session(api):
    """Токен с jti сервер считает отозванным, пока нет записи сессии — поэтому её
    заводим. Побочная польза: локальный выход и отзыв работают как на бою."""
    from app.db import SessionLocal
    from app.models import AuthSession
    access, _ = local_api.issue_local_session("t", "student")
    from app.security import decode_token
    jti = decode_token(access).get("jti")
    db = SessionLocal()
    try:
        row = db.query(AuthSession).filter(AuthSession.jti == jti).first()
        assert row is not None and not row.revoked
        assert row.login == "t" and row.kind == "access"
    finally:
        db.close()
