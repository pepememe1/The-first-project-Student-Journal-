"""
local_api.py — ЛОКАЛЬНЫЙ сервер приложения внутри десктопа (offline-first на Vue).

━━ ПОЧЕМУ ИМЕННО ТАК, А НЕ «АДАПТЕР» ━━

Задача: десктоп и сайт должны жить на ОДНОМ интерфейсном коде, и при этом десктоп
обязан работать без интернета. Очевидный на первый взгляд путь — написать переходник,
который отдаёт Vue данные из десктопного SQLite. Он плох ровно тем, ради чего всё
затевается: `/web/*` — это около сотни эндпоинтов и весь расчёт успеваемости, и вторая
их реализация начала бы расходиться с первой ровно так же, как расходились два фронта.
Мы это уже проходили — на сервере однажды жила упрощённая копия классификатора Вектора
и отстала от десктопной (см. §5 CLAUDE.md).

Поэтому берём НАСТОЯЩЕЕ серверное приложение (`server/app`) и запускаем ЕГО ЖЕ на этом
компьютере. Оно уже умеет всё нужное:
  • раздаёт собранную Vue-SPA с того же адреса, что и API (см. server/app/main.py) —
    значит интерфейс и данные приходят с одного origin, без CORS и без «адреса сервера»;
  • работает на SQLite, если задать GRADEBOOK_DB_URL (в бою там PostgreSQL).
Итог: один код интерфейса, один код API, офлайн — потому что всё локально.

━━ БЕЗОПАСНОСТЬ ━━
  • Слушаем РОВНО 127.0.0.1 и эфемерный порт: из сети до сокета не дойти, порт не угадать.
    ⚠️ НЕ МЕНЯТЬ на 0.0.0.0 «чтобы зайти с телефона» — для этого есть отдельный ФОНОВЫЙ
    сервер хоста (server_control.py), который для того и предназначен и настраивается
    осознанно. Правило закреплено тестом.
  • Доступ к данным по-прежнему за JWT — это тот же `get_current_user`, что и на бою,
    никаких «локально значит без пароля».
  • Поднимаем ПОТОКОМ внутри процесса, а не subprocess: поток не может показать окно,
    поэтому вспышек консоли не бывает в принципе (флаг CREATE_NO_WINDOW помогает не
    на всех путях запуска, гарантия по построению надёжнее).

━━ ЧТО ЭТО НЕ ДЕЛАЕТ ━━
Локальная база — ОТДЕЛЬНЫЙ файл в папке данных, наполняется синхронизацией с боевым
сервером. Существующая десктопная база (data/core.py) не трогается и продолжает
обслуживать нативные экраны, пока переезд не завершён: одномоментная замена сломала бы
журнал у всех, а так обе дороги какое-то время сосуществуют.
"""
import os
import socket
import threading
import time

import log

_LOG = log.get("local_api")

#Сколько ждём готовности сервера, прежде чем признать запуск неудачным.
_READY_TIMEOUT_S = 25
_READY_POLL_S = 0.15


