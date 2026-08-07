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
import json
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


def local_db_file(login: str = "", encrypted=None) -> str:
    """Путь к локальной базе КОНКРЕТНОГО пользователя.

    ⚠️ Файл СВОЙ на каждого вошедшего, и это не удобство, а защита. Раньше файл был один
    на машину, и в нём одновременно оказывались данные разных ролей: после сеанса
    преподавателя в базе оставались оценки всей группы, а следующий вошедший студент
    получал к ним доступ (проверено: 44 оценки шести студентов на машине студента).
    Имя файла — хеш логина, а не сам логин: имя учётной записи — тоже персональные
    данные, и светить его в имени файла незачем.

    ⚠️ У ЗАШИФРОВАННОЙ копии ДРУГОЕ ИМЯ («.enc.db»). Одна и та же машина может запускать
    программу двумя способами: собранным .exe (в нём вшит `sqlcipher3`, копия шифруется) и
    из исходников (драйвера может не быть, копия открытая). Пока имя было общим, эти два
    запуска дрались за один файл: копию, зашифрованную .exe, запуск из исходников открыть
    не мог и падал со «file is not a database» — и наоборот. Разные имена разводят их
    навсегда, а не лечат каждый раз заново."""
    import hashlib
    import app_paths
    who = hashlib.sha256((login or "anon").encode("utf-8")).hexdigest()[:16]
    if encrypted is None:
        encrypted = bool(_local_db_key())
    suffix = ".enc" if encrypted else ""
    return app_paths.data_file(f"local_app_{who}{suffix}.db")


def local_db_url(login: str = "") -> str:
    """Адрес локальной базы (схема сервера) в папке данных — .exe остаётся портативным."""
    return "sqlite:///" + local_db_file(login).replace("\\", "/")


def _drop_plaintext_copy(login: str = "") -> None:
    """Снять НЕЗАШИФРОВАННУЮ копию, оставшуюся от прежних версий.

    Зовётся, только когда шифровать ЕСТЬ ЧЕМ. В этом случае открытая копия — чистая
    обуза: в ней лежат ФИО, группы и оценки, читаемые любым просмотрщиком (в том числе с
    украденного диска), а нужды в ней уже нет — рабочая копия зашифрована и лежит под
    ДРУГИМ именем. Содержимое не теряется: копия это кэш, зеркало скачает его заново.

    ⚠️ Целимся в НЕЗАШИФРОВАННОЕ имя явно (`encrypted=False`). Раньше имя было общим, и
    после разделения имён функция чистила бы зашифрованный файл — то есть ровно тот,
    которым сейчас работает программа."""
    path = local_db_file(login, encrypted=False)
    try:
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            if not f.read(16).startswith(b"SQLite format 3"):
                return          #уже зашифрована — не трогаем
    except OSError:
        return
    #⚠️ ЯВНО указываем, что стираем ОТКРЫТУЮ копию. Без этого удалялся бы файл «по
    #умолчанию» — то есть зашифрованный, тот самый, с которым программа сейчас работает.
    if wipe_local_db(login, encrypted=False):
        _LOG.info("[local-api] прежняя НЕЗАШИФРОВАННАЯ копия удалена — данные приедут заново")
    else:
        _LOG.warning("[local-api] НЕЗАШИФРОВАННУЮ копию удалить не удалось — она содержит "
                     "персональные данные, удалите файл вручную")


#Ключ спрашивают часто (в т.ч. на каждое вычисление имени файла), а ответ за время
#работы процесса не меняется: драйвер не появится, ключ устройства не переедет. Без кеша
#в лог сыпалось по шесть одинаковых предупреждений на один запуск.
_key_cache = None


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
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    try:
        import sqlcipher3  # noqa: F401 — проверяем ДОСТУПНОСТЬ драйвера
    except Exception:
        _LOG.warning("[local-api] драйвера sqlcipher3 нет — копия базы без шифрования")
        _key_cache = ""
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
                _key_cache = key.decode("ascii")
                return _key_cache
            #⚠️ НЕ ЗАВОДИМ НОВЫЙ КЛЮЧ поверх существующего файла. Раньше здесь стояло
            #«не расшифровался — заводим новый», и это тихо УНИЧТОЖАЛО офлайн-копию:
            #новый ключ не подходит к уже зашифрованной базе, она превращается в мусор
            #(«hmac check failed»), а вместе с ней пропадает работа без интернета.
            #Причина сбоя DPAPI бывает временной (другая учётная запись Windows, профиль
            #ещё не разблокирован), и терять данные из-за неё нельзя. Честно работаем без
            #шифрования этот сеанс; ключ и копия остаются нетронутыми до выяснения.
            _LOG.warning("[local-api] ключ копии не расшифровался — НЕ трогаем его и не "
                         "перезаписываем базу; этот сеанс без шифрования копии")
            _key_cache = ""
            return ""
        key = binascii.hexlify(_os.urandom(32))
        with open(path, "wb") as f:
            f.write(security.os_protect(key))
        _key_cache = key.decode("ascii")
        return _key_cache
    except Exception as e:
        _LOG.warning(f"[local-api] ключ шифрования не получен: {e}")
        _key_cache = ""
        return ""


