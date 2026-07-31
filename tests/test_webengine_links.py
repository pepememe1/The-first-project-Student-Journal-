"""
test_webengine_links.py — внешние ссылки (window.open) из встроенных веб-видов.

Реальный найденный баг: у vue_shell.py (общий кабинет, «Сообщения» доступны через
собственную навигацию SPA — embed='nav') не было перехвата createWindow(), в отличие от
messenger_web.py (отдельная вкладка) — ссылка показывала подтверждение «Переадресация»,
но браузер не открывался, потому что QtWebEngine у window.open() без createWindow()
молча ничего не делает.

Инстанцировать QWebEnginePage без живого QApplication небезопасно (падает без питоновского
исключения — сам движок), поэтому проверяем СТРУКТУРУ (класс/метод есть) и то, что оба
потребителя реально ЗОВУТ install(), а не просто импортируют модуль — так же, как уже
проверяются другие Qt-детали в этом проекте (inspect.getsource, см. test_login_bridge.py).
"""
import inspect

import webengine_links


def test_external_link_page_class_has_create_window():
    cls = webengine_links.external_link_page_class()
    assert hasattr(cls, "createWindow")


def test_install_is_a_setpage_call():
    src = inspect.getsource(webengine_links.install)
    assert "setPage" in src


def test_messenger_web_calls_the_shared_install():
    import messenger_web
    src = inspect.getsource(messenger_web)
    assert "webengine_links.install(" in src


def test_vue_shell_calls_the_shared_install():
    """Регрессия на сам баг: vue_shell.py обязан перехватывать внешние ссылки, а не
    только messenger_web.py — «Сообщения» открываются и внутри его собственной
    QWebEngineView (embed='nav', меню SPA сохраняется)."""
    import vue_shell
    src = inspect.getsource(vue_shell)
    assert "webengine_links.install(" in src


def test_install_called_before_load_in_both_consumers():
    """setPage() ОБЯЗАН стоять ДО view.load(...) — переключение страницы уже загруженного
    view не имеет смысла (или сотрёт историю навигации)."""
    from messenger_web import MessengerWebPanel
    from vue_shell import VueShell
    for method in (MessengerWebPanel._build_web, VueShell._build_view):
        src = inspect.getsource(method)
        assert src.index("webengine_links.install(") < src.index("view.load(")
