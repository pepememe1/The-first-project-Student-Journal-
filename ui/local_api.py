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


def local_db_file(login: str = "") -> str:
    """Путь к локальной базе КОНКРЕТНОГО пользователя.

    ⚠️ Файл СВОЙ на каждого вошедшего, и это не удобство, а защита. Раньше файл был один
    на машину, и в нём одновременно оказывались данные разных ролей: после сеанса
    преподавателя в базе оставались оценки всей группы, а следующий вошедший студент
    получал к ним доступ (проверено: 44 оценки шести студентов на машине студента).
    Имя файла — хеш логина, а не сам логин: имя учётной записи — тоже персональные
    данные, и светить его в имени файла незачем."""
    import hashlib
    import app_paths
    who = hashlib.sha256((login or "anon").encode("utf-8")).hexdigest()[:16]
    return app_paths.data_file(f"local_app_{who}.db")


def local_db_url(login: str = "") -> str:
    """Адрес локальной базы (схема сервера) в папке данных — .exe остаётся портативным."""
    return "sqlite:///" + local_db_file(login).replace("\\", "/")


def _drop_plaintext_copy(login: str = "") -> None:
    """Снять НЕЗАШИФРОВАННУЮ копию, оставшуюся от прежних версий.

    Драйвер не откроет открытый файл ключом («file is not a database»), а копия — это
    кэш: её содержимое полностью восстанавливается зеркалом с сервера. Поэтому удалить
    честнее, чем пытаться конвертировать: ни одна правка пользователя тут не живёт."""
    path = local_db_file(login)
    try:
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            if not f.read(16).startswith(b"SQLite format 3"):
                return          #уже зашифрована — не трогаем
    except OSError:
        return
    _LOG.info("[local-api] прежняя НЕЗАШИФРОВАННАЯ копия удалена — будет скачана заново")
    wipe_local_db(login)


def _local_db_key() -> str:
    """Ключ шифрования локальной копии ('' — шифровать нечем, работаем как раньше).

    Заводится ОДИН раз на устройство и хранится защищённым DPAPI: сам файл ключа
    бесполезен на другом компьютере и под другой учётной записью Windows. Ключ случайный —
    не производный от пароля: пароль в программе не хранится (§4.7), и привязка к нему
    сделала бы копию нечитаемой после смены пароля.

    Драйвер отсутствует (запуск из исходников без sqlcipher3) — возвращаем пустую строку:
    интерфейс важнее, чем упасть на старте, а сервер сам сообщит, что база без шифра. В
    .exe драйвер вшит (см. GradeBookAI.spec), поэтому пользователю ничего доустанавливать
    не нужно."""
    try:
        import sqlcipher3  # noqa: F401 — проверяем ДОСТУПНОСТЬ драйвера
    except Exception:
        _LOG.warning("[local-api] драйвера sqlcipher3 нет — копия базы без шифрования")
        return ""
    try:
        import binascii
        import os as _os
        import app_paths
        import security
        path = app_paths.data_file("local_app.key")
        if _os.path.exists(path):
            with open(path, "rb") as f:
                key = security.os_unprotect(f.read())
            if key:
                return key.decode("ascii")
            _LOG.warning("[local-api] ключ копии не расшифровался — заводим новый")
        key = binascii.hexlify(_os.urandom(32))
        with open(path, "wb") as f:
            f.write(security.os_protect(key))
        return key.decode("ascii")
    except Exception as e:
        _LOG.warning(f"[local-api] ключ шифрования не получен: {e}")
        return ""