def wipe_local_db(login: str = "", encrypted=None) -> bool:
    """Стереть локальную копию — ПО ЯВНОМУ ТРЕБОВАНИЮ, а НЕ при каждом выходе.

    ⚠️ Стирать на выходе НЕЛЬЗЯ: копия и есть offline-first. Без неё следующий запуск без
    сети не покажет ни журнала, ни расписания — то самое обещание, ради которого локальный
    сервер и появился. Поэтому копия живёт между сеансами.
    Изоляцию даёт не стирание, а РАЗДЕЛЬНЫЕ файлы (см. local_db_file): чужую копию
    следующий вошедший просто не открывает. Эта функция — для «выйти и забыть меня»,
    отвязки устройства и очистки перед передачей компьютера другому человеку.
    Вместе с файлом уходит и метка дельты (она внутри базы), поэтому следующий вход
    честно скачает копию заново.

    `encrypted` — какую именно копию стирать (None = ту, с которой работаем сейчас).
    Явный выбор нужен уборке открытой копии: у зашифрованной ДРУГОЕ имя, и без указания
    функция стёрла бы рабочий файл вместо мусорного."""
    import os
    path = local_db_file(login, encrypted=encrypted)
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

    Каталог ищем НЕСКОЛЬКИМИ путями, и это не перестраховка — у каждого своя причина:
    1. Путь ОТ ЭТОГО ФАЙЛА (ui/ → корень репозитория) — от точки запуска не зависит,
       нужен для запуска из исходников и под pytest (там `app_paths.app_dir()`
       отталкивается от каталога САМОГО pytest, и `server/` там не находится вовсе).
    2. `dirname(sys.executable)` — 🔥 ЖИВОЙ БАГ («программа не запускается» — WebView2
       считал локальный сервер недоступным, откатывался на Qt, которого в релизной
       сборке нет вовсе, — окно не открывалось СОВСЕМ, без единого сообщения).
       Под Nuitka onefile `__file__` СКОМПИЛИРОВАННОГО модуля (кандидат 1) не
       резолвится туда, где ФАКТИЧЕСКИ лежат сырые бандл-файлы (`--include-raw-dir=
       server/app=server/app`) — они распаковываются в ОТДЕЛЬНЫЙ кэш
       (`--onefile-tempdir-spec`), а не рядом с настоящим .exe. `sys.executable` под
       Nuitka onefile указывает на bootstrap-python ВНУТРИ этого же кэша (проверено
       отдельной пробной сборкой с тем же `--onefile-tempdir-spec`, что и релиз, +
       прямым осмотром кэша на диске: `server/app` там реально лежит) — то есть это
       ТОЧНО противоположность тому, что нужно `app_paths.app_dir()` (та отвечает
       «где лежит настоящий .exe», см. её докстрин), но ровно то, что нужно здесь.
    3. `app_paths.app_dir()` — последний резерв (PyInstaller/dev, где `sys.executable`
       уже указывает на настоящий .exe и бандл-файлы физически рядом с ним)."""
    import sys
    candidates = []
    here = os.path.dirname(os.path.abspath(__file__))          # …/ui
    candidates.append(os.path.join(os.path.dirname(here), "server"))
    try:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                       "server"))
    except Exception:
        pass
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
    #Логин — из живой сессии, а если её ещё нет, из СОХРАНЁННОЙ (см. `_session_login`).
    #setdefault, а не присваивание: если сервер уже поднят на чьей-то базе, менять адрес
    #на ходу нельзя — SQLAlchemy держит движок с прежним файлом.
    login = _session_login()
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
        #⚠️ ПУСТАЯ СТРОКА, а не удаление переменной. Серверный пакет читает `server/.env`
        #через `os.environ.setdefault` — то есть подставляет СВОЙ ключ в любую переменную,
        #которой нет. Удалив её, мы освобождали место, и локальную копию начинал шифровать
        #ключ из `.env` (чужой, общий, вообще не наш DPAPI-ключ устройства).
        #Последствие было хуже утечки: копия, зашифрованная запуском С драйвером
        #sqlcipher3, не открывалась запуском БЕЗ него — сервер падал на старте
        #(«file is not a database»), и вместе с ним не открывалась вся программа.
        #Переменная, заданная явно (пусть и пустой), `setdefault` уже не перебьёт.
        os.environ["GRADEBOOK_DB_KEY"] = ""
    #Копия могла остаться от запуска с ДРУГИМ набором пакетов (например, была
    #зашифрована SQLCipher, а сейчас драйвера нет) — тогда её нельзя даже открыть.
    _ensure_copy_openable(login, bool(key))


def _ensure_copy_openable(login: str, encrypted: bool) -> None:
    """Убрать в сторону локальную копию, которую НЕЧЕМ открыть, — и дать создать новую.

    Копия базы — ПРОИЗВОДНЫЕ данные: истина живёт на сервере, а сюда она зеркалится
    (`local_mirror`). Поэтому нечитаемый файл это не потеря, а мусор, и единственно
    правильное поведение — начать копию заново. Без этой проверки сервер падал на старте
    («file is not a database»), а вместе с ним не открывалась ВСЯ программа: ровно так и
    случилось на машине, где копию однажды зашифровали, а потом запустили из окружения
    без `sqlcipher3`.

    ⚠️ ПЕРЕИМЕНОВЫВАЕМ, а не удаляем. Файл может оказаться единственным местом, где ещё
    лежат офлайн-правки, не уехавшие на сервер; вернуть их из «.unreadable» можно, из
    небытия — нет. Заодно уносим -wal/-shm: оставшись рядом, они испортят новый файл."""
    path = local_db_file(login)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return
    if _copy_opens(path, encrypted):
        return
    import time
    #⚠️ ВСЁ ИЛИ НИЧЕГО. Если хоть один файл занят другим процессом, отступаем целиком:
    #унести основной файл и оставить его -wal рядом значит собрать «разорванную» копию,
    #которую следующий запуск тоже не откроет. А занятый файл вдобавок означает, что базу
    #прямо сейчас держит другой экземпляр программы — тогда наш вердикт «нечитаема»
    #и вовсе ненадёжен, и правильнее ничего не трогать.
    stamp = time.strftime("%Y%m%d_%H%M%S")
    present = [path + s for s in ("", "-wal", "-shm") if os.path.exists(path + s)]
    for src in present:
        try:
            with open(src, "ab"):
                pass                    #проверка «файл не занят», не изменяя содержимое
        except OSError as e:
            _LOG.warning(f"[local-api] копию держит другой процесс — не трогаем её ({e})")
            return
    moved = []
    for src in present:
        try:
            os.replace(src, f"{src}.unreadable-{stamp}")
            moved.append(os.path.basename(src))
        except OSError as e:
            #Успели унести часть — возвращаем обратно, чтобы не оставить половину.
            for done in moved:
                try:
                    os.replace(os.path.join(os.path.dirname(path),
                                            f"{done}.unreadable-{stamp}"),
                               os.path.join(os.path.dirname(path), done))
                except OSError:
                    pass
            _LOG.warning(f"[local-api] не удалось убрать нечитаемую копию {src}: {e}")
            return
    _LOG.warning("[local-api] локальная копия нечитаема — начинаем заново "
                 f"(старая сохранена как *.unreadable-{stamp}): {', '.join(moved)}")


def _copy_opens(path: str, encrypted: bool) -> bool:
    """Открывается ли файл тем же способом, каким его откроет серверный пакет."""
    key = os.environ.get("GRADEBOOK_DB_KEY", "") if encrypted else ""
    try:
        if key:
            try:
                import sqlcipher3 as _sq
            except Exception:
                import sqlite3 as _sq          #драйвера нет — откроется как обычный SQLite
        else:
            import sqlite3 as _sq
        con = _sq.connect(path)
        try:
            cur = con.cursor()
            if key:
                #Тот же формат ключа, что в server/app/db.py.
                cur.execute(f"PRAGMA key=\"x'{key}'\"")
            cur.execute("PRAGMA schema_version")   #дешёвое чтение заголовка
            cur.fetchone()
            return True
        finally:
            con.close()
    except Exception as e:
        _LOG.info(f"[local-api] копия не открывается ({e})")
        return False


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
                install_desktop_bootstrap(app)
                install_remote_proxy(app)
                #Мост входа нужен ЛЮБОЙ оболочке, а не только новой: как только форма
                #входа становится веб-овой, локальная копия обязана уметь пускать
                #человека офлайн и сходить на бой при первом входе на этой машине.
                install_login_bridge(app)
                #Раздел «Сервер»: управление боевой машиной по SSH. Живёт ТОЛЬКО здесь,
                #в локальном сервере программы. На бою этого кода нет вовсе — там
                #работает `routers/serverinfo.py`, который умеет только смотреть.
                #Граница проходит по наличию кода, а не по проверке роли: роль можно
                #обойти, отсутствующий код — нельзя (см. шапку ui/server_admin.py).
                import server_admin
                server_admin.install(app, _local_caller_ok)
            except Exception as e:
                _LOG.warning(f"[local-api] надстройки локального сервера не встали: {e}")

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


def _session_login() -> str:
    """Кто работает в программе: живая сессия, иначе — сохранённая на этой машине.

    ⚠️ ФОЛБЭК НА СОХРАНЁННУЮ СЕССИЮ ОБЯЗАТЕЛЕН, и вот почему. С появлением ЛИЧНОЙ копии
    базы у каждого пользователя (файл на логин) сервер на холодном старте поднимался на
    «анонимной» копии: `current_login()` до входа пуст. В ней нужного человека нет,
    поэтому `user_exists` отвечал «нет», оболочка не отдавала сессию и открывала форму
    входа — при живом сохранённом входе и целой личной копии. Со стороны это выглядело
    как «программа каждый раз разлогинивает и сбрасывает тему»: тема приезжает той же
    страницей-передатчиком, что и сессия, и вместе с ней не доезжала.

    Доверять сохранённой сессии здесь не новость: `webview2_app._start_url` брал логин
    ровно оттуда с самого начала — расходились только эти два места."""
    try:
        from sync_runner import current_login
        live = current_login()
        if live:
            return live
    except Exception:      # noqa: BLE001
        pass
    try:
        import app_settings
        return ((app_settings.get_saved_session() or {}).get("login") or "").strip()
    except Exception:      # noqa: BLE001
        return ""


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
#⚠️ «/web/admin/server» ЗДЕСЬ ОБЯЗАТЕЛЕН. Раздел «Сервер» рассказывает про БОЕВУЮ
#машину, а внутри программы страница говорит с ЛОКАЛЬНЫМ сервером — и без пересылки
#показывала диск, память и базу компьютера администратора вместо VPS. Со стороны это
#выглядит как правдоподобная ложь: цифры настоящие, но не про тот компьютер.
#⚠️ (живой отзыв Влада) ЭТОТ ЖЕ БАГ БЫЛ ЕЩЁ В ЧЕТЫРЁХ МЕСТАХ, найдено сверкой:
#`/me/prefs` (тема, аватар, «о себе», цвет плашки, стиль никнейма, настройки
#уведомлений) и `/me/events` (сама вкладка «Уведомления») — НЕ синхронизируемые поля
#(`User.prefs`/`NotifyEvent` не в SYNC_MODELS), и вдобавок `PUSH_SCOPE` для
#teacher/student вообще не включает "users" — значит правки профиля/темы, сделанные
#ВНУТРИ десктопа без этой пересылки, не просто не долетали до сайта, а физически не
#МОГЛИ долететь и терялись при следующей синхронизации (сервер = истина, §4
#инвариант 5). `/web/staff/parents`/`/web/staff/parent-links`/`/web/admin/parents` —
#привязки родителей, тоже не синкаются (ParentLink не в SYNC_MODELS), поэтому список
#привязанных родителей в локальной копии всегда пуст. Разбор ПО ТОЙ ЖЕ логике, что
#выше: если данные не входят в offline-first синк — единственный источник правды для
#них ВСЕГДА бой, и без пересылки внутри десктопа их просто неоткуда взять.
_PROXY_PREFIXES = ("/web/messenger", "/messenger", "/web/admin/server",
                   "/me/prefs", "/me/events",
                   "/web/staff/parents", "/web/staff/parent-links", "/web/admin/parents")


#Что именно недоступно — зависит и от пути, и от ПРИЧИНЫ. Два прежних текста врали в
#самых частых случаях: «Сервер сообщений не ответил» на странице состояния отправляло
#чинить мессенджер, которого не трогали, а «нет связи» при живом интернете — к
#провайдеру, тогда как истёк всего лишь пятичасовой токен (§6).
#Подставляется в винительном падеже («показать состояние», «показать сообщения») —
#так одна формулировка годится и для среднего рода, и для множественного числа.
_WHAT = {"/web/admin/server": "состояние", "/web/messenger": "сообщения",
         "/messenger": "сообщения", "/me/prefs": "профиль", "/me/events": "уведомления",
         "/web/staff/parents": "родителей", "/web/staff/parent-links": "родителей",
         "/web/admin/parents": "родителей"}


def _offline_reason(path: str, why: str = "offline") -> str:
    what = next((v for k, v in _WHAT.items() if path.startswith(k)), "эти данные")
    if why == "expired":
        return (f"Сессия на сервере истекла — показать {what} сейчас не можем. "
                "Выйдите и войдите заново, чтобы обновить доступ. "
                "Журнал и расписание работают и без этого.")
    if why == "no-url":
        return "Адрес сервера не задан — укажите его в настройках программы."
    if why == "no-session":
        return "Вход в программу не выполнен."
    return f"Нет связи с сервером — {what} показать не можем."


def _remote_auth():
    """(база, боевой токен) текущей сессии ('', '' — связи нет или вход не выполнялся).

    ⚠️ ЖИВОЙ СЕССИИ НА ХОЛОДНОМ СТАРТЕ ЕЩЁ НЕТ. `sync_runner` получает креды в момент
    входа, а программа, открытая по СОХРАНЁННОЙ сессии, входа не проходит — токен в нём
    пуст, хотя на диске лежат и access, и refresh. Пока фолбэка не было, любая
    пересылаемая страница (мессенджер, раздел «Сервер») отвечала «нет связи с сервером»
    при совершенно живом интернете — а человек шёл проверять сеть и провайдера.

    Порядок тот же, что и везде в этом файле: живое → сохранённое. Протухший access
    обновляем по refresh и СРАЗУ сохраняем: иначе обновление повторялось бы на каждый
    запрос, а 5-часовой токен успевает протухнуть между запусками почти всегда.

    Третьим значением возвращаем ПРИЧИНУ отказа. Она не для красоты: «нет связи»,
    показанное при живом интернете и истёкшей сессии, отправляет человека проверять
    провайдера вместо того, чтобы просто войти заново."""
    base = ""
    try:
        from sync_runner import fresh_auth
        base, token = fresh_auth()
        base = (base or "").rstrip("/")
        if token:
            return base, token, ""
    except Exception:      # noqa: BLE001
        pass

    try:
        import app_settings
        base = base or (app_settings.get_api_url() or "").rstrip("/")
        if not base:
            return "", "", "no-url"
        login = _session_login()
        if not login:
            return base, "", "no-session"
        token = app_settings.get_saved_token(login) or ""
        from sync_client import is_token_expired
        if token and not is_token_expired(token):
            return base, token, ""

        refresh = app_settings.get_saved_refresh_token(login) or ""
        if not refresh:
            return base, "", "expired"
        from sync_client import SyncClient
        data = SyncClient(base, token, refresh).refresh() or {}
        fresh = (data.get("access_token") or "").strip()
        if not fresh:
            return base, "", "expired"
        app_settings.set_saved_token(login, fresh)
        if data.get("refresh_token"):
            app_settings.set_saved_refresh_token(login, data["refresh_token"])
        _LOG.info("[local-api] боевой токен обновлён по сохранённому refresh")
        return base, fresh, ""
    except Exception as e:      # noqa: BLE001 — нет сети/отозван токен: это не авария
        _LOG.info(f"[local-api] боевой токен недоступен: {e}")
        #401 на refresh — это НЕ сеть, а истёкшая сессия (JWT живёт жёстко 5 ч, §6).
        expired = "401" in str(e) or "Unauthorized" in str(e)
        return base, "", ("expired" if expired else "offline")


def _local_caller_ok(authorization: str) -> bool:
    """Пришёл ли запрос от вошедшего человека (проверка ЛОКАЛЬНОГО токена).

    Прокси уходит на бой с чужими правами, поэтому пускать в него можно только того, кто
    уже прошёл вход в программе. Логин из токена обязан совпасть с логином сессии: иначе
    старый токен от прошлого пользователя открывал бы переписку нового."""
    prefix = "bearer "
    if not authorization or not authorization.lower().startswith(prefix):
        return False
    token = authorization[len(prefix):].strip()
    try:
        prepare_env()
        from app.security import decode_token
        data = decode_token(token) or {}
    except Exception:
        return False
    login = (data.get("sub") or "").strip()
    if not login:
        return False
    #Сверяем с ТЕМ ЖЕ источником, что и всё остальное (`_session_login`): живая сессия,
    #иначе сохранённая. Раньше здесь стояла ТОЛЬКО живая, и получалось несогласованно —
    #страница-передатчик выпускала токен для сохранённого пользователя, а прокси этот же
    #токен отвергал с 401. Для страницы 401 значит «сессия истекла», и она выкидывала
    #человека из аккаунта ровно в тот момент, когда он открывал раздел «Сервер».
    #Строгость при этом не падает: чужой логин по-прежнему не проходит, а сохранённая
    #сессия появляется только после успешного входа на этой машине.
    expected = _session_login()
    return bool(expected) and login == expected


def install_remote_proxy(app) -> None:
    """Переслать онлайн-подсистемы на боевой сервер. Ошибку НЕ прячем: пустой чат без
    объяснения читается как «сообщения пропали»."""
    from fastapi import Request, Response

    @app.middleware("http")
    async def _proxy_online_subsystems(request: Request, call_next):
        path = request.url.path
        if not path.startswith(_PROXY_PREFIXES):
            return await call_next(request)
        #🔒 СНАЧАЛА проверяем, КТО спрашивает, и только потом подставляем боевой токен.
        #Без этой проверки прокси был дырой: он подменял Authorization токеном вошедшего,
        #не глядя на присланный, — значит переписку мог прочитать (и писать от лица
        #человека) ЛЮБОЙ процесс на этом компьютере, а с браузерной страницы это ещё и
        #обычный CSRF: адрес петли доступен любому сайту, открытому у пользователя.
        #Барьер тот же, что у остальных эндпоинтов локального сервера, — свой токен.
        if not _local_caller_ok(request.headers.get("authorization", "")):
            return Response(content='{"detail":"Требуется авторизация"}'.encode(),
                            status_code=401, media_type="application/json")
        base, token, why = _remote_auth()
        if not base or not token:
            body = json.dumps({"detail": _offline_reason(path, why)}, ensure_ascii=False)
            #503, а НЕ 401: 401 страница трактует как «сессия истекла» и выкидывает из
            #аккаунта — а локальная сессия жива, и журнал с расписанием работают.
            return Response(content=body.encode(), status_code=503,
                            media_type="application/json")
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
            #Сюда попадаем, когда запрос УЖЕ ушёл и оборвался, — это именно сеть.
            body = json.dumps({"detail": _offline_reason(path, "offline")},
                              ensure_ascii=False)
            return Response(content=body.encode(), status_code=502,
                            media_type="application/json")


#━━ ПЕРЕДАЧА СЕССИИ ЛЮБОЙ ОБОЛОЧКЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#Раньше сессия попадала в страницу инъекцией JS до загрузки — приём, который умеет
#именно QtWebEngine (DocumentCreation). Оболочку мы меняем, и опираться на её частную
#способность больше нельзя: у WebView2 такого хука в нашей обвязке нет.
#Поэтому сессию отдаёт САМ локальный сервер: короткая страница кладёт всё в localStorage
#и уходит на нужный маршрут. Работает с любым движком, включая нынешний.
#🔒 Токенов в АДРЕСЕ нет намеренно: адреса попадают в историю и логи, а сервер и так
#знает, кто вошёл, — он выпускает сессию сам. Снаружи страница недостижима: сервер
#слушает только петлю.
_BOOTSTRAP_PATH = "/desktop/bootstrap"


def install_desktop_bootstrap(app) -> None:
    """Маршрут, который отдаёт странице сессию, тему и режим встраивания."""
    import json as _json

    from fastapi import Request
    from fastapi.responses import HTMLResponse

    @app.get(_BOOTSTRAP_PATH, response_class=HTMLResponse)
    def _bootstrap(request: Request, route: str = "/", embed: str = "0"):
        #Тот же источник, что и у базы (см. `_session_login`): раньше здесь бралась
        #ТОЛЬКО живая сессия, и на холодном старте логин был пуст — страница отдавала
        #пустой токен, а SPA показывала форму входа уже вошедшему человеку.
        login = _session_login()
        role = ""
        try:
            import app_settings
            role = (app_settings.get_saved_session() or {}).get("role", "") or ""
        except Exception:
            pass
        access, refresh = ("", "")
        if login:
            access, refresh = issue_local_session(login, role or "student")
        theme = ""
        try:
            import themes
            spec = themes.active_spec()
            if spec:
                theme = _json.dumps(spec)
        except Exception:
            pass
        user = _json.dumps({"login": login, "role": role, "name": login})
        #⚠️ dumps ДВАЖДЫ для gb.user: внутренний даёт JSON, внешний — строковый литерал JS.
        #С одним dumps браузер сохранял «[object Object]», разбор падал, и SPA показывала
        #форму входа человеку, который уже вошёл (ловили это в 3.4).
        #Маршрут прогоняем через json.dumps тоже — он приходит извне, и «"+alert(1)+"» в
        #нём не должен превратиться в код.
        parts = [
            f"localStorage.setItem('gb.access',{_json.dumps(access)});",
            f"localStorage.setItem('gb.refresh',{_json.dumps(refresh or access)});",
            f"localStorage.setItem('gb.user',{_json.dumps(user)});",
            "localStorage.setItem('gb.api_base','');",
            f"localStorage.setItem('gb.embed',{_json.dumps(embed)});",
        ]
        if theme:
            parts.append(f"localStorage.setItem('gb.theme',{_json.dumps(theme)});")
        parts.append(f"location.replace({_json.dumps(route or '/')});")
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><title>GradeBookAI</title>"
            "<body style='background:#0f1b22'></body>"
            "<script>try{" + "".join(parts) + "}catch(e){document.body.innerText=e;}</script>")

    #⚠️ В НАЧАЛО списка маршрутов. Приложение раздаёт SPA заглушкой «всё остальное →
    #index.html», она зарегистрирована раньше и перехватила бы наш адрес: сервер честно
    #отвечал 200, но отдавал обычную страницу, а сессия не приезжала. Маршруты
    #сопоставляются по порядку, поэтому свой ставим первым.
    app.router.routes.insert(0, app.router.routes.pop())


def bootstrap_url(route: str = "/", embed: str = "0") -> str:
    """Адрес страницы-передатчика сессии для оболочки ('' — сервер не поднят)."""
    from urllib.parse import urlencode
    if not _instance.port:
        return ""
    return _instance.url(_BOOTSTRAP_PATH) + "?" + urlencode({"route": route, "embed": embed})


#━━ МОСТ ВХОДА: локально, а если человека тут ещё нет — через боевой сервер ━━━━━━━━━━
#Без него общий интерфейс не может заменить нативный экран входа: локальная копия базы
#создаётся ПОД конкретного человека, и до первого входа его там просто нет. Форма
#честно отвечала бы «неверный логин или пароль» тому, у кого всё верно.
#
#Порядок «сначала локально» ВАЖЕН и обратный неверен: он и даёт offline-first. Хеш
#владельца сессии в локальной копии есть (чужие сервер вырезает при выдаче), поэтому без
#сети человек входит в свой кабинет как обычно. В сеть идём, только когда локально не
#вышло, — то есть при первом входе на этой машине или после смены пароля.
def install_login_bridge(app) -> None:
    """POST /auth/login: локальная проверка → при неудаче боевой сервер → СВОЙ токен."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.post("/auth/login")
    async def _login(request: Request):
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        login = (body.get("login") or "").strip()
        password = body.get("password") or ""
        if not login or not password:
            return JSONResponse({"detail": "Введите логин и пароль"}, status_code=400)

        local = _try_local_login(login, password)
        if local is not None:
            _remember_session(login, password, local.get("role", ""))
            return JSONResponse(local)

        #Человека в текущей копии нет — возможно, она ещё «анонимная» (сервер поднялся
        #до входа). Переключаемся на ЕГО базу и пробуем ещё раз: вдруг он уже заходил на
        #этой машине и его копия лежит готовая — тогда вход останется офлайновым.
        if switch_user_db(login):
            local = _try_local_login(login, password)
            if local is not None:
                _remember_session(login, password, local.get("role", ""))
                return JSONResponse(local)

        remote = _try_remote_login(login, password)
        if remote is None:
            #Ни локально, ни на бою. Причину не разделяем на «нет сети» и «неверный
            #пароль» намеренно: подсказка «такой логин есть, но пароль не тот» — это
            #подсказка и подбирающему тоже.
            return JSONResponse({"detail": "Неверный логин или пароль, либо нет связи."},
                                status_code=401)

        role = remote.get("role") or "student"
        _remember_session(login, password, role)
        #🔒 ГЛАВНОЕ: до синхронизации переключаем базу на ЛИЧНУЮ копию этого человека.
        #Без этого его данные легли бы в общий «анонимный» файл, и следующий вошедший на
        #этом компьютере увидел бы чужие оценки — ровно та утечка, ради которой копии и
        #сделаны раздельными (см. local_db_file).
        switch_user_db(login)
        #Зеркало могло ещё не докачать человека — тогда `/web/*` ответит «нет доступа», и
        #в кабинете будет пусто. Ждём ОДИН короткий цикл, но не блокируем вход навсегда:
        #лучше пустоватый кабинет, который наполнится, чем висящая форма входа.
        _wait_for_mirror(login, seconds=12)
        access, refresh = issue_local_session(login, role)
        if not access:
            #Локальную сессию выпустить не удалось (человека всё ещё нет в копии) —
            #отдаём боевые токены: кабинет будет работать через прокси, пока не докачается.
            return JSONResponse(remote)
        out = dict(remote)
        out["access_token"], out["refresh_token"] = access, refresh
        return JSONResponse(out)

    #В НАЧАЛО: иначе сработает штатный /auth/login серверного приложения (см. тот же
    #приём и ту же причину у bootstrap-маршрута выше).
    app.router.routes.insert(0, app.router.routes.pop())


