"""
test_session_restore.py — программа не должна разлогинивать человека при каждом запуске.

Что здесь защищается. У каждого вошедшего СВОЯ копия базы (файл на логин), а локальный
сервер поднимается ДО того, как известно, кто войдёт. Пока логин брался только из ЖИВОЙ
сессии, на холодном старте он был пуст, сервер стартовал на «анонимной» копии, нужного
человека в ней не было — и оболочка честно открывала форму входа при целой сохранённой
сессии и целой личной копии.

Со стороны это выглядело как «программа каждый раз выкидывает из аккаунта и сбрасывает
тему»: тему отдаёт та же страница-передатчик, что и сессию, поэтому терялись обе.
"""
from desktop import local_api


class _FakeSettings:
    """Подмена настроек программы: НАСТОЯЩИЕ трогать нельзя — прогон тестов однажды уже
    затирал сохранённый вход разработчика выдуманным логином."""

    def __init__(self, login="", role="student"):
        self._data = {"login": login, "role": role} if login else {}

    def get_saved_session(self):
        return dict(self._data)


def _patch_settings(monkeypatch, login):
    import sys
    fake = _FakeSettings(login)
    monkeypatch.setattr("data.app_settings", fake)
    return fake


def test_saved_session_is_used_when_there_is_no_live_one(monkeypatch):
    """Холодный старт: живой сессии ещё нет, но человек уже входил на этой машине."""
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "")
    _patch_settings(monkeypatch, "ivanova")
    assert local_api._session_login() == "ivanova"


def test_live_session_wins_over_the_saved_one(monkeypatch):
    """Если вошёл ДРУГОЙ человек, работать надо с ним, а не с прошлым владельцем машины —
    иначе он увидел бы чужую копию базы."""
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "petrov")
    _patch_settings(monkeypatch, "ivanova")
    assert local_api._session_login() == "petrov"


def test_no_session_at_all_is_empty(monkeypatch):
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "")
    _patch_settings(monkeypatch, "")
    assert local_api._session_login() == ""


def test_cold_start_binds_the_personal_copy_not_the_anonymous_one(monkeypatch):
    """Главная проверка. Сервер обязан подняться на ЛИЧНОЙ копии сохранённого
    пользователя: на анонимной его нет, `user_exists` отвечает «нет», и человек получает
    форму входа вместо кабинета."""
    import os
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "")
    _patch_settings(monkeypatch, "ivanova")
    monkeypatch.delenv("GRADEBOOK_DB_URL", raising=False)
    monkeypatch.setattr(local_api, "ensure_server_path", lambda: None)
    monkeypatch.setattr(local_api, "_local_db_key", lambda: "")

    local_api.prepare_env()
    bound = os.environ["GRADEBOOK_DB_URL"]
    assert local_api.local_db_file("ivanova").replace("\\", "/") in bound
    assert local_api.local_db_file("").replace("\\", "/") not in bound, \
        "поднялись на анонимной копии — человек увидит форму входа"


def test_bootstrap_and_database_agree_on_who_is_working():
    """Страница-передатчик и выбор базы обязаны брать логин ИЗ ОДНОГО МЕСТА.

    Раньше они расходились: база смотрела на живую сессию, оболочка — на сохранённую.
    Совпадали они только после входа, то есть ровно тогда, когда проблемы и не было."""
    import inspect
    for fn in (local_api.prepare_env, local_api.install_desktop_bootstrap):
        src = inspect.getsource(fn)
        assert "_session_login" in src, f"{fn.__name__} берёт логин мимо общего источника"


# ── Почему онлайн-раздел недоступен ──────────────────────────────────────────────────
# Текст отказа тут важнее обычного: он решает, ЧТО человек пойдёт делать. «Нет связи»
# при живом интернете отправляет проверять провайдера, хотя истёк всего лишь токен.
def test_expired_session_is_not_called_a_network_problem():
    msg = local_api._offline_reason("/web/admin/server/metrics", "expired")
    assert "истекла" in msg and "войдите заново" in msg.lower()
    assert "Нет связи" not in msg
    # И сразу успокаиваем: offline-first цел, журнал работает.
    assert "Журнал" in msg


def test_network_failure_is_called_a_network_problem():
    msg = local_api._offline_reason("/web/admin/server/metrics", "offline")
    assert "Нет связи" in msg


def test_message_names_what_exactly_is_unavailable():
    """Раньше раздел состояния сервера сообщал «сервер сообщений не ответил» — человек
    шёл чинить мессенджер, которого не трогал."""
    assert "состояние" in local_api._offline_reason("/web/admin/server/metrics", "offline")
    assert "сообщения" in local_api._offline_reason("/web/messenger/chats", "expired")


def test_missing_address_asks_for_the_address():
    assert "Адрес" in local_api._offline_reason("/web/messenger/chats", "no-url")


def test_saved_tokens_are_used_when_there_is_no_live_session(monkeypatch):
    """Холодный старт: `sync_runner` креды получает только при входе, а программа,
    открытая по сохранённой сессии, входа не проходит. Пока фолбэка не было, все
    пересылаемые разделы отвечали «нет связи» при живом интернете."""
    import sys

    class _Settings:
        def get_api_url(self):
            return "https://example.test"

        def get_saved_session(self):
            return {"login": "ivanov", "role": "student"}

        def get_saved_token(self, login):
            return "живой-токен"

        def get_saved_refresh_token(self, login):
            return "refresh"

    monkeypatch.setattr("data.app_settings", _Settings())
    monkeypatch.setattr("sync.sync_runner.fresh_auth", lambda: ("https://example.test", ""))
    monkeypatch.setattr("sync.sync_client.is_token_expired", lambda t, skew_sec=30: False)

    base, token, why = local_api._remote_auth()
    assert base == "https://example.test"
    assert token == "живой-токен" and why == ""


