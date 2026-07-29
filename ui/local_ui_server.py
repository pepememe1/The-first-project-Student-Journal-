"""
local_ui_server.py — ПРИВАТНЫЙ локальный сервер, раздающий Vue-интерфейс десктопу.

Зачем он вообще. Сейчас у нас два фронта: нативный Qt и Vue-SPA, и каждую правку
приходится делать дважды. Эндшпиль (§11 CLAUDE.md) — десктоп показывает ТОТ ЖЕ Vue,
но берёт его не с боевого сайта, а со своего адреса 127.0.0.1, чтобы интерфейс
работал и без интернета. Этот модуль — фундамент: он поднимает такой адрес.

━━ ТРЕБОВАНИЯ, КОТОРЫЕ ЗДЕСЬ ВЫПОЛНЯЮТСЯ ━━

1) НИКАКИХ ОКОН. Сервер поднимается ПОТОКОМ ВНУТРИ программы, а не отдельным
   процессом. Это принципиально: любой subprocess на Windows — потенциальная вспышка
   консоли (CREATE_NO_WINDOW помогает не всегда: его нет у части пусковых путей, и он
   не действует, когда процесс стартует через оболочку). Поток не может показать окно
   в принципе — гарантия по построению, а не по флагу.
   ⚠️ Не путать с ФОНОВЫМ сервером хоста (server_control.py): тот раздаёт журнал всему
   колледжу, живёт отдельным процессом и слушает сеть. Этот — личный, только для
   интерфейса на этом же компьютере.

2) СНАРУЖИ НЕ ДОСТУЧАТЬСЯ. Три независимых рубежа, каждый закрывает свою дыру:
   • слушаем РОВНО 127.0.0.1 (не 0.0.0.0) — пакет из сети до сокета просто не дойдёт;
   • порт ЭФЕМЕРНЫЙ (его выдаёт ОС) — угадывать нечего, и конфликта с чужой программой
     на фиксированном порту тоже не будет;
   • на каждый запрос нужен ТОКЕН этого запуска (32 случайных байта, живёт в памяти).
     Это защита от соседей ПО ЭТОМУ ЖЕ компьютеру: на общем ПК колледжа под другой
     учётной записью localhost общий, и без токена чужая программа могла бы читать
     журнал через наш же адрес.
   • плюс проверка заголовка Host — от DNS-rebinding: браузер по ссылке со стороннего
     сайта может слать запросы на 127.0.0.1, и без этой проверки они бы прошли.

3) ЛЮБОЙ КОМПЬЮТЕР ПОТЯНЕТ. Отдаём только статику Vue, без БД и без тяжёлых
   зависимостей. Это дешевле, чем уже работающий в программе QtWebEngine (Chromium),
   так что на требования к железу переход не влияет.

Модуль НЕ тянет PySide6 — его можно проверять тестами без GUI.
"""
import hmac
import mimetypes
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

import log

_LOG = log.get("local_ui_server")

#Имя заголовка/куки с токеном запуска. Кука нужна потому, что за картинками и скриптами
#браузер ходит сам и наш заголовок к ним не подставит.
TOKEN_HEADER = "X-GB-Local-Token"
TOKEN_COOKIE = "gb_local_token"

#Хосты, которые считаем «своими» в заголовке Host (см. пункт 2 выше).
_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")


def _dist_dir() -> str:
    """Где лежит собранный Vue. В .exe его кладут рядом (webdist), в dev — web/dist."""
    import app_paths
    for candidate in (os.path.join(app_paths.app_dir(), "webdist"),
                      os.path.join(app_paths.app_dir(), "web", "dist")):
        if os.path.isdir(candidate):
            return candidate
    return ""