def _try_local_login(login: str, password: str):
    """Проверить пароль по ЛОКАЛЬНОЙ копии. None — не вышло (нет человека/не тот пароль)."""
    try:
        prepare_env()
        from app.db import SessionLocal
        from app.models import User
        from app.security import verify_password
        db = SessionLocal()
        try:
            user = (db.query(User)
                    .filter(User.login == login, User.deleted == False)  # noqa: E712
                    .first())
            if user is None or not user.password_hash:
                return None
            if not verify_password(password, user.password_hash):
                return None
            access, refresh = issue_local_session(user.login, user.role or "student")
            if not access:
                return None
            #⚠️ (живой отзыв Влада) Раньше здесь ФИО собиралось ТОЛЬКО из surname+name —
            #это поля СТУДЕНЧЕСКОЙ конвенции (см. докстринг User.name в models.py: «ключ
            #ОЦЕНОК»), а у преподавателя основное поле — full_name (models.py: «ФИО, у
            #преподавателя — КЛЮЧ»). У препода с пустыми surname/name (обычный случай)
            #строка схлопывалась в пустоту и откатывалась на login — карточка профиля
            #показывала логин ДВАЖДЫ вместо ФИО+логина. Тот же порядок проверки, что и на
            #бою (`routers/auth.py`: `user.full_name or f"{surname} {name}".strip()`).
            name = (user.full_name or f"{user.surname or ''} {user.name or ''}".strip()
                    or user.login)
            return {"access_token": access, "refresh_token": refresh,
                    "role": user.role or "student", "name": name}
        finally:
            db.close()
    except Exception as e:
        _LOG.info(f"[login] локальная проверка не удалась: {e}")
        return None


