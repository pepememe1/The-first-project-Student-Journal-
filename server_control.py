"""
server_control.py — Управление сервером синхронизации С ЭТОГО ПК (модель «хост»).

Зачем. В небольшом колледже один ПК может быть и рабочим местом администратора,
и сервером синхронизации. Этот модуль позволяет из админ-панели десктопа:
  • выбрать движок серверной БД — SQLite (по умолчанию) или PostgreSQL;
  • записать выбор в server/.env (переменная GRADEBOOK_DB_URL — её читает сервер);
  • проверить подключение к PostgreSQL;
  • запустить/остановить сам сервер (FastAPI/uvicorn) — ВНУТРИ этой же программы,
    отдельным потоком (не нужен отдельный Python снаружи);
  • узнать его состояние (по эндпоинту /health).

Пока программа открыта — сервер работает; закрыли программу — сервер
останавливается вместе с ней. Для круглосуточного сервера используйте боевое
развёртывание (systemd) из server/DEPLOY.md.

ВАЖНО (архитектура): это нужно только НА ОДНОМ ПК — том, который будет сервером.
Клиентские ПК сюда не лезут — они лишь указывают адрес этого сервера в «Адрес
сервера» и работают по API. К PostgreSQL клиенты не подключаются вообще: строка
подключения к БД живёт только здесь, в server/.env, и наружу не раздаётся.

⚠️ Пароль PostgreSQL серверу нужен открытым (так устроен любой backend), поэтому
он лежит в server/.env. Файл вне Git (.gitignore) и кладётся рядом с сервером;
права на него сужаем. Не копируйте server/.env на чужие машины.
"""
import os
import re
import sys
import socket
import threading
import subprocess

#Папка сервера лежит рядом с клиентскими модулями (репозиторий) — и в dev, и при
#запуске из исходников. Берём абсолютный путь относительно этого файла.
_HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(_HERE, "server")
ENV_PATH = os.path.join(SERVER_DIR, ".env")

DEFAULT_PORT = 8000
SQLITE_URL = "sqlite:///./gradebook_server.db"

#Сервер запускается ВНУТРИ этого же процесса (отдельным потоком), чтобы не нужен
#был отдельный Python — одна кнопка «Запустить» в админке и всё работает.
_server = None     #uvicorn.Server текущего запуска
_thread = None     #поток, в котором крутится сервер

#Туннель «доступ из интернета» (ssh -R на serveo.net). Поднимается отдельной
#кнопкой в админке: сервер крутится на этом ПК, а туннель показывает его наружу,
#чтобы коллеги с других сетей могли подключиться. Внешний ssh уже встроен в
#Windows 10/11, ставить ничего не нужно.
_tunnel_proc = None    #subprocess.Popen запущенного ssh
_tunnel_url = ""       #публичный адрес, который выдал serveo (https://…)


#Чтение/запись server/.env (простой формат KEY=VALUE)
def read_env() -> dict:
    """Возвращает текущие переменные из server/.env (пусто, если файла нет)."""
    out = {}
    try:
        if os.path.exists(ENV_PATH):
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    except Exception as e:
        print(f"[server_control] не удалось прочитать .env: {e}")
    return out


def _write_env(values: dict) -> bool:
    """Перезаписывает server/.env заданными парами KEY=VALUE и сужает права."""
    try:
        os.makedirs(SERVER_DIR, exist_ok=True)
        lines = [
            "# server/.env — конфигурация сервера. Сгенерировано админ-панелью.",
            "# НЕ коммитить и не копировать на чужие ПК (тут реквизиты БД).",
        ]
        for k, v in values.items():
            lines.append(f"{k}={v}")
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        try:
            os.chmod(ENV_PATH, 0o600)   #только владелец (на не-Windows строго)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[server_control] не удалось записать .env: {e}")
        return False


def _ensure_jwt_secret(values: dict) -> dict:
    """Гарантирует наличие НЕдефолтного секрета JWT (иначе токены небезопасны).
    Если секрета нет или это плейсхолдер — генерируем длинный случайный."""
    secret = values.get("GRADEBOOK_JWT_SECRET", "")
    if not secret or "change" in secret.lower():
        import secrets
        values["GRADEBOOK_JWT_SECRET"] = secrets.token_urlsafe(48)
    return values


