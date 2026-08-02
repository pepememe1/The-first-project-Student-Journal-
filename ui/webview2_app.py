"""
webview2_app.py — ВСЯ программа одним окном системного движка Edge (WebView2).

━━ ЗАЧЕМ ━━
Интерфейс уже целиком веб-овый: кабинеты студента, преподавателя и админа — это Vue-SPA,
которую отдаёт НАСТОЯЩЕЕ серверное приложение, поднятое на этом же компьютере
(`ui/local_api.py`). Qt в сборке остался ради одного — показать страницу, и стоит это
~180 МБ Chromium внутри .exe. В Windows 10/11 движок Edge уже установлен системой,
поэтому окно можно рисовать им, а из сборки убрать и Chromium, и сам Qt.

━━ ЧТО ЗДЕСЬ ПРИНЦИПИАЛЬНО ━━
• OFFLINE-FIRST ЦЕЛ. Окно смотрит на 127.0.0.1, а не на сайт: данные берутся из локальной
  зашифрованной копии базы, синхронизация идёт фоном. Без сети программа работает.
• ВХОД ТОЖЕ ВЕБ-ОВЫЙ. Раньше он был нативным экраном Qt — теперь это страница той же SPA,
  а «человека ещё нет в локальной копии» решает мост в `local_api.install_login_bridge`
  (сначала локальная проверка, при неудаче — боевой сервер).
• Странице доступен `js_api` (см. `_DeskAPI`) — версия приложения, закрытие окна. Раздел
  «Сервер» (хостинг, БД, §16) теперь в самой SPA (`AdminServer.vue`), не через этот мост:
  отдельная нативная дверь «Инструменты ПК» переиспользовала устаревший, не обновлявшийся
  вместе с Vue-панелью нативный `AdminDashboard` — убрана целиком.

━━ ЧЕГО ЗДЕСЬ НЕТ ━━
Своего цикла событий и своих окон: `webview.start()` блокирует поток до закрытия окна.
Именно поэтому оболочки Qt и WebView2 НЕ сосуществуют в одном запуске — выбор делается
один раз на старте (см. `main.py`).
"""
import os
import sys
import threading

import local_api
import log

_LOG = log.get("webview2app")

#Окно меньше этого размера ломает вёрстку кабинета (таблицы журнала уезжают), а больше
#экрана — не открыть. Значения те же, что у Qt-оболочки: смена движка не должна менять
#привычный размер окна.
_MIN_SIZE = (1024, 640)
_START_SIZE = (1440, 900)


class _DeskAPI:
    """То, чего у браузера нет в принципе. Доступно странице как `window.pywebview.api`.

    Сознательно КРОШЕЧНЫЙ набор: каждый метод здесь — это способность, которой нет у
    сайта и телефона, то есть расхождение платформ. Всё, что можно дать всем, даётся
    через обычный веб-интерфейс, а не через этот мост."""

    def app_version(self):
        try:
            from core import APP_VERSION
            return APP_VERSION
        except Exception:
            return ""

    def quit(self):
        """Закрыть программу из интерфейса (кнопка «Выйти» ведёт на экран входа, а не сюда)."""
        try:
            import webview
            for w in webview.windows:
                w.destroy()
            return {"ok": True}
        except Exception as e:      # noqa: BLE001
            return {"ok": False, "error": str(e)}


def available() -> bool:
    """Можно ли запуститься на системном движке (обвязка + WebView2 Runtime)."""
    try:
        from webview2_shell import available as _av
        return bool(_av())
    except Exception:
        return False


def run() -> bool:
    """Запустить программу целиком на WebView2. False — движок не подошёл, зовите Qt.

    ⚠️ БЛОКИРУЕТ поток до закрытия окна. Возврат False возможен только ДО открытия окна:
    если окно уже показано, откат на Qt был бы вторым интерфейсом в одном запуске."""
    if not available():
        _LOG.info("[webview2] движок недоступен — остаёмся на прежней оболочке")
        return False

    import webview
    import webview2_shell as shell

    #1. Поднимаем НАСТОЯЩЕЕ серверное приложение на петле. Без него показывать нечего:
    #   и страницы, и данные приходят с одного адреса (поэтому нет ни CORS, ни настройки
    #   «адрес сервера» — см. шапку local_api).
    local_api.prepare_env()
    api = local_api.instance()
    if not api.start():
        _LOG.warning(f"[webview2] локальный сервер не поднялся: {api.error}")
        return False

    #2. Мост входа, передача сессии и прокси онлайн-подсистем ставит сам LocalAPI.start()
    #   (см. local_api) — здесь их дублировать не нужно.
    # Если человек уже входил на этой машине, отдаём сессию странице сразу — тогда
    #   программа открывается на кабинете, а не на форме входа.
    url = _start_url(api)

    shell.apply_privacy_env()        #телеметрия/SmartScreen/синхронизация — выключены
    _prepare_permissions()

    try:
        from core import APP_VERSION
        title = f"GradeBookAI — {APP_VERSION}"
    except Exception:
        title = "GradeBookAI"

    window = webview.create_window(title, url, width=_START_SIZE[0], height=_START_SIZE[1],
                                   min_size=_MIN_SIZE, text_select=True, js_api=_DeskAPI())
    #Иконка окна — наш гексагон GB. Ставим ПОСЛЕ появления окна: до этого системного окна
    #ещё нет. Без этого в углу и на панели задач висит значок Edge, и программа выглядит
    #чужой — «браузер с сайтом», а не приложение колледжа.
    #⚠️ ИКОНКУ СТАВИМ ТОЛЬКО ПРИ ЗАПУСКЕ ИЗ ИСХОДНИКОВ. У собранного .exe значок и так
    #берётся из ресурсов файла, а обработчик события `shown` выполняется на потоке
    #интерфейса и делает там `import clr` (инициализация .NET). Импорт с чужого потока в
    #момент, когда другой поток тоже что-то импортирует, упирается в общий импорт-замок
    #Python — и процесс встаёт ЦЕЛИКОМ: окно «не отвечает», локальный сервер перестаёт
    #отвечать даже на /health (проверено на собранном exe). Украшение не стоит риска.
    if not getattr(sys, "frozen", False) and not _is_compiled():
        window.events.shown += lambda: _apply_window_icon(window)
    _LOG.info(f"[webview2] окно открыто: {url}")
    try:
        webview.start(gui="edgechromium",
                      private_mode=True,             #эфемерный профиль (152-ФЗ)
                      storage_path=shell.profile_dir(),
                      debug=False)
    finally:
        #Сначала дописать несохранённое, потом гасить сервер: выход не имеет права
        #потерять правки, сделанные в последнюю минуту (то же правило, что у Qt-оболочки).
        _flush_sync()
        try:
            api.stop()
        except Exception:
            pass
    return True