def _try_remote_login(login: str, password: str):
    """Войти на БОЕВОМ сервере. None — не вышло (нет сети или неверные данные)."""
    try:
        import app_settings
        base = (app_settings.get_api_url() or "").rstrip("/")
    except Exception:
        base = ""
    if not base:
        return None
    try:
        import httpx
        r = httpx.post(f"{base}/auth/login", json={"login": login, "password": password},
                       headers={"X-Client": "web"}, timeout=20.0)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        _LOG.info(f"[login] боевой сервер недоступен: {e}")
        return None


def _remember_session(login: str, password: str, role: str) -> None:
    """Отдать вход слою синхронизации — ровно как это делал нативный экран входа.

    Пароль остаётся В ПАМЯТИ процесса (инвариант §7: на диск он не пишется). Он нужен
    синхронизации, чтобы переполучать токен: боевой JWT живёт жёстко 5 часов."""
    try:
        from sync_runner import start as _sync_start
        _sync_start(login, password, role or "student")
    except Exception as e:
        _LOG.warning(f"[login] синхронизация не запустилась: {e}")
    try:
        import app_settings
        app_settings.set_saved_session(login, role or "student")
    except Exception:
        pass


def _wait_for_mirror(login: str, seconds: int = 12) -> bool:
    """Дождаться, пока человек появится в локальной копии (после первого входа)."""
    import time
    try:
        from local_mirror import mirror_once
        mirror_once()
    except Exception:
        pass
    edge = time.time() + max(1, seconds)
    while time.time() < edge:
        if user_exists(login):
            return True
        time.sleep(0.5)
    return user_exists(login)


