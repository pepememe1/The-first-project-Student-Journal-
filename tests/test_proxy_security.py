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

from desktop import local_api


@pytest.fixture(autouse=True)
def _schema():
    """Токены пишутся в auth_sessions, поэтому таблицы нужны и здесь: без них выпуск
    сессии молча возвращает пустоту, и тест проверял бы «пустой токен не пускают» вместо
    заявленного."""
    local_api.prepare_env()
    from app import models  # noqa: F401 — без импорта моделей metadata пуста
    from app.db import Base, engine
    Base.metadata.create_all(bind=engine)
    #Люди, чьи токены выпускают тесты ниже, обязаны существовать в копии: с 3.7.7
    #`issue_local_session` не выписывает сессию тому, кого в базе нет (мёртвый токен —
    #это «вошёл и через секунду выкинуло», см. tests/test_desktop_first_login.py).
    _seed_users("ivanov", "petrov")


def _seed_users(*logins):
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        for lg in logins:
            db.merge(User(id=f"stud:{lg}", login=lg, role="student", surname="Тестов",
                          name="Тест", deleted=False,
                          updated_at="2026-08-19T00:00:00+00:00"))
        db.commit()
    finally:
        db.close()


def _ok(auth: str) -> bool:
    return local_api._local_caller_ok(auth)


def test_no_token_is_rejected(monkeypatch):
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "ivanov")
    assert _ok("") is False
    assert _ok("Bearer ") is False


def test_garbage_token_is_rejected(monkeypatch):
    """Подпись обязана проверяться: без неё «токен» подделывается текстовым редактором."""
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "ivanov")
    assert _ok("Bearer garbage.token.here") is False


def test_token_of_another_user_is_rejected(monkeypatch):
    """Токен ПРОШЛОГО пользователя не должен открывать переписку нового — на общем
    компьютере колледжа это самый вероятный сценарий злоупотребления."""
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "ivanov")
    other, _ = local_api.issue_local_session("petrov", "student")
    assert other, "тесту нужен настоящий подписанный токен"
    assert _ok(f"Bearer {other}") is False


def test_own_token_is_accepted(monkeypatch):
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "ivanov")
    own, _ = local_api.issue_local_session("ivanov", "student")
    assert _ok(f"Bearer {own}") is True


def _no_saved_session(monkeypatch):
    """Убрать сохранённую сессию: НАСТОЯЩИЕ настройки в тестах не трогаем."""
    import sys

    class _Empty:
        def get_saved_session(self):
            return {}

    monkeypatch.setattr("data.app_settings", _Empty())


def test_without_any_session_nothing_passes(monkeypatch):
    """Вход не выполнялся ВООБЩЕ — прокси закрыт целиком, даже с формально верным
    токеном: подставлять боевые права некому."""
    own, _ = local_api.issue_local_session("ivanov", "student")
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "")
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
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "")
    monkeypatch.setattr("data.app_settings", _Saved())
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
    #⚠️ `/me` ЗДЕСЬ БОЛЬШЕ НЕТ, и это не недосмотр. Он стоял в списке, когда под ним не
    #пересылалось ничего, но в 3.6.7 `/me/prefs` и `/me/events` СОЗНАТЕЛЬНО отправлены на
    #бой: `User.prefs` не синкается, `NotifyEvent` не в SYNC_MODELS, а `PUSH_SCOPE` у
    #teacher/student не включает "users" — то есть правки профиля и темы, сделанные внутри
    #программы, физически не могли доехать до сайта и терялись. Третий путь под `/me` —
    #`/me/push-token` — онлайновый по своей природе (регистрация токена устройства).
    #Офлайн-способных данных под `/me` не осталось, поэтому запись убрана целиком, а не
    #обвешана исключениями: список исключений к сторожу быстро становится сторожем в
    #никуда. Противоречие поймал `test_proxied_and_local_paths_never_overlap` ниже.
    "/sync", "/auth",
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