def build_pg_url(host: str, port: str, db: str, user: str, password: str) -> str:
    """Собирает строку подключения PostgreSQL. Пароль URL-кодируем — в нём могут
    быть символы @ : / и т.п., иначе строка подключения разъедется."""
    from urllib.parse import quote_plus
    host = (host or "localhost").strip()
    port = str(port or "5432").strip()
    db = (db or "vsgutu_grades").strip()
    user = quote_plus((user or "").strip())
    pw = quote_plus(password or "")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


#Текущий режим БД
def get_db_url() -> str:
    return read_env().get("GRADEBOOK_DB_URL", SQLITE_URL)


def is_postgres() -> bool:
    return get_db_url().startswith("postgresql")


#Сохранение выбора движка
def use_sqlite() -> bool:
    """Переключает сервер на SQLite (значение по умолчанию)."""
    env = read_env()
    env["GRADEBOOK_DB_URL"] = SQLITE_URL
    return _write_env(_ensure_jwt_secret(env))


def use_postgres(host: str, port: str, db: str, user: str, password: str) -> bool:
    """Переключает сервер на PostgreSQL с указанными реквизитами."""
    env = read_env()
    env["GRADEBOOK_DB_URL"] = build_pg_url(host, port, db, user, password)
    return _write_env(_ensure_jwt_secret(env))


