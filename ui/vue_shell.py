"""
vue_shell.py — показ ОБЩЕГО Vue-интерфейса внутри десктопа.

Здесь та же Vue-SPA, что и на сайте, открывается со СВОЕГО адреса 127.0.0.1, а не с
боевого домена. Разница принципиальная и ровно ради offline-first: страница, взятая с
сайта, без интернета не откроется вообще, а взятая со своего компьютера — откроется
всегда.

ДВА ИСТОЧНИКА, в порядке предпочтения:
  1. `local_api` — НАСТОЯЩЕЕ серверное приложение, запущенное на этом компьютере. Отдаёт
     и SPA, и `/web/*` с ОДНОГО адреса, поэтому интерфейс и данные приходят с одного
     origin (без CORS и без «адреса сервера»), а офлайн работает целиком. Главный путь.
  2. `local_ui_server` — только статика Vue, данные с боевого сервера. Запасной путь на
     случай, если серверный пакет рядом недоступен: интерфейс всё равно откроется.

⚠️ ОТЛИЧИЕ ОТ `ui/messenger_web.py`. Тот встраивает SPA с БОЕВОГО сервера и годится
только онлайн-разделам (мессенджер и модерация — они и так без сети бессмысленны).
Этот модуль — дорога к тому, чтобы на Vue переехал ВЕСЬ интерфейс, включая офлайн-разделы.
Пока оба сосуществуют: messenger_web остаётся рабочим, пока переезд не завершён —
одномоментная замена сломала бы журнал у всех сразу.
"""
import json

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

import log

_LOG = log.get("vue_shell")