class _Handler(BaseHTTPRequestHandler):
    """Раздача статики Vue + SPA-фолбэк. Только GET/HEAD: ничего изменять здесь нельзя."""

    server_version = "GradeBookLocalUI"
    sys_version = ""            #не выдаём версию Python в заголовках

    #ссылка на владельца (проставляется при создании сервера)
    root = ""
    token = ""

    def log_message(self, fmt, *args):
        """Молчим в stdout. У собранного .exe консоли нет, а вывод в неё — верный способ
        получить исключение на ровном месте (или мигающее окно)."""
        return

    # ── безопасность ────────────────────────────────────────────────────────────────
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in _ALLOWED_HOSTS

    def _token_ok(self) -> bool:
        """Токен из заголовка ИЛИ из куки. Сравниваем через compare_digest —
        побайтовое сравнение утекает длину совпадения по времени ответа."""
        supplied = self.headers.get(TOKEN_HEADER) or ""
        if not supplied:
            raw = self.headers.get("Cookie") or ""
            for part in raw.split(";"):
                name, _, value = part.strip().partition("=")
                if name == TOKEN_COOKIE:
                    supplied = value
                    break
        return bool(supplied) and hmac.compare_digest(supplied, self.token)

    def _deny(self, code: int = 403):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ── раздача ─────────────────────────────────────────────────────────────────────
    def _resolve(self, url_path: str) -> str:
        """URL → путь на диске. Возвращает '' при попытке выйти за пределы каталога.

        Проверяем НЕ по подстроке «..», а сравнением РЕАЛЬНЫХ путей: «..» бывает
        закодирован (%2e%2e), и подстрочная проверка такое пропускает."""
        rel = unquote(urlparse(url_path).path).lstrip("/")
        full = os.path.realpath(os.path.join(self.root, rel))
        root = os.path.realpath(self.root)
        if full != root and not full.startswith(root + os.sep):
            return ""
        return full

    def do_GET(self, body: bool = True):
        if not self._host_ok():
            return self._deny(421)          #Misdirected Request — обращались не к нам
        if not self._token_ok():
            return self._deny(403)
        path = self._resolve(self.path)
        if not path:
            return self._deny(404)
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")
        if not os.path.isfile(path):
            #SPA-фолбэк: маршруты Vue (/student/journal и т.п.) файлами не существуют,
            #их разбирает сам роутер в браузере — отдаём index.html.
            path = os.path.join(self.root, "index.html")
            if not os.path.isfile(path):
                return self._deny(404)
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return self._deny(404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        #Локальная раздача — кэшировать нечего, а устаревший бандл после обновления
        #программы обошёлся бы дороже, чем повторное чтение файла с диска.
        self.send_header("Cache-Control", "no-store")
        #Страницу нельзя встроить в чужой фрейм и утащить из неё данные.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if body:
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET(body=False)


class LocalUIServer:
    """Живёт столько же, сколько программа. start() идемпотентен."""

    def __init__(self):
        self._httpd = None
        self._thread = None
        self.port = 0
        self.token = ""
        self.root = ""

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> bool:
        """Поднять сервер. False — если раздавать нечего (нет собранного Vue)."""
        if self.running:
            return True
        root = _dist_dir()
        if not root:
            _LOG.warning("[local-ui] не найден собранный Vue (webdist / web/dist) — "
                         "десктоп продолжит работать на нативном интерфейсе")
            return False
        self.root = root
        self.token = secrets.token_urlsafe(32)

        handler = type("_BoundHandler", (_Handler,),
                       {"root": root, "token": self.token})
        #Порт 0 — ОС сама выдаст свободный эфемерный. Слушаем строго петлю.
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        #Потоки-обработчики тоже демоны: программа должна закрываться мгновенно, не
        #дожидаясь висящих соединений (например, брошенной вкладки).
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="gb-local-ui", daemon=True)
        self._thread.start()
        _LOG.info(f"[local-ui] интерфейс раздаётся на 127.0.0.1:{self.port}")
        return True

    def stop(self):
        if not self._httpd:
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
        self._httpd = None
        self._thread = None

    def url(self, route: str = "/") -> str:
        if not self.running:
            return ""
        if not route.startswith("/"):
            route = "/" + route
        return f"http://127.0.0.1:{self.port}{route}"


#Один сервер на программу — интерфейс общий для всех вкладок.
_instance = LocalUIServer()


def instance() -> LocalUIServer:
    return _instance


def is_loopback_only(host: str) -> bool:
    """Проверка для тестов и для ревью: адрес обязан быть петлевым.

    Вынесено отдельно, чтобы правило «слушаем только себя» было ЗАКРЕПЛЕНО тестом, а не
    держалось на строке в конструкторе, которую однажды поправят «чтобы с телефона зайти»."""
    try:
        return socket.inet_aton(host)[0:1] == b"\x7f"
    except OSError:
        return host in ("::1", "localhost")