def wipe_local_db(login: str = "") -> bool:
    """Стереть локальную копию — ПО ЯВНОМУ ТРЕБОВАНИЮ, а НЕ при каждом выходе.

    ⚠️ Стирать на выходе НЕЛЬЗЯ: копия и есть offline-first. Без неё следующий запуск без
    сети не покажет ни журнала, ни расписания — то самое обещание, ради которого локальный
    сервер и появился. Поэтому копия живёт между сеансами.
    Изоляцию даёт не стирание, а РАЗДЕЛЬНЫЕ файлы (см. local_db_file): чужую копию
    следующий вошедший просто не открывает. Эта функция — для «выйти и забыть меня»,
    отвязки устройства и очистки перед передачей компьютера другому человеку.
    Вместе с файлом уходит и метка дельты (она внутри базы), поэтому следующий вход
    честно скачает копию заново."""
    import os
    path = local_db_file(login)
    ok = True
    for suffix in ("", "-wal", "-shm"):
        try:
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
        except OSError as e:
            ok = False
            _LOG.warning(f"[local-api] копию не удалось стереть: {e}")
    return ok


def ensure_server_path() -> None:
    """Положить `server/` в sys.path, чтобы был импортируем пакет `app`.

    Каталог ищем ДВУМЯ путями, и это не перестраховка: `app_paths.app_dir()`
    отталкивается от точки запуска, а она разная — у .exe это папка рядом с ним, а под
    pytest вообще каталог самого pytest, и тогда `server/` не находится вовсе. Поэтому
    сначала пробуем путь ОТ ЭТОГО ФАЙЛА (ui/ → корень репозитория), который от точки
    запуска не зависит."""
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
            return


def prepare_env() -> None:
    """Указать серверному пакету на ЛОКАЛЬНУЮ базу. Зовётся ПЕРЕД любым обращением к
    `app.db` — не только при старте сервера.

    Иначе легко получить тихую подмену: `app.db` без этой переменной откроет базу
    разработчика, и проверка «есть ли такой человек» ответит по чужому файлу. Один раз
    это уже стоило нам вечной формы входа во вкладке. Функция идемпотентна.

    Заодно делаем пакет `app` импортируемым: без этого те же вызовы падали бы на
    ImportError и — из-за мягкой обработки ошибок — отвечали бы «человека нет»."""
    ensure_server_path()
    #Логин берём из ЖИВОЙ сессии: у каждого вошедшего своя копия базы (см. local_db_file).
    #setdefault, а не присваивание: если сервер уже поднят на чьей-то базе, менять адрес
    #на ходу нельзя — SQLAlchemy держит движок с прежним файлом.
    login = ""
    try:
        from sync_runner import current_login
        login = current_login()
    except Exception:
        pass
    os.environ.setdefault("GRADEBOOK_DB_URL", local_db_url(login))
    #🔒 ЛОКАЛЬНАЯ КОПИЯ ШИФРУЕТСЯ (SQLCipher, тот же механизм, что на боевом сервере).
    #Раньше здесь стоял pop() с рассуждением «ключ пришлось бы держать рядом с базой, а
    #значит защиты не будет». Рассуждение неверное: ключ лежит не «рядом», а под Windows
    #DPAPI — расшифровать его может только ЭТА учётная запись Windows на ЭТОЙ машине.
    #Ровно так в проекте уже защищён ключ Fernet (§6). Без этого копия была обычным
    #SQLite: ФИО, группы и оценки читались любым просмотрщиком с флешки.
    key = _local_db_key()
    if key:
        os.environ["GRADEBOOK_DB_KEY"] = key
        _drop_plaintext_copy(login)
    else:
        os.environ.pop("GRADEBOOK_DB_KEY", None)


