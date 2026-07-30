"""
test_proxy_security.py — прокси онлайн-подсистем не должен стать чёрным ходом.

Зачем этот файл. Переписка не синхронизируется (§5.4), поэтому внутри программы чаты
берутся с боевого сервера, а пересылает запросы САМ локальный сервер — иначе браузер
зарежет их по CORS. Опасность в том, что при пересылке подставляется БОЕВОЙ токен
вошедшего: если не проверить, кто спрашивает, прокси отдаёт переписку любому, кто
дотянулся до петли. А дотянуться просто — это и любой процесс на компьютере, и обычная
страница в браузере пользователя (адрес 127.0.0.1 доступен любому сайту, то есть выходит
готовый CSRF: чужой сайт читает и пишет сообщения от лица человека).

Поэтому барьер тот же, что у остальных эндпоинтов локального сервера: свой токен, и
логин в нём обязан совпасть с логином текущей сессии.
"""
import pytest

import local_api


@pytest.fixture(autouse=True)
def _schema():
    """Токены пишутся в auth_sessions, поэтому таблицы нужны и здесь: без них выпуск
    сессии молча возвращает пустоту, и тест проверял бы «пустой токен не пускают» вместо
    заявленного."""
    local_api.prepare_env()
    from app import models  # noqa: F401 — без импорта моделей metadata пуста
    from app.db import Base, engine
    Base.metadata.create_all(bind=engine)


def _ok(auth: str) -> bool:
    return local_api._local_caller_ok(auth)


def test_no_token_is_rejected(monkeypatch):
    monkeypatch.setattr("sync_runner.current_login", lambda: "ivanov")
    assert _ok("") is False
    assert _ok("Bearer ") is False


def test_garbage_token_is_rejected(monkeypatch):
    """Подпись обязана проверяться: без неё «токен» подделывается текстовым редактором."""
    monkeypatch.setattr("sync_runner.current_login", lambda: "ivanov")
    assert _ok("Bearer garbage.token.here") is False


def test_token_of_another_user_is_rejected(monkeypatch):
    """Токен ПРОШЛОГО пользователя не должен открывать переписку нового — на общем
    компьютере колледжа это самый вероятный сценарий злоупотребления."""
    monkeypatch.setattr("sync_runner.current_login", lambda: "ivanov")
    other, _ = local_api.issue_local_session("petrov", "student")
    assert other, "тесту нужен настоящий подписанный токен"
    assert _ok(f"Bearer {other}") is False


def test_own_token_is_accepted(monkeypatch):
    monkeypatch.setattr("sync_runner.current_login", lambda: "ivanov")
    own, _ = local_api.issue_local_session("ivanov", "student")
    assert _ok(f"Bearer {own}") is True


def test_without_active_session_nothing_passes(monkeypatch):
    """Вход не выполнен — прокси закрыт целиком, даже с формально верным токеном:
    подставлять боевые права некому."""
    own, _ = local_api.issue_local_session("ivanov", "student")
    monkeypatch.setattr("sync_runner.current_login", lambda: "")
    assert _ok(f"Bearer {own}") is False


def test_proxy_only_covers_online_subsystems():
    """Прокси обязан касаться ТОЛЬКО онлайн-подсистем. Расширение на /web/student или
    /sync увело бы наружу то, что должно читаться из локальной копии, и тихо убило бы
    offline-first."""
    assert local_api._PROXY_PREFIXES == ("/web/messenger", "/messenger")