#Заведомо ОНЛАЙН-подсистемы: их данных в локальной копии нет и быть не может, поэтому
#внутри программы единственный источник правды для них — бой. Ключ — КОРЕНЬ подсистемы,
#значение — почему она онлайновая (причина проверяется человеком на ревью, не машиной).
_ONLINE_ONLY_SUBSYSTEMS = {
    "/web/messenger": "переписка сознательно вне SYNC_MODELS (§5.4) — локально её нет",
    "/messenger": "тот же мессенджер, короткий префикс WS/служебных путей",
    "/web/admin/server": "раздел «Сервер» рассказывает про БОЕВУЮ машину; без пересылки "
                         "показывал бы диск и базу компьютера администратора вместо VPS",
    "/me/prefs": "User.prefs не синкается, а PUSH_SCOPE у teacher/student не включает "
                 "'users' — правки темы/профиля физически не смогли бы доехать до сайта",
    "/me/events": "NotifyEvent не в SYNC_MODELS — вкладка «Уведомления» локально пуста",
    "/web/staff/parents": "ParentLink не в SYNC_MODELS",
    "/web/staff/parent-links": "ParentLink не в SYNC_MODELS",
    "/web/admin/parents": "ParentLink не в SYNC_MODELS",
    "/web/admin/registrations": "RegistrationRequest не в SYNC_MODELS, а одобрение заявки "
                                "СОЗДАЁТ пользователя и шлёт письмо — выполнить это против "
                                "локального зеркала значит завести фантомный аккаунт",
    "/connect": "одобрение УСТРОЙСТВ живёт только на боевом сервере: список ожидающих "
                "машин и белый список одобренных — серверные таблицы, в локальной копии "
                "их нет и быть не может. Без пересылки администратор в программе видел "
                "бы пустой список и не мог одобрить ничью машину",
    "/web/admin/zet-thresholds": "РЕДАКТОР порогов: сами пороги синкаются (ZetThreshold в "
                                 "SYNC_MODELS), но у Phase B-записи нет обратного пути из "
                                 "local_app.db на бой — сохранённый порог потерялся бы молча",
}


def test_proxied_prefixes_are_all_online_only():
    """Обратная сторона: каждый пересылаемый префикс обязан быть онлайн-подсистемой.

    ⚠️ ПРОВЕРЯЕМ СВОЙСТВО, А НЕ РАВЕНСТВО СПИСКУ. Здесь раньше стояло точное сравнение
    множества с тремя префиксами — и оно покраснело от законных правок 3.6.7, где к
    пересылке добавили ещё пять. Это ровно та ошибка, которую высмеивает докстринг
    соседнего теста: сравнение с точным кортежем ломается на каждом честном добавлении и
    подталкивает «просто обновить ожидание», то есть обесценивает сторожа.

    Свойство: каждый пересылаемый путь обязан лежать ВНУТРИ заведомо онлайн-подсистемы с
    записанной причиной. Расширение уже признанной подсистемы (`/web/messenger/gifs`,
    `/me/events/unread-count`) теста не трогает. Появление НОВОГО корня — падает, и это
    правильный момент задуматься: у этих данных точно нет офлайн-источника?"""
    roots = tuple(_ONLINE_ONLY_SUBSYSTEMS)
    for prefix in local_api._PROXY_PREFIXES:
        assert prefix.startswith(roots), (
            f"{prefix} пересылается на бой, но не относится ни к одной онлайн-подсистеме. "
            f"Если данных этого пути действительно нет в локальной копии — допишите корень "
            f"и ПРИЧИНУ в _ONLINE_ONLY_SUBSYSTEMS. Если есть — путь пересылать нельзя: "
            f"внутри программы он должен читаться офлайн.")


def test_proxied_and_local_paths_never_overlap():
    """Списки офлайн-путей и пересылаемых подсистем не должны пересекаться ни в одну
    сторону. Проверка дешёвая, но ловит опечатку в префиксе раньше, чем она превратится
    в «в аудитории журнал пустой»: перекрытие означает, что один и тот же путь считается
    одновременно офлайн-способным и онлайн-только."""
    for prefix in local_api._PROXY_PREFIXES:
        for local_path in _MUST_STAY_LOCAL:
            assert not local_path.startswith(prefix), \
                f"{local_path} обязан читаться локально, но попал под пересылку {prefix}"
            assert not prefix.startswith(local_path), \
                f"пересылаемый {prefix} лежит внутри офлайн-пути {local_path}"