class LocalAPI:
    """Серверное приложение, поднятое на этом компьютере. start() идемпотентен."""

    def __init__(self):
        self._server = None
        self._thread = None
        self.port = 0
        self.error = ""
        #Оба вызывающих (main.py — фоновым потоком сразу при старте, и VueShell._build —
        #из потока интерфейса при первом показе вкладки) держат ОДИН и тот же _instance
        #(см. instance() внизу файла) и оба могут позвать start() почти одновременно.
        #Без замка оба проходят проверку self.running (пока она ещё False), поднимают
        #ДВА uvicorn.Server на РАЗНЫХ портах — и оба одинаково зовут init_db() на ТОЙ ЖЕ
        #local_app.db, второй падает на «table already exists» (боевая находка — именно
        #так и обнаружено, прогоном собранного exe: реальная гонка, не гипотетическая).
        self._start_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    def _prepare_env(self):
        """Переменные окружения ДО импорта серверного приложения: config читает их на
        импорте, позже менять поздно."""
        prepare_env()

    def start(self) -> bool:
        """Поднять локальный сервер. False — если серверный пакет недоступен.

        Под замком целиком: конкурентный вызов должен ДОЖДАТЬСЯ уже идущего запуска и
        увидеть его результат через running, а не запускать свой собственный сервер
        параллельно (см. комментарий в __init__)."""
        with self._start_lock:
            if self.running:
                return True
            try:
                self._prepare_env()
                app = self._load_app()
            except Exception as e:
                self.error = str(e)
                _LOG.warning(f"[local-api] серверное приложение не загрузилось: {e}")
                return False

            #Онлайн-подсистемы (мессенджер) — пересылаем на бой: их данных в локальной
            #копии нет по замыслу, и без этого чаты в программе открывались пустыми.
            try:
                install_remote_proxy(app)
            except Exception as e:
                _LOG.warning(f"[local-api] прокси онлайн-подсистем не встал: {e}")

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
        """Импорт серверного приложения (пакет `app` лежит внутри `server/`)."""
        ensure_server_path()
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


def user_exists(login: str) -> bool:
    """Есть ли такой человек в ЛОКАЛЬНОЙ копии базы.

    Нужно перед выпуском локальной сессии: токен может быть безупречен, но если зеркало
    ещё не докачало самого пользователя, любой `/web/*` ответит «требуется авторизация»,
    и человек увидит форму входа. Лучше в этот момент честно уйти на боевой сервер."""
    if not login:
        return False
    try:
        prepare_env()
        from app.db import SessionLocal
        from app.models import User
    except Exception:
        return False
    db = SessionLocal()
    try:
        return db.query(User).filter(User.login == login).first() is not None
    except Exception:
        return False
    finally:
        db.close()


def issue_local_session(login: str, role: str) -> tuple:
    """Выпустить пару токенов ДЛЯ ЛОКАЛЬНОГО сервера. Возвращает (access, refresh).

    ⚠️ ЗАЧЕМ ЭТО ВООБЩЕ НУЖНО. Токен, которым десктоп ходит на боевой сервер, подписан
    БОЕВЫМ секретом, а локальный сервер подписывает своим — и обязан такой токен
    отвергнуть. Без своего токена общий интерфейс внутри программы показывал форму
    входа, хотя человек в программу уже вошёл.

    Права это не ослабляет: токен выпускается ТОЛЬКО для уже вошедшего пользователя и
    только на его роль, а сам локальный сервер доступен исключительно с этого
    компьютера (127.0.0.1). Проще говоря, здесь мы не обходим проверку, а признаём уже
    состоявшийся вход — второй раз спрашивать пароль за ту же сессию незачем.

    Заодно заводим запись сессии (AuthSession): без неё сервер отвергает токен с jti как
    отозванный. Побочная польза — локальный выход и отзыв работают ровно как на бою.

    Пустая пара — если что-то не удалось (тогда SPA просто попросит войти)."""
    try:
        prepare_env()
        from app.security import create_token_full
        from app.models import AuthSession
        from app.db import SessionLocal
        from datetime import datetime, timezone
    except Exception as e:
        _LOG.warning(f"[local-api] локальную сессию выпустить не удалось: {e}")
        return "", ""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc).isoformat()
        out = []
        for kind in ("access", "refresh"):
            token, jti, exp = create_token_full(login, role, kind)
            db.merge(AuthSession(jti=jti, login=login, role=role, kind=kind,
                                 device_id="local", ip="127.0.0.1",
                                 issued_at=now, expires_at=exp, revoked=False))
            out.append(token)
        db.commit()
        return out[0], out[1]
    except Exception as e:
        db.rollback()
        _LOG.warning(f"[local-api] сессия не записана: {e}")
        return "", ""
    finally:
        db.close()