def _free_loopback_port() -> int:
    """Свободный порт на петле. Просим у ОС порт 0 и сразу отпускаем.

    Теоретически между «отпустили» и «заняли» его может перехватить кто-то ещё, но на
    петле это событие исчезающе редкое, а альтернатива (передавать uvicorn готовый
    сокет) заметно усложняет запуск и завершение."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def local_db_url() -> str:
    """Адрес ЛОКАЛЬНОЙ базы приложения (схема сервера). Лежит в папке данных рядом с
    остальным, чтобы портативный .exe оставался портативным."""
    import app_paths
    path = app_paths.data_file("local_app.db").replace("\\", "/")
    return f"sqlite:///{path}"


class LocalAPI:
    """Серверное приложение, поднятое на этом компьютере. start() идемпотентен."""

    def __init__(self):
        self._server = None
        self._thread = None
        self.port = 0
        self.error = ""

    @property
    def running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    def _prepare_env(self):
        """Переменные окружения ДО импорта серверного приложения: config читает их на
        импорте, позже менять поздно."""
        os.environ.setdefault("GRADEBOOK_DB_URL", local_db_url())
        #Локальная база — файл на диске пользователя. Шифрование БД (SQLCipher) здесь
        #НЕ включаем: ключ пришлось бы хранить рядом с самой базой, что защиты не даёт.
        #ПДн на десктопе защищает существующий слой (Fernet + DPAPI, §6) — его и оставляем.
        os.environ.pop("GRADEBOOK_DB_KEY", None)

    def start(self) -> bool:
        """Поднять локальный сервер. False — если серверный пакет недоступен."""
        if self.running:
            return True
        try:
            self._prepare_env()
            app = self._load_app()
        except Exception as e:
            self.error = str(e)
            _LOG.warning(f"[local-api] серверное приложение не загрузилось: {e}")
            return False

        import uvicorn
        self.port = _free_loopback_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port,
                                log_level="warning", access_log=False,
                                lifespan="on")
        self._server = uvicorn.Server(config)
        #install_signal_handlers работает только в главном потоке — в фоновом он бы
        #упал на ValueError, поэтому отключаем (останавливать будем флагом should_exit).
        self._server.install_signal_handlers = lambda: None
        self._thread = threading.Thread(target=self._server.run,
                                        name="gb-local-api", daemon=True)
        self._thread.start()
        if not self._wait_ready():
            self.error = "сервер не ответил вовремя"
            _LOG.warning("[local-api] не дождались готовности")
            self.stop()
            return False
        _LOG.info(f"[local-api] приложение доступно на 127.0.0.1:{self.port}")
        return True

    def _load_app(self):
        """Импорт серверного приложения (пакет `app` лежит внутри `server/`).

        Каталог ищем ДВУМЯ путями, и это не перестраховка: `app_paths.app_dir()`
        отталкивается от точки запуска, а она разная — у .exe это папка рядом с ним, а
        под pytest вообще каталог самого pytest, и тогда `server/` не находится вовсе.
        Поэтому сначала пробуем путь ОТ ЭТОГО ФАЙЛА (ui/ → корень репозитория), который
        от точки запуска не зависит."""
        import sys
        candidates = []
        here = os.path.dirname(os.path.abspath(__file__))          # …/ui
        candidates.append(os.path.join(os.path.dirname(here), "server"))
        try:
            import app_paths
            candidates.append(os.path.join(app_paths.app_dir(), "server"))
        except Exception:
            pass
        for server_dir in candidates:
            if os.path.isdir(server_dir):
                if server_dir not in sys.path:
                    sys.path.insert(0, server_dir)
                break
        from app.main import app          # noqa: WPS433 — импорт намеренно ленивый
        return app

    def _wait_ready(self) -> bool:
        """Ждём, пока сервер начнёт отвечать. Опрашиваем /health, а не спим фиксированно:
        на медленной машине первая инициализация БД занимает секунды, и жёсткая пауза
        либо тормозила бы запуск всем, либо не хватала бы части."""
        import urllib.error
        import urllib.request
        deadline = time.time() + _READY_TIMEOUT_S
        url = self.url("/health")
        while time.time() < deadline:
            if self._server is not None and getattr(self._server, "started", False):
                try:
                    with urllib.request.urlopen(url, timeout=2) as r:
                        if r.status == 200:
                            return True
                except (urllib.error.URLError, OSError):
                    pass
            if self._thread is not None and not self._thread.is_alive():
                return False        #поток умер — дальше ждать бессмысленно
            time.sleep(_READY_POLL_S)
        return False

    def stop(self):
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def url(self, route: str = "/") -> str:
        if not self.port:
            return ""
        if not route.startswith("/"):
            route = "/" + route
        return f"http://127.0.0.1:{self.port}{route}"


_instance = LocalAPI()


def instance() -> LocalAPI:
    return _instance