def switch_user_db(login: str) -> bool:
    """Переключить локальный сервер на ЛИЧНУЮ копию базы этого пользователя.

    Зачем это вообще нужно. Форма входа стала веб-овой, значит сервер поднимается ДО
    того, как известно, кто войдёт, — на «анонимной» базе. А копия у каждого своя
    (изоляция данных). Значит после входа привязку надо сменить, иначе всё ляжет в общий
    файл и следующий вошедший прочитает чужие оценки.

    Возвращает True, если после переключения база готова к работе. Ошибку не поднимаем:
    вход важнее, а без переключения кабинет всё равно откроется (просто на прежней базе),
    и это лучше, чем не пустить человека вовсе.
    """
    if not login:
        return False
    try:
        prepare_env()
        target = local_db_url(login)
        from app import db as _db
        if getattr(_db, "DATABASE_URL", "") == target:
            return True                     #уже на нужной базе — переключать нечего
        #Копию могли зашифровать другим ключом/другим запуском — проверяем ДО привязки,
        #иначе сервер упадёт на первом же обращении («file is not a database»).
        _ensure_copy_openable(login, bool(_local_db_key()))
        _db.rebind(target, os.environ.get("GRADEBOOK_DB_KEY", ""))
        os.environ["GRADEBOOK_DB_URL"] = target
        _LOG.info("[local-api] база переключена на личную копию пользователя")
        return True
    except Exception as e:      # noqa: BLE001 — не пускать человека из-за этого нельзя
        _LOG.warning(f"[local-api] не удалось переключить базу на личную копию: {e}")
        return False