def session_works(access: str) -> bool:
    """Пустит ли локальный сервер с этим токеном (проверка ДО показа страницы).

    Причина существовать: SPA на отказ авторизации молча показывает форму входа —
    ошибка выглядит как «ничего не сделали», и разбираться приходится по логам. Один
    запрос по петле стоит миллисекунды и превращает молчаливый провал в честный выбор:
    не пускает — открываем вкладку с боевого сервера, человек видит данные."""
    if not access or not _instance.running:
        return False
    import urllib.error
    import urllib.request
    #`/me/prefs` — самый дешёвый эндпоинт за тем же барьером: не зависит от роли и не
    #требует, чтобы у человека уже были оценки, занятия или группа.
    req = urllib.request.Request(_instance.url("/me/prefs"),
                                 headers={"X-Client": "web",
                                          "Authorization": f"Bearer {access}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        _LOG.warning(f"[local-api] локальная сессия не принята сервером: HTTP {e.code}")
        return False
    except Exception as e:
        _LOG.warning(f"[local-api] локальную сессию проверить не удалось: {e}")
        return False


_instance = LocalAPI()


def instance() -> LocalAPI:
    return _instance


#━━ ПРОКСИ ОНЛАЙН-ПОДСИСТЕМ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#Мессенджер сознательно НЕ входит в синхронизацию (§5.4): переписка живёт только на
#сервере, в локальной копии её нет и быть не должно. Поэтому внутри программы чаты
#открывались ПУСТЫМИ — данных в локальной базе просто нет.
#Ходить за ними напрямую с 127.0.0.1 нельзя: браузер режет кросс-доменный запрос по
#CORS, а раздавать боевому серверу Access-Control-Allow-Origin ради десктопа —
#открывать его любому чужому origin'у. Поэтому пересылает САМ локальный сервер: для
#страницы это тот же адрес (CORS не при чём), а наружу идёт обычный серверный запрос.
#Токен подменяем на БОЕВОЙ: локальный подписан своим секретом, бой его отвергнет.
_PROXY_PREFIXES = ("/web/messenger", "/messenger")


def _remote_auth():
    """(база, боевой токен) текущей сессии ('', '' — офлайн)."""
    try:
        from sync_runner import fresh_auth
        base, token = fresh_auth()
        return (base or "").rstrip("/"), token or ""
    except Exception:
        return "", ""


def install_remote_proxy(app) -> None:
    """Переслать онлайн-подсистемы на боевой сервер. Ошибку НЕ прячем: пустой чат без
    объяснения читается как «сообщения пропали»."""
    from fastapi import Request, Response

    @app.middleware("http")
    async def _proxy_online_subsystems(request: Request, call_next):
        path = request.url.path
        if not path.startswith(_PROXY_PREFIXES):
            return await call_next(request)
        base, token = _remote_auth()
        if not base or not token:
            return Response(content='{"detail":"Нет связи с сервером сообщений."}'.encode(),
                            status_code=503, media_type="application/json")
        import httpx
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ("host", "authorization", "content-length",
                                        "accept-encoding")}
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Client"] = "web"
        try:
            async with httpx.AsyncClient(timeout=25) as cli:
                r = await cli.request(request.method, f"{base}{path}",
                                      params=dict(request.query_params),
                                      content=await request.body(), headers=headers)
            #Заголовки ответа фильтруем: hop-by-hop и кодирование относятся к ТОМУ
            #соединению, а не к нашему — иначе браузер получит битое тело.
            skip = ("content-encoding", "transfer-encoding", "content-length",
                    "connection")
            out = {k: v for k, v in r.headers.items() if k.lower() not in skip}
            return Response(content=r.content, status_code=r.status_code, headers=out)
        except Exception as e:
            _LOG.warning(f"[proxy] {path}: {e}")
            return Response(content='{"detail":"Сервер сообщений не ответил."}'.encode(),
                            status_code=502, media_type="application/json")
