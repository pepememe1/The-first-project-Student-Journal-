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


def _no_saved_session(monkeypatch):
    """Убрать сохранённую сессию: НАСТОЯЩИЕ настройки в тестах не трогаем."""
    import sys

    class _Empty:
        def get_saved_session(self):
            return {}

    monkeypatch.setitem(sys.modules, "app_settings", _Empty())


def test_without_any_session_nothing_passes(monkeypatch):
    """Вход не выполнялся ВООБЩЕ — прокси закрыт целиком, даже с формально верным
    токеном: подставлять боевые права некому."""
    own, _ = local_api.issue_local_session("ivanov", "student")
    monkeypatch.setattr("sync_runner.current_login", lambda: "")
    _no_saved_session(monkeypatch)
    assert _ok(f"Bearer {own}") is False


def test_saved_session_passes_on_cold_start(monkeypatch):
    """Холодный старт: живой сессии ещё нет, но человек уже входил на этой машине.

    Раньше здесь был отказ — и это ломало не безопасность, а вход: страница-передатчик
    выпускала токен для сохранённого пользователя, прокси отвечал 401, страница
    трактовала 401 как «сессия истекла» и выкидывала человека из аккаунта."""
    import sys

    class _Saved:
        def get_saved_session(self):
            return {"login": "ivanov", "role": "student"}

    own, _ = local_api.issue_local_session("ivanov", "student")
    monkeypatch.setattr("sync_runner.current_login", lambda: "")
    monkeypatch.setitem(sys.modules, "app_settings", _Saved())
    assert _ok(f"Bearer {own}") is True
    #Строгость не упала: чужой логин не проходит и по сохранённой сессии.
    other, _ = local_api.issue_local_session("petrov", "student")
    assert _ok(f"Bearer {other}") is False


#Пути, которые обязаны читаться из ЛОКАЛЬНОЙ копии. Пересылка любого из них наружу
#убивает offline-first молча: в сети всё работает, а без сети журнал становится пустым —
#и заметят это в аудитории, а не на разработке.
_MUST_STAY_LOCAL = (
    "/web/student", "/web/teacher", "/web/parent", "/web/curator", "/web/admin/students",
    "/web/admin/groups", "/web/admin/teachers", "/web/schedule", "/web/terms",
    #⚠️ «Вектор» обязан отвечать ОФЛАЙН — это его главное обещание. Внутри программы он
    #работает через ЛОКАЛЬНЫЙ сервер (тот же server/app, та же функция
    #web.py::answer_vector_question, что и на бою), поэтому пересылать /web/vector на VPS
    #нельзя: без интернета помощник просто замолчал бы. Сюда же попадает /vector/stt —
    #звук распознаёт локальная машина, и он не должен покидать ПК (152-ФЗ).
    "/web/vector",
    "/sync", "/auth", "/me",
)


def test_proxy_never_covers_offline_capable_data():
    """Прокси обязан касаться ТОЛЬКО онлайн-подсистем.

    Проверяем не точный список префиксов, а СВОЙСТВО: ни один путь, который должен
    читаться локально, не должен попадать под пересылку. Точное сравнение кортежа
    ломалось на каждом законном добавлении и подталкивало «просто обновить ожидание» —
    то есть ровно к тому, от чего оно защищало."""
    for path in _MUST_STAY_LOCAL:
        assert not path.startswith(local_api._PROXY_PREFIXES), \
            f"{path} уехал бы на сервер — offline-first сломан"


def test_proxied_prefixes_are_all_online_only():
    """Обратная сторона: каждый пересылаемый префикс обязан быть онлайн-подсистемой.

    Мессенджер (§5.4) данных в локальной копии не имеет по замыслу. Раздел «Сервер»
    рассказывает про БОЕВУЮ машину — локально о ней знать нечего, и без пересылки он
    показывал диск и базу компьютера администратора вместо VPS."""
    assert set(local_api._PROXY_PREFIXES) == {
        "/web/messenger", "/messenger", "/web/admin/server"}