class VueShell(QWidget):
    """Вкладка десктопа, показывающая маршрут общей Vue-SPA.

    route — путь внутри SPA («/student/journal»); role — роль для роут-гарда SPA.
    embed=True прячет собственный сайдбар SPA (когда вокруг есть нативная навигация)."""

    def __init__(self, route: str, role: str, parent=None, embed: bool = True):
        super().__init__(parent)
        self._route = route
        self._role = role
        self._embed = bool(embed)
        self._view = None
        self.ok = False        #удалось ли показать интерфейс (иначе — нативный запасной)
        self._source = ""      #откуда взят интерфейс: local_api | static
        self._api_base = ""    #куда SPA ходит за данными ('' = тот же origin)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._build()

    def _message(self, text: str):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        self._lay.addWidget(lbl)

    def _build(self):
        """Выбираем источник интерфейса.

        ОСНОВНОЙ путь — локальное серверное приложение (`local_api`): оно отдаёт и SPA,
        и `/web/*` с ОДНОГО адреса, поэтому интерфейс и данные живут на одном origin, а
        офлайн работает целиком. ЗАПАСНОЙ — статическая раздача (`local_ui_server`):
        если серверный пакет почему-то недоступен, интерфейс всё равно откроется и
        возьмёт данные с боевого сервера, как раньше."""
        api = self._start_local_api()
        if api is not None:
            self._source = "local_api"
            #Один origin: адрес API не задаём вовсе — SPA пойдёт к тому же серверу,
            #с которого её саму и отдали.
            self._api_base = ""
            #Токены — ЛОКАЛЬНЫЕ: боевой подписан чужим секретом, и этот сервер обязан
            #его отвергнуть (см. issue_local_session). Без этого общий интерфейс внутри
            #программы показывал форму входа, хотя человек уже вошёл.
            try:
                import local_api as _la
                self._local_tokens = _la.issue_local_session(self._current_login(), self._role)
            except Exception:
                self._local_tokens = ("", "")
            try:
                self._build_view(api.url(self._route), token_cookie="", token="")
                self.ok = True
                return
            except Exception as e:
                _LOG.warning(f"[vue-shell] веб-вид поверх локального API не собрался: {e}")

        from local_ui_server import instance, TOKEN_COOKIE
        srv = instance()
        if not srv.start():
            #Собранного Vue рядом нет (запуск из исходников без `npm run build`).
            #Это не авария: значит десктоп просто продолжает жить на нативных экранах.
            self._message("Интерфейс не собран. Выполните «npm run build» в папке web "
                          "или используйте нативные вкладки.")
            return
        self._source = "static"
        #Статическая раздача данных не отдаёт — за ними SPA идёт на боевой сервер.
        self._api_base = self._remote_base()
        try:
            self._build_view(srv.url(self._route), TOKEN_COOKIE, srv.token)
            self.ok = True
        except Exception as e:
            _LOG.warning(f"[vue-shell] веб-вид не собрался: {e}")
            self._message("Не удалось открыть интерфейс. Работают нативные вкладки.")

    @staticmethod
    def _start_local_api():
        """Локальное серверное приложение (или None, если поднять не удалось)."""
        try:
            import local_api
            api = local_api.instance()
            return api if api.start() else None
        except Exception as e:
            _LOG.warning(f"[vue-shell] локальный API недоступен: {e}")
            return None

    @staticmethod
    def _current_login() -> str:
        """Логин вошедшего пользователя — берём из боевого JWT (claim sub)."""
        try:
            from sync_runner import fresh_auth
            from ui.messenger_web import _decode_login
            return _decode_login(fresh_auth()[1] or "")
        except Exception:
            return ""

    @staticmethod
    def _remote_base() -> str:
        try:
            from sync_runner import fresh_auth
            return fresh_auth()[0] or ""
        except Exception:
            return ""

    def _build_view(self, url: str, token_cookie: str = "", token: str = ""):
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import (QWebEngineScript, QWebEngineSettings,
                                             QWebEngineProfile)
        from PySide6.QtNetwork import QNetworkCookie

        view = QWebEngineView(self)
        #Своё меню Chromium («Назад/Обновить/Посмотреть код») выдаёт обёртку и перебивает
        #меню приложения — отдаём ПКМ странице (как в messenger_web).
        view.setContextMenuPolicy(Qt.NoContextMenu)
        #Доступ к буферу обмена: без него «Копировать» в SPA молча не работает
        #(QtWebEngine запрещает его по умолчанию — этот баг мы уже ловили в 3.3).
        try:
            s = view.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)
        except Exception:
            pass
        #Фон под тему: иначе на тёмной теме при открытии вспыхивает белый холст.
        try:
            from PySide6.QtGui import QColor
            from styles import C
            view.page().setBackgroundColor(QColor(C.get("bg", "#ffffff")))
        except Exception:
            pass

        #ТОКЕН СТАТИЧЕСКОЙ РАЗДАЧИ — кукой (нужен только запасному пути). Заголовок тут
        #не годится: за скриптами, стилями и картинками браузер ходит сам, и наш
        #заголовок к этим запросам не подставится, а без токена статический сервер их
        #отклонит (см. local_ui_server._token_ok). У локального API своя защита — JWT,
        #поэтому там кука не нужна.
        if token_cookie and token:
            profile = view.page().profile()
            cookie = QNetworkCookie(token_cookie.encode(), token.encode())
            cookie.setDomain("127.0.0.1")
            cookie.setPath("/")
            #HttpOnly НЕ ставим: кука должна уходить с обычными запросами страницы, а не
            #читаться из JS — на её секретность это не влияет (страница и так наша).
            profile.cookieStore().setCookie(cookie, QUrl(url))

        #Сессия/тема/флаги — в localStorage ДО загрузки страницы, иначе роут-гард SPA
        #успеет увести на форму входа. Тот же приём, что в messenger_web.
        script = QWebEngineScript()
        script.setName("gb-vue-shell-bootstrap")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(self._bootstrap_js())
        view.page().scripts().insert(script)

        view.load(QUrl(url))
        self._lay.addWidget(view)
        self._view = view

    def _bootstrap_js(self) -> str:
        """JS, выполняемый до загрузки SPA: сессия, тема, режим встраивания, адрес API."""
        access = refresh = login = ""
        base = ""
        try:
            from sync_runner import fresh_auth
            base, access = fresh_auth()
        except Exception:
            base = ""
        try:
            from ui.messenger_web import _decode_login       # noqa: WPS436 — общий разбор JWT
            login = _decode_login(access)
        except Exception:
            login = ""
        try:
            import app_settings
            refresh = app_settings.get_saved_refresh_token(login) or ""
        except Exception:
            refresh = ""
        theme_js = ""
        try:
            import themes
            spec = themes.active_spec()
            if spec:
                theme_js = f"localStorage.setItem('gb.theme',{json.dumps(json.dumps(spec))});"
        except Exception:
            pass
        user = json.dumps({"login": login, "role": self._role, "name": login})
        #`gb.api_base` — КУДА SPA ходит за данными (ключ задан в web/src/api/server.js).
        #Задать его здесь ОБЯЗАТЕЛЬНО: страница открыта с 127.0.0.1, и пустое значение
        #означало бы «тот же origin», то есть запросы ушли бы в нашу статическую
        #раздачу, где никакого API нет. Пока это боевой сервер — как и раньше.
        #Когда появится локальный API поверх десктопного SQLite, поменяется РОВНО эта
        #строка, и офлайн заработает целиком — остальной интерфейс трогать не придётся.
        api_base = getattr(self, "_api_base", base or "")
        #Локальный путь — свои токены (см. выше). Запасной (статика + боевой сервер)
        #продолжает пользоваться боевыми.
        local_access, local_refresh = getattr(self, "_local_tokens", ("", ""))
        if local_access:
            access, refresh = local_access, local_refresh
        return (
            "try{"
            f"localStorage.setItem('gb.access',{json.dumps(access or '')});"
            f"localStorage.setItem('gb.refresh',{json.dumps(refresh or access or '')});"
            f"localStorage.setItem('gb.user',{user});"
            f"localStorage.setItem('gb.api_base',{json.dumps(api_base)});"
            f"{theme_js}"
            f"localStorage.setItem('gb.embed',{json.dumps('1' if self._embed else '0')});"
            "}catch(e){}"
        )
