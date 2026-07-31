"""
webengine_links.py — внешние ссылки (window.open) из встроенного веб-вида в СИСТЕМНЫЙ
браузер, а не в никуда.

Общий для ВСЕХ QWebEngineView в приложении: раньше жил только в messenger_web.py, но
«один интерфейс» (§11) открывает ту же переписку и через vue_shell.py (общий кабинет,
пункт меню «Сообщения» внутри SPA-навигации, embed='nav') — у него была своя, ОТДЕЛЬНАЯ
QWebEngineView без этого перехвата. Со стороны это выглядело как «предупреждение
"Переадресация" показывается, а браузер не открывается»: без переопределения
createWindow() у QWebEnginePage клик по ссылке (после window.open()) молча ничего не
делает — второго окна QtWebEngine у нас нет, и Chromium это просто проглатывает.

Видео-эмбеды (<iframe> youtube.com/vk.com/rutube.ru) сюда не попадают — это обычная
навигация ВНУТРИ той же страницы, createWindow() при ней не вызывается.
"""


def external_link_page_class():
    """Класс QWebEnginePage, чей createWindow() отдаёт одноразовую страницу-ловушку:
    та перехватывает целевой URL через urlChanged и открывает его SYSTEM'ным браузером
    (QDesktopServices.openUrl), сама никогда не рендерится."""
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtGui import QDesktopServices

    class _ExternalLinkPage(QWebEnginePage):
        def __init__(self, profile, parent=None):
            super().__init__(profile, parent)
            self.urlChanged.connect(self._open_externally)

        def _open_externally(self, url):
            QDesktopServices.openUrl(url)
            self.deleteLater()

    class _ExternalLinkAwarePage(QWebEnginePage):
        def createWindow(self, _window_type):
            return _ExternalLinkPage(self.profile(), self)

    return _ExternalLinkAwarePage


def install(view) -> None:
    """Подменить page() у УЖЕ созданного QWebEngineView на страницу с перехватом внешних
    ссылок. Вызывать ДО view.load(...) — как и любой setPage()."""
    page_cls = external_link_page_class()
    view.setPage(page_cls(view))
