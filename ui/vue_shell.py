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
        self._embed = self._embed_mode(embed)
        self._view = None
        self._loaded = False   #страницу грузим при ПЕРВОМ показе, а не при сборке
        self.ok = False        #удалось ли показать интерфейс (иначе — нативный запасной)
        self._source = ""      #откуда взят интерфейс: local_api | static
        self._api_base = ""    #куда SPA ходит за данными ('' = тот же origin)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self.ok = self._probe()

    @staticmethod
    def _embed_mode(embed) -> str:
        """Режим встраивания СТРОКОЙ, как его читает SPA (см. AppShell.vue).

        '1' — встроена одна страница: меню SPA прячем, вокруг нативные вкладки;
        'nav' — встроен весь кабинет: меню оставляем (иначе застрять на одной странице),
                прячем только шапку — её роль играет заголовок окна;
        '0' — не встроено."""
        if embed == "nav":
            return "nav"
        return "1" if embed else "0"

    def showEvent(self, event):
        """Страницу грузим ЛЕНИВО — при первом реальном показе вкладки.

        Это не оптимизация, а исправление: вкладки собираются сразу после входа, и в
        этот момент живой токен сессии ещё может быть не готов. Сессию для локального
        сервера мы выпускаем по логину вошедшего — на пустом логине сервер её законно
        отвергал, и внутри программы показывалась ФОРМА ВХОДА, хотя человек уже вошёл.
        К моменту, когда человек открывает вкладку, сессия заведомо на месте."""
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._build()

    def _message(self, text: str):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        self._lay.addWidget(lbl)

    def _probe(self) -> bool:
        """Есть ли чем показать вкладку. Отвечаем ДО загрузки страницы: вызывающий по
        этому флагу решает, строить ли нативный запасной экран, и решение нужно ему
        сразу при сборке — а сама страница грузится позже, при первом показе."""
        #⚠️ Проверяем не только «сервер поднялся», но и «сессию выпустить получилось».
        #Иначе выходит худший из вариантов: проба сказала «покажу», а на показе выяснилось,
        #что нельзя — и человек получал пустую вкладку ВМЕСТО нативного кабинета. Именно
        #так у преподавателя и админа кабинет перестал открываться вовсе.
        if self._start_local_api() is not None:
            if self._issue_local_session()[0]:
                return True
            _LOG.warning("[vue-shell] общий кабинет недоступен — отдаём нативный")
            return False
        try:
            from local_ui_server import instance
            return bool(instance().start())
        except Exception as e:
            _LOG.warning(f"[vue-shell] интерфейс недоступен: {e}")
            return False

    def _build(self):
        """Выбираем источник интерфейса и грузим страницу.

        ОСНОВНОЙ путь — локальное серверное приложение (`local_api`): оно отдаёт и SPA,
        и `/web/*` с ОДНОГО адреса, поэтому интерфейс и данные живут на одном origin, а
        офлайн работает целиком. ЗАПАСНОЙ — статическая раздача (`local_ui_server`):
        данные берутся с боевого сервера, как раньше.

        ⚠️ Локальный путь выбираем, ТОЛЬКО если для него удалось выпустить сессию.
        Иначе он гарантированно покажет форму входа (боевой токен подписан чужим
        секретом), а запасной путь в это же время прекрасно работает: лучше отдать
        онлайн-интерфейс, чем офлайн-способный, но пустой."""
        api = self._start_local_api()
        if api is not None:
            #Токены — ЛОКАЛЬНЫЕ: боевой подписан чужим секретом, и этот сервер обязан
            #его отвергнуть (см. issue_local_session).
            self._local_tokens = self._issue_local_session()
            if self._local_tokens[0]:
                self._source = "local_api"
                #Один origin: адрес API не задаём вовсе — SPA пойдёт к тому же серверу,
                #с которого её саму и отдали.
                self._api_base = ""
                try:
                    self._build_view(api.url(self._route), token_cookie="", token="")
                    self.ok = True
                    return
                except Exception as e:
                    _LOG.warning(f"[vue-shell] веб-вид поверх локального API не собрался: {e}")

        #⚠️ ЗАПАСНОГО ПУТИ «статика + боевой API» БОЛЬШЕ НЕТ, и это не упрощение.
        #Он физически неработоспособен: страница отдаётся с 127.0.0.1, а запросы шли бы
        #на esstu-gradebook.ru — браузер режет их по CORS ДО отправки, и заголовков
        #Access-Control-Allow-Origin боевой сервер не выдаёт (правильно, что не выдаёт:
        #открывать его чужим origin'ам ради десктопа нельзя). На практике это выглядело
        #как «нет групп, нет студентов, пустой мессенджер» — интерфейс живой, а каждый
        #запрос отклонён. Правильный ответ один: ВСЁ ходит на локальный сервер, один
        #origin; онлайн-подсистемы он проксирует на бой сам (см. local_api).
        self._local_tokens = ("", "")
        _LOG.warning("[vue-shell] локальный сервер недоступен — вкладка не открыта")
        self._message("Не удалось запустить локальный сервер приложения. "
                      "Работают нативные вкладки.")

    def _issue_local_session(self) -> tuple:
        """Сессия для локального сервера ('', '' — не удалось, тогда запасной путь).

        Дополнительно проверяем, что человек ЕСТЬ в локальной копии базы: сразу после
        первого входа зеркало ещё могло не докачаться, и тогда даже правильный токен
        привёл бы к форме входа. В этом случае честнее уйти на боевой сервер и
        переехать на локальный при следующем открытии вкладки."""
        login = self._current_login()
        if not login:
            _LOG.warning("[vue-shell] не удалось определить логин — вкладка пойдёт на боевой сервер")
            return "", ""
        try:
            import local_api as _la
            if not _la.user_exists(login):
                #Не «уходим на боевой сервер» (так нельзя — CORS, см. _build), а ДОГОНЯЕМ
                #копию здесь же: без своей строки в базе локальный сервер отвергнет даже
                #верный токен. Синхронно и однократно — это первый вход на этой машине.
                _LOG.info(f"[vue-shell] «{login}» ещё не в локальной копии — догоняем зеркало")
                import local_mirror
                local_mirror.mirror_once()
                if not _la.user_exists(login):
                    _LOG.warning(f"[vue-shell] «{login}» не пришёл в зеркало — нет связи?")
                    return "", ""
            tokens = _la.issue_local_session(login, self._role)
            #Проверяем ДО показа: SPA на отказ авторизации молча покажет форму входа,
            #и человек решит, что вкладка сломана. Не приняли — уходим на боевой сервер.
            if tokens[0] and not _la.session_works(tokens[0]):
                _LOG.warning("[vue-shell] локальная сессия не работает — вкладка пойдёт "
                             "на боевой сервер")
                return "", ""
        except Exception as e:
            _LOG.warning(f"[vue-shell] локальная сессия не выпущена: {e}")
            return "", ""
        _LOG.info(f"[vue-shell] локальная сессия для «{login}»: "
                  f"{'готова' if tokens[0] else 'НЕ выпущена'}")
        return tokens

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
        """Логин вошедшего пользователя.

        ТРИ источника по убыванию надёжности, и ни один не лишний:
          1. логин текущей сессии программы — известен с момента входа ВСЕГДА;
          2. claim `sub` живого токена — если синк почему-то не запущен;
          3. сохранённая сессия на диске — последняя соломинка.
        Третий источник сам по себе обманчив: при выходе запись стирается, и «вошедший
        человек» с диска выглядит как отсутствующий. Поэтому он и не первый."""
        try:
            from sync_runner import current_login
            login = current_login()
            if login:
                return login
        except Exception:
            pass
        try:
            from sync_runner import fresh_auth
            #Плоский импорт (см. _bootstrap.py — ui/ лежит В sys.path, не как пакет ui.*).
            from messenger_web import _decode_login
            login = _decode_login(fresh_auth()[1] or "")
            if login:
                return login
        except Exception:
            pass
        try:
            import app_settings
            return (app_settings.get_saved_session() or {}).get("login", "") or ""
        except Exception:
            return ""

    @staticmethod
    def _remote_token() -> str:
        """Живой токен боевого сервера ('' — офлайн либо вход не выполнялся)."""
        try:
            from sync_runner import fresh_auth
            return fresh_auth()[1] or ""
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
        login = self._current_login()
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
        #⚠️ dumps ДВАЖДЫ, и это не описка. Внутренний даёт JSON, который SPA потом
        #разбирает; внешний превращает его в СТРОКОВЫЙ литерал JS. С одним dumps в код
        #попадал объектный литерал, localStorage сохранял его как «[object Object]»,
        #разбор падал — и SPA считала, что никто не вошёл, показывая форму входа.
        user = json.dumps(json.dumps({"login": login, "role": self._role, "name": login}))
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
            f"localStorage.setItem('gb.embed',{json.dumps(self._embed)});"
            "}catch(e){}"
        )