def test_postgres(host: str, port: str, db: str, user: str, password: str) -> tuple:
    """Проверяет подключение к PostgreSQL. (True, версия) или (False, причина)."""
    try:
        import psycopg2
    except ImportError:
        return False, ("Драйвер psycopg2 не установлен. Установите зависимости "
                       "сервера: pip install -r server/requirements.txt")
    try:
        conn = psycopg2.connect(
            host=(host or "localhost").strip(), port=int(port or 5432),
            dbname=(db or "vsgutu_grades").strip(), user=(user or "").strip(),
            password=password or "", connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT version()")
        ver = cur.fetchone()[0]
        conn.close()
        return True, ver
    except Exception as e:
        return False, str(e)


#Запуск / остановка / статус сервера
def _abs_sqlite_path() -> str:
    """Абсолютный путь к файлу SQLite сервера (рядом с папкой server).
    Берём абсолютный, потому что in-process у нас может быть любой рабочий каталог,
    а относительный 'sqlite:///./...' зависел бы от него."""
    return os.path.join(SERVER_DIR, "gradebook_server.db")


def _db_url_for_runtime() -> str:
    """Строка подключения для запуска. SQLite приводим к абсолютному пути."""
    url = get_db_url()
    if url.startswith("sqlite") and "./" in url:
        return "sqlite:///" + _abs_sqlite_path().replace("\\", "/")
    return url


def server_running(port: int = DEFAULT_PORT, timeout: float = 1.0) -> bool:
    """True, если сервер отвечает на /health."""
    try:
        import requests
        r = requests.get(f"http://127.0.0.1:{port}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def lan_ip() -> str:
    """IPv4-адрес этого ПК в локальной сети — его дают клиентам при «прямом»
    доступе (ВСГУТУ-сервер в ЛВС). Открываем UDP-сокет «наружу» (НИЧЕГО не шлём),
    ОС сама выбирает исходящий интерфейс — его адрес и берём. Строго AF_INET, без
    IPv6. '' — если определить не удалось (тогда подскажем 127.0.0.1)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return ""


def start_server(port: int = DEFAULT_PORT) -> tuple:
    """Запускает сервер ВНУТРИ этой программы (отдельным потоком). Внешний Python
    не нужен. (True, сообщение) или (False, причина)."""
    global _server, _thread
    if server_running(port):
        return True, "Сервер уже запущен."
    if _thread is not None and _thread.is_alive():
        return True, "Сервер уже запускается."
    if not os.path.isdir(SERVER_DIR):
        return False, f"Папка сервера не найдена: {SERVER_DIR}"
    if _port_busy(port):
        return False, f"Порт {port} занят другим процессом."

    #Гарантируем .env с движком БД и секретом JWT.
    env_vals = read_env()
    if "GRADEBOOK_DB_URL" not in env_vals:
        env_vals["GRADEBOOK_DB_URL"] = SQLITE_URL
    _write_env(_ensure_jwt_secret(env_vals))
    #Прокидываем настройки в окружение ДО импорта сервера (его config читает env).
    for k, v in read_env().items():
        os.environ[k] = v
    os.environ["GRADEBOOK_DB_URL"] = _db_url_for_runtime()
    #device_id этого ПК — чтобы сервер всегда пропускал ХОСТА через барьер подтверждения
    #(на нём админ поднимает сервер и одобряет остальных — сам себя одобрить было бы
    #некому). Сервер читает GRADEBOOK_HOST_DEVICE_ID при проверке устройства (connect.py).
    try:
        import app_settings
        host_dev = app_settings.get_device_id()
        if host_dev:
            os.environ["GRADEBOOK_HOST_DEVICE_ID"] = host_dev
    except Exception as e:
        print(f"[server_control] device_id хоста не выставлен: {e}")

    #Папку server делаем импортируемой и поднимаем приложение в потоке.
    if SERVER_DIR not in sys.path:
        sys.path.insert(0, SERVER_DIR)
    try:
        import uvicorn
        from app.main import app   #пакет server/app
    except Exception as e:
        return False, ("Не удалось загрузить сервер. На ПК-сервере нужны его "
                       "зависимости — установите их один раз командой:\n"
                       "pip install -r server/requirements.txt\n\n"
                       f"Подробность: {e}")

    #uvicorn в НЕглавном потоке сам пропускает установку обработчиков сигналов —
    #это штатно. Поднимаем сервер и ждём, пока ответит /health.
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    _server = uvicorn.Server(config)
    _thread = threading.Thread(target=_server.run, daemon=True)
    _thread.start()

    import time
    for _ in range(30):                      #до ~15 секунд на старт
        if server_running(port):
            return True, f"Сервер запущен на порту {port}."
        if not _thread.is_alive():
            return False, ("Сервер не стартовал. Проверьте доступность БД "
                           "(для PostgreSQL — что она запущена и реквизиты верны).")
        time.sleep(0.5)
    return False, "Сервер запускается дольше обычного — проверьте состояние позже."


def stop_server(port: int = DEFAULT_PORT) -> tuple:
    """Останавливает сервер, запущенный этой программой."""
    global _server, _thread
    if _server is not None:
        _server.should_exit = True           #штатная остановка uvicorn
        if _thread is not None:
            _thread.join(timeout=10)
    _server = None
    _thread = None
    if not server_running(port):
        return True, "Сервер остановлен."
    return False, ("Сервер ещё отвечает. Если его запускали другим способом — "
                   "остановите тот процесс вручную.")


#Туннель «доступ из интернета» (ssh -R на serveo.net)
#Зачем отдельно от сервера: сервер слушает только локальную сеть (0.0.0.0), а
#коллеги с ДРУГИХ интернетов так его не увидят. Туннель пробрасывает локальный
#порт на публичный адрес serveo, который виден из любой точки.

#Имя поддомена храним в server/.env, чтобы адрес был ПОСТОЯННЫМ между запусками
#(serveo закрепляет занятое имя за этим ПК) — иначе он менялся бы каждый раз и
#api_config друзьям пришлось бы обновлять.
def get_tunnel_name() -> str:
    return read_env().get("GRADEBOOK_TUNNEL_NAME", "").strip()


def set_tunnel_name(name: str) -> bool:
    env = read_env()
    env["GRADEBOOK_TUNNEL_NAME"] = (name or "").strip()
    return _write_env(env)


#Режим доступа к серверу — чтобы при следующем открытии админки восстановить выбор
#типа сервера. 'serveo' — доступ из интернета через туннель; 'direct' — сервер
#виден напрямую (локальная сеть / свой домен). Это настройка ПК-хоста, живёт в .env
#рядом с прочей серверной конфигурацией.
def get_access_mode() -> str:
    """'serveo' или 'direct' (по умолчанию — 'direct', т.е. ВСГУТУ-сервер в ЛВС)."""
    mode = read_env().get("GRADEBOOK_ACCESS_MODE", "").strip().lower()
    return "serveo" if mode == "serveo" else "direct"


def set_access_mode(mode: str) -> bool:
    env = read_env()
    env["GRADEBOOK_ACCESS_MODE"] = "serveo" if (mode or "").strip().lower() == "serveo" else "direct"
    return _write_env(env)


#Порт сервера храним в .env, чтобы автозапуск хоста поднимал сервер на ТОМ ЖЕ порту,
#который админ выбрал в панели (а не на дефолтном 8000, если он его менял).
def get_server_port() -> int:
    try:
        return int(read_env().get("GRADEBOOK_SERVER_PORT", str(DEFAULT_PORT)) or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def set_server_port(port: int) -> bool:
    env = read_env()
    env["GRADEBOOK_SERVER_PORT"] = str(int(port or DEFAULT_PORT))
    return _write_env(env)


def tunnel_running() -> bool:
    """True, если ssh-туннель ещё жив."""
    return _tunnel_proc is not None and _tunnel_proc.poll() is None


def tunnel_url() -> str:
    """Текущий публичный адрес туннеля ('' — туннель не поднят)."""
    return _tunnel_url if tunnel_running() else ""


def _read_tunnel_output(proc, evt):
    """В фоне дочитывает вывод ssh: ловит строку с публичным адресом и держит
    трубу пустой (иначе ssh подвис бы на заполненном буфере). Нить-демон —
    завершится сама, когда ssh закроется."""
    global _tunnel_url
    pat = re.compile(r"Forwarding\s+HTTP\s+traffic\s+from\s+(https?://\S+)")
    try:
        for line in proc.stdout:
            m = pat.search(line)
            if m:
                _tunnel_url = m.group(1).rstrip("/")
                evt.set()
    except Exception:
        pass
    finally:
        evt.set()   #процесс закрылся — разбудим ожидающего, даже если адреса нет


def start_tunnel(port: int = DEFAULT_PORT, name: str = "") -> tuple:
    """Поднимает ssh-туннель к serveo.net и возвращает публичный адрес.
    (True, 'https://…') либо (False, причина).

    Важно: форвардим на 127.0.0.1 (IPv4), а НЕ на localhost. На чистом IPv4
    (типично для РФ) localhost резолвится сначала в IPv6 ::1, куда сервер не
    слушает — и туннель отдавал бы 502. Явный 127.0.0.1 это снимает."""
    global _tunnel_proc, _tunnel_url
    if tunnel_running():
        return True, (_tunnel_url or "Туннель уже запущен.")

    name = (name or "").strip()
    #С именем — постоянный адрес name.serveo.net; без имени — случайный каждый раз.
    remote = f"{name}:80:127.0.0.1:{port}" if name else f"80:127.0.0.1:{port}"
    cmd = [
        #-4 — ВЕСЬ туннель строго по IPv4. В РФ IPv6 часто битый/выключен: без
        #этого ssh может выбрать AAAA-адрес serveo.net и зависнуть на подключении,
        #а форвард на 127.0.0.1 (а не localhost) гарантирует IPv4 и на нашем конце.
        "ssh", "-4", "-R", remote, "serveo.net",
        #accept-new — не зависаем на вопросе про host-key при первом подключении;
        #ServerAlive — держим соединение; ExitOnForwardFailure — падаем сразу,
        #если порт занять не удалось (а не висим молча).
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=60",
        "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes",
    ]
    #На Windows прячем чёрное окно консоли ssh (иначе оно всплывает поверх UI).
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        _tunnel_url = ""
        _tunnel_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, creationflags=flags)
    except FileNotFoundError:
        return False, ("Не найден ssh. Он встроен в Windows 10/11 — включите "
                       "компонент «Клиент OpenSSH» (Параметры → Приложения → "
                       "Дополнительные компоненты).")
    except Exception as e:
        return False, f"Не удалось запустить туннель: {e}"

    evt = threading.Event()
    threading.Thread(target=_read_tunnel_output, args=(_tunnel_proc, evt),
                     daemon=True).start()
    #Ждём, пока serveo выдаст адрес (обычно 2–5 c). Если ssh сразу умер или адрес
    #не пришёл — честно сообщаем, а не оставляем «висящий» туннель.
    if evt.wait(timeout=20) and _tunnel_url:
        return True, _tunnel_url
    if _tunnel_proc.poll() is not None:
        return False, ("ssh-туннель сразу завершился. Проверьте интернет и что "
                       "serveo.net доступен (он бывает перегружен — попробуйте "
                       "ещё раз через минуту).")
    return False, "Туннель не выдал адрес за 20 секунд — попробуйте ещё раз."


def stop_tunnel() -> tuple:
    """Останавливает ssh-туннель."""
    global _tunnel_proc, _tunnel_url
    proc = _tunnel_proc
    _tunnel_proc = None
    _tunnel_url = ""
    if proc is None or proc.poll() is not None:
        return True, "Туннель остановлен."
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    except Exception as e:
        return False, f"Не удалось остановить туннель: {e}"
    return True, "Туннель остановлен."


#Единый запуск из админки (одна кнопка «Запустить сервер»)
def launch(access: str, engine: str, port: int = DEFAULT_PORT,
           name: str = "", pg: dict = None) -> tuple:
    """Поднимает сервер «под ключ» по выбранному типу и возвращает адрес, который
    надо сохранить в программе как адрес сервера синхронизации.

    Шаги: записать движок БД в .env → запустить сервер (in-process FastAPI — это и
    есть «сам API») → для serveo поднять ssh-туннель и взять публичный адрес; для
    прямого доступа вернуть локальный адрес этого ПК.

    access: 'serveo' (доступ из интернета) | 'direct' (ЛВС/домен).
    engine: 'sqlite' | 'postgres'.
    Возвращает (ok: bool, url: str, message: str). url — что сохранить как адрес
    сервера ('' при ошибке)."""
    access = "serveo" if (access or "").lower() == "serveo" else "direct"
    engine = "postgres" if (engine or "").lower() == "postgres" else "sqlite"

    #1. Движок серверной БД в .env (его прочитает start_server до импорта сервера).
    if engine == "postgres":
        pg = pg or {}
        ok = use_postgres(pg.get("host"), pg.get("port"), pg.get("db"),
                          pg.get("user"), pg.get("password"))
    else:
        ok = use_sqlite()
    if not ok:
        return False, "", "Не удалось сохранить настройки БД сервера в .env."

    #Запомним выбранный режим доступа, чтобы восстановить его в UI при след. запуске.
    set_access_mode(access)

    #2. Сам сервер (API). При уже запущенном — start_server вернёт «уже запущен».
    ok, msg = start_server(port)
    if not ok:
        return False, "", msg

    #3. Доступ к серверу.
    if access == "serveo":
        ok, res = start_tunnel(port, name)
        if not ok:
            #Сервер подняли, а туннель — нет: говорим честно, адрес не сохраняем.
            return False, "", f"Сервер запущен, но доступ из интернета не открылся: {res}"
        return True, res, f"Сервер запущен, доступ из интернета открыт:\n{res}"

    #Прямой доступ: на ЭТОМ ПК клиент ходит на 127.0.0.1, остальным даём адрес в ЛВС.
    ip = lan_ip() or "127.0.0.1"
    url = f"http://127.0.0.1:{port}"
    hint = (f"Сервер запущен на порту {port}.\n"
            f"Адрес для других ПК в сети: http://{ip}:{port}")
    return True, url, hint


def autostart(port: int = None) -> tuple:
    """Поднимает сервер ПК-хоста по УЖЕ сохранённой в .env конфигурации — без
    перезаписи .env и без участия администратора. Зовётся при старте программы, если
    включён автозапуск (app_settings.host_autostart_enabled). Так связь становится
    постоянной: сервер встаёт сам при каждом запуске, админ может выйти из аккаунта.

    Для режима serveo заодно поднимаем туннель (чтобы другие ПК видели сервер), но
    СВОИМ адресом хост всегда ходит на 127.0.0.1: сервер локальный, гонять собственный
    трафик наружу через serveo незачем (и надёжнее — localhost не отвалится).

    Возвращает (ok: bool, local_url: str, message: str)."""
    if port is None:
        port = get_server_port()

    #Сам сервер (API). Движок БД уже записан в .env прошлым запуском из админки —
    #его прочитает start_server до импорта сервера, переписывать .env не нужно.
    ok, msg = start_server(port)
    if not ok:
        return False, "", msg

    #Для serveo поднимаем туннель в фоне — для ДРУГИХ ПК. Свой адрес — всё равно
    #localhost, поэтому даже если туннель не встанет, хост продолжит работать.
    if get_access_mode() == "serveo":
        try:
            start_tunnel(port, get_tunnel_name())
        except Exception as e:
            print(f"[server_control] автозапуск туннеля пропущен: {e}")

    return True, f"http://127.0.0.1:{port}", f"Сервер хоста запущен на порту {port}."
