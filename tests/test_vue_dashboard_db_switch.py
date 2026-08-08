"""
test_vue_dashboard_db_switch.py — общий Vue-кабинет обязан переключить локальную базу
на копию ВОШЕДШЕГО человека, а не только веб-форма входа.

Найденный на живых данных баг: запасная Qt-оболочка (WebView2 недоступен) поднимает
локальный сервер общего кабинета ФОНОМ ещё ДО входа (main.py::_start_local_api_background)
— он остаётся привязан к «анонимной» копии базы. Веб-форма входа сама переключает базу
на личную копию (local_api.install_login_bridge → switch_user_db), но нативная форма Qt —
нет. Кабинет открывается и выглядит рабочим, но пишет не в ту копию: правки (например,
группы в админке) молча оседают в «анонимном» файле и пропадают после следующего
перезапуска (тот подберёт уже ПРАВИЛЬНУЮ копию по сохранённой сессии).

main_window.py::_try_vue_dashboard теперь переключает базу сам — тем же вызовом, что и
веб-мост — перед тем как открыть кабинет, независимо от того, как прошёл вход.
"""
import main_window


def test_try_vue_dashboard_switches_to_logged_in_user_copy(monkeypatch):
    calls = []
    import app_settings
    import local_api
    import vue_dashboard

    monkeypatch.setattr(app_settings, "get_saved_session",
                        lambda: {"login": "admin", "role": "admin"})
    monkeypatch.setattr(local_api, "switch_user_db", lambda login: calls.append(login) or True)
    monkeypatch.setattr(vue_dashboard, "available_for", lambda role: True)

    class _StubDash:
        ok = True

        def __init__(self, role, parent=None, context=None, on_logout=None):
            pass

    monkeypatch.setattr(vue_dashboard, "VueDashboard", _StubDash)

    dash = main_window.MainAppWindow._try_vue_dashboard("admin")

    assert dash is not None
    assert calls == ["admin"], "база обязана переключиться на копию вошедшего до открытия кабинета"


def test_try_vue_dashboard_switch_failure_does_not_block_cabinet(monkeypatch):
    """Переключение — best-effort: сбой (сеть/файл занят) не имеет права оставить
    человека без кабинета, только без гарантии писать в ту копию."""
    import app_settings
    import local_api
    import vue_dashboard

    monkeypatch.setattr(app_settings, "get_saved_session",
                        lambda: {"login": "admin", "role": "admin"})

    def _boom(login):
        raise RuntimeError("нет сети")
    monkeypatch.setattr(local_api, "switch_user_db", _boom)
    monkeypatch.setattr(vue_dashboard, "available_for", lambda role: True)

    class _StubDash:
        ok = True

        def __init__(self, role, parent=None, context=None, on_logout=None):
            pass

    monkeypatch.setattr(vue_dashboard, "VueDashboard", _StubDash)

    dash = main_window.MainAppWindow._try_vue_dashboard("admin")
    assert dash is not None, "сбой переключения базы не должен закрывать общий кабинет"


def test_try_vue_dashboard_skips_switch_without_saved_login(monkeypatch):
    """Нет сохранённой сессии (например, самый первый холодный старт) — переключать
    нечего, но кабинет всё равно должен пытаться открыться как раньше."""
    import app_settings
    import local_api
    import vue_dashboard

    monkeypatch.setattr(app_settings, "get_saved_session", lambda: {})
    calls = []
    monkeypatch.setattr(local_api, "switch_user_db", lambda login: calls.append(login))
    monkeypatch.setattr(vue_dashboard, "available_for", lambda role: True)

    class _StubDash:
        ok = True

        def __init__(self, role, parent=None, context=None, on_logout=None):
            pass

    monkeypatch.setattr(vue_dashboard, "VueDashboard", _StubDash)

    dash = main_window.MainAppWindow._try_vue_dashboard("admin")
    assert dash is not None
    assert calls == [], "без сохранённого логина switch_user_db не вызывается вовсе"


def test_bootstrap_binds_db_before_issuing_session(monkeypatch):
    """Страница-передатчик сама привязывает базу к тому, ЧЬЮ сессию выдаёт.

    Почему это отдельный тест, хотя выше уже проверен `main_window`. Точечная починка
    ОДНОГО вызывающего (3.5.4) оставила мину следующему: `/desktop/bootstrap` — то самое
    место, где сессия уходит в оболочку, и единственное, которое знает, чья она, — само
    привязку не обеспечивало. Основная оболочка (WebView2, `webview2_app._start_url` →
    `bootstrap_url`) переключения не делает вовсе и держалась на том, что сервер угадал
    привязку при старте. Теперь гарантия выполняется по построению, и порядок важен:
    переключить базу ОБЯЗАНЫ до выпуска токена, иначе сессия окажется валидной для одной
    копии, а сервер будет читать другую.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import local_api

    order = []
    monkeypatch.setattr(local_api, "_session_login", lambda: "ivanov")
    monkeypatch.setattr(local_api, "switch_user_db",
                        lambda login: order.append(("switch", login)) or True)
    monkeypatch.setattr(local_api, "issue_local_session",
                        lambda login, role: order.append(("issue", login)) or ("acc", "ref"))
    import app_settings
    monkeypatch.setattr(app_settings, "get_saved_session",
                        lambda: {"login": "ivanov", "role": "teacher"})

    app = FastAPI()
    local_api.install_desktop_bootstrap(app)
    resp = TestClient(app).get("/desktop/bootstrap", params={"route": "/teacher"})

    assert resp.status_code == 200
    assert order == [("switch", "ivanov"), ("issue", "ivanov")], (
        f"база обязана быть привязана ДО выпуска сессии, получено: {order}")