def test_expired_saved_token_is_refreshed_and_stored(monkeypatch):
    """Обновлённый токен обязан СОХРАНИТЬСЯ: иначе обновление повторялось бы на каждый
    запрос, а пятичасовой токен протухает между запусками почти всегда."""
    import sys
    saved = {}

    class _Settings:
        def get_api_url(self):
            return "https://example.test"

        def get_saved_session(self):
            return {"login": "ivanov", "role": "student"}

        def get_saved_token(self, login):
            return saved.get("access", "старый")

        def get_saved_refresh_token(self, login):
            return "refresh"

        def set_saved_token(self, login, value):
            saved["access"] = value

        def set_saved_refresh_token(self, login, value):
            saved["refresh"] = value

    class _Client:
        def __init__(self, base, token, refresh):
            pass

        def refresh(self):
            return {"access_token": "новый", "refresh_token": "новый-refresh"}

    monkeypatch.setattr("data.app_settings", _Settings())
    monkeypatch.setattr("sync.sync_runner.fresh_auth", lambda: ("https://example.test", ""))
    monkeypatch.setattr("sync.sync_client.is_token_expired", lambda t, skew_sec=30: True)
    monkeypatch.setattr("sync.sync_client.SyncClient", _Client)

    base, token, why = local_api._remote_auth()
    assert token == "новый" and why == ""
    assert saved == {"access": "новый", "refresh": "новый-refresh"}


def test_rejected_refresh_is_reported_as_expired_not_offline(monkeypatch):
    """Сервер ответил 401 на refresh — это истёкшая сессия, а не пропавшая сеть.
    Разница видна человеку: в одном случае надо войти заново, в другом ждать связи."""
    import sys

    class _Settings:
        def get_api_url(self):
            return "https://example.test"

        def get_saved_session(self):
            return {"login": "ivanov", "role": "student"}

        def get_saved_token(self, login):
            return "старый"

        def get_saved_refresh_token(self, login):
            return "refresh"

    class _Client:
        def __init__(self, *a):
            pass

        def refresh(self):
            raise RuntimeError("401 Client Error: Unauthorized for url: /auth/refresh")

    monkeypatch.setattr("data.app_settings", _Settings())
    monkeypatch.setattr("sync.sync_runner.fresh_auth", lambda: ("https://example.test", ""))
    monkeypatch.setattr("sync.sync_client.is_token_expired", lambda t, skew_sec=30: True)
    monkeypatch.setattr("sync.sync_client.SyncClient", _Client)

    _base, token, why = local_api._remote_auth()
    assert not token and why == "expired"


# ── Срок жизни сохранённого входа (3.7.6) ─────────────────────────────────────────────
def test_saved_session_expires(monkeypatch):
    """🔥 НАСТОЯЩАЯ ДЫРА, найденная Ярославом на живой программе: «токен должен был
    сгореть, а я через неделю открываю программу и я в аккаунте админа».

    Механизм был такой: оболочка при запуске брала из настроек логин и роль и ВЫПИСЫВАЛА
    СЕБЕ НОВЫЙ локальный токен (`issue_local_session`), не спрашивая, жива ли ещё сессия.
    Серверный JWT при этом честно жил жёсткие 5 часов (§6) — но к локальной копии он
    отношения не имел, и журнал с настоящими ПДн студентов открывался кому угодно, кто
    запустил .exe на этом компьютере. На общем ПК колледжа это ровно та ситуация, ради
    которой 5 часов и вводили.

    Теперь у сохранённого входа есть СРОК. Он не ломает offline-first: пароль
    проверяется локально по хешу в личной копии, то есть войти заново можно и без сети.

    Обратный ход: убрать проверку срока в `app_settings.saved_session_alive` — краснеет.
    """
    from datetime import datetime, timedelta, timezone

    from data import app_settings

    long_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    monkeypatch.setattr(app_settings, "get_saved_session",
                        lambda: {"login": "admin", "role": "admin", "at": long_ago})
    assert app_settings.saved_session_alive() is False


def test_fresh_saved_session_is_alive(monkeypatch):
    """Обратная сторона: только что вошедшего программа не выкидывает."""
    from datetime import datetime, timezone

    from data import app_settings

    monkeypatch.setattr(app_settings, "get_saved_session",
                        lambda: {"login": "admin", "role": "admin",
                                 "at": datetime.now(timezone.utc).isoformat()})
    assert app_settings.saved_session_alive() is True


def test_session_without_timestamp_is_treated_as_expired(monkeypatch):
    """Записи БЕЗ метки времени остались от прежних версий. Считаем их истёкшими:
    иначе обновление программы сохранило бы вечный вход тем, у кого он уже есть, —
    то есть починка не подействовала бы ровно там, где дыра и живёт."""
    from data import app_settings

    monkeypatch.setattr(app_settings, "get_saved_session",
                        lambda: {"login": "admin", "role": "admin"})
    assert app_settings.saved_session_alive() is False


def test_bootstrap_does_not_hand_out_a_session_after_expiry(monkeypatch):
    """СТОРОЖ ВЫЗОВА: проверка обязана стоять на пути выдачи сессии в окно, а не просто
    существовать. Ровно этот класс дефекта («обещание без вызывающего») в проекте самый
    частый, и здесь он означал бы, что дыра осталась открытой при зелёном тесте выше."""
    import inspect

    src = inspect.getsource(local_api)
    assert "saved_session_alive" in src, "страница-передатчик не проверяет срок сессии"