def _start_url(api) -> str:
    """Адрес первой страницы: кабинет, если сессия есть, иначе форма входа."""
    login = ""
    try:
        from sync_runner import current_login
        login = current_login()
    except Exception:
        pass
    if not login:
        try:
            import app_settings
            saved = app_settings.get_saved_session() or {}
            login = (saved.get("login") or "").strip()
        except Exception:
            login = ""
    #Сессию передаём, ТОЛЬКО если человек уже есть в локальной копии: иначе `/web/*`
    #ответит «нет доступа», и кабинет откроется пустым вместо честной формы входа.
    if login and local_api_user_ready(login):
        role = ""
        try:
            import app_settings
            role = (app_settings.get_saved_session() or {}).get("role", "") or ""
        except Exception:
            pass
        home = {"student": "/student", "teacher": "/teacher",
                "admin": "/admin", "parent": "/parent"}.get(role, "/")
        #embed='0': у окна нет своей нативной шапки — вся навигация и шапка веб-овые.
        url = local_api.bootstrap_url(home, embed="0")
        if url:
            return url
    return api.url("/login")


def local_api_user_ready(login: str) -> bool:
    try:
        return bool(local_api.user_exists(login))
    except Exception:
        return False


def _is_compiled() -> bool:
    """Собран ли модуль Nuitka (в .exe у окна уже есть иконка из ресурсов файла)."""
    return "__compiled__" in globals() or bool(getattr(sys, "frozen", False))


def _apply_window_icon(window) -> None:
    """Поставить окну иконку программы (гексагон GB) вместо значка движка Edge.

    Оболочка WebView2 на Windows — это форма WinForms, и у неё есть свойство `Icon`;
    именно оно определяет значок в углу окна и на панели задач. У собранного .exe иконка
    берётся из ресурсов файла, а при запуске из исходников её ставить некому — значок
    остаётся от Edge, и программа выглядит чужой.

    Любая осечка здесь молча игнорируется: значок — это украшение, ронять из-за него
    запуск нельзя."""
    try:
        path = _icon_path()
        if not path:
            return
        #`System.*` доступен только когда pywebview уже поднял WinForms через pythonnet —
        #то есть в момент показа окна, а не при импорте модуля. Ссылку добавляем сами:
        #обвязка тянет System.Windows.Forms, а System.Drawing (где живёт Icon) — не всегда.
        import clr
        try:
            clr.AddReference("System.Drawing")
        except Exception:
            pass
        from System.Drawing import Icon
        window.native.Icon = Icon(path)
        _LOG.info("[webview2] иконка окна установлена")
    except Exception as e:      # noqa: BLE001
        _LOG.info(f"[webview2] иконка окна не установлена: {e}")


def _icon_path() -> str:
    """Путь к icon.ico ('' — не нашли). Ищем там же, где нативная оболочка (см. main.py):
    рядом с .exe, рядом с исходниками и во временной папке PyInstaller."""
    import sys
    bases = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bases.append(meipass)
    try:
        import app_paths
        bases.insert(0, app_paths.app_dir())
    except Exception:
        pass
    for base in bases:
        p = os.path.join(base, "icon.ico")
        if os.path.exists(p):
            return p
    return ""


def _prepare_permissions() -> None:
    """Разрешить микрофон без вопроса-модалки на КАЖДОЕ нажатие кнопки.

    В браузере разрешение спрашивают у человека, и это правильно — там страница чужая.
    Здесь страница НАША и открыта с петли, а запись всё равно не покидает компьютер
    (распознаёт локальный сервер). Спрашивать при каждом нажатии значит ломать
    голосовой ввод ради обряда."""
    prev = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    #`--use-fake-ui-for-media-stream` заставляет движок отвечать «разрешено» на запрос
    #getUserMedia без диалога. Микрофон при этом всё равно включает ТОЛЬКО наш код и
    #только по нажатию кнопки — фонового доступа этот флаг не даёт.
    flag = "--use-fake-ui-for-media-stream"
    if flag not in prev:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"{prev} {flag}".strip()


def _flush_sync() -> None:
    """Дописать несохранённое перед закрытием (правки последней минуты не теряем)."""
    try:
        from sync_runner import flush
        t = threading.Thread(target=flush, daemon=True)
        t.start()
        t.join(timeout=8)
    except Exception as e:      # noqa: BLE001
        _LOG.info(f"[webview2] финальная синхронизация не удалась: {e}")
