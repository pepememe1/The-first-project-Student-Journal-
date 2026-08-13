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
import log
import re
import sys
import time
import socket
import signal
import secrets
import subprocess

#Папка сервера лежит рядом с клиентскими модулями (репозиторий) — и в dev, и при
#запуске из исходников. Берём абсолютный путь относительно этого файла.
_HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(_HERE, "server")
ENV_PATH = os.path.join(SERVER_DIR, ".env")

DEFAULT_PORT = 8000
SQLITE_URL = "sqlite:///./gradebook_server.db"

#ФОНОВЫЙ сервер. Раньше сервер крутился ВНУТРИ программы (uvicorn в потоке-демоне) и
#умирал вместе с ней. Теперь сервер и ssh-туннель — ОТДЕЛЬНЫЕ процессы (detached),
#которые продолжают работать, когда программа закрыта и при смене аккаунта на хосте.
#Их PID пишем в файлы, чтобы при следующем запуске программы ПОДХВАТИТЬ уже работающие
#(а не плодить второй сервер). Лог пишем в файл (а не в PIPE) — труба умерла бы вместе
#с GUI, а файл переживает и помогает диагностике. Останавливаются процессы только явной
#кнопкой «Остановить» (или taskkill) — закрытие программы их больше НЕ гасит.
SERVER_PID = os.path.join(SERVER_DIR, "server.pid")
SERVER_LOG = os.path.join(SERVER_DIR, "server.log")
TUNNEL_PID = os.path.join(SERVER_DIR, "tunnel.pid")
TUNNEL_LOG = os.path.join(SERVER_DIR, "tunnel.log")
#Caddy — HTTPS-прокси под СВОИМ доменом (авто-сертификат Let's Encrypt). Отдельный
#фоновый процесс, как ssh-туннель: свой PID, лог и Caddyfile. TLS терминируется на
#этом ПК своим доменом — данные не идут через чужого посредника (важно для 152-ФЗ).
CADDY_PID = os.path.join(SERVER_DIR, "caddy.pid")
CADDY_LOG = os.path.join(SERVER_DIR, "caddy.log")
CADDYFILE = os.path.join(SERVER_DIR, "Caddyfile")


#PID-файлы и проверка/остановка процессов (кросс-платформенно, без psutil)
def _detached_flags() -> int:
    """Флаги Popen, чтобы дочерний процесс пережил закрытие программы и не показывал
    окно консоли. На не-Windows — 0 (там процесс и так не убивается с родителем, если
    не в той же сессии; daemon-поведение задаём start_new_session)."""
    if os.name == "nt":
        return (getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _write_pid(path: str, pid: int):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(int(pid)))
    except Exception as e:
        log.get("server_control").warning(f"[server_control] PID не записан ({path}): {e}")


def _read_pid(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return int((f.read() or "0").strip() or 0)
    except Exception:
        return 0


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс с таким PID."""
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k = ctypes.windll.kernel32
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    else:
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False


def _pid_kill(pid: int):
    """Останавливает процесс (с дочерними) по PID."""
    if not pid:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log.get("server_control").warning(f"[server_control] taskkill {pid}: {e}")
    else:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass


def _pids_on_port(port: int) -> list:
    """PID(ы) процессов, СЛУШАЮЩИХ указанный TCP-порт.

    Запасной путь остановки: сервер — фоновый detached-процесс и переживает закрытие
    программы. К моменту «Остановить» сохранённый PID мог потеряться (например, сервер
    подхватили из прошлого сеанса и PID-файла не было) — тогда сохранённый kill ничего
    не гасит, а /health продолжает отвечать. Здесь находим слушателя порта напрямую и
    возвращаем его PID, чтобы гарантированно остановить сервер.

    Состояния в netstat (LISTENING/ESTABLISHED) не локализуются — на любой раскладке
    Windows они английские, поэтому фильтр по 'LISTENING' надёжен."""
    pids = set()
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout or ""
            needle = f":{port}"
            for line in out.splitlines():
                parts = line.split()
                #Колонки: Proto  Local  Foreign  State  PID
                if (len(parts) >= 5 and parts[0].upper() == "TCP"
                        and parts[3].upper() == "LISTENING"
                        and parts[1].endswith(needle)):
                    try:
                        pids.add(int(parts[4]))
                    except ValueError:
                        pass
        else:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, errors="replace").stdout or ""
            for tok in out.split():
                try:
                    pids.add(int(tok))
                except ValueError:
                    pass
    except Exception as e:
        log.get("server_control").warning(f"[server_control] не удалось найти PID на порту {port}: {e}")
    return list(pids)


#Чтение/запись server/.env (простой формат KEY=VALUE)
def read_env() -> dict:
    """Возвращает текущие переменные из server/.env (пусто, если файла нет)."""
    out = {}
    try:
        if os.path.exists(ENV_PATH):
            with open(ENV_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    except Exception as e:
        log.get("server_control").warning(f"[server_control] не удалось прочитать .env: {e}")
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
        log.get("server_control").warning(f"[server_control] не удалось записать .env: {e}")
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


def _runtime_env(port: int) -> dict:
    """Окружение для ОТДЕЛЬНОГО процесса сервера: к текущему env добавляем настройки из
    .env, абсолютный путь к SQLite и device_id хоста (чтобы сервер пропускал хост через
    барьер подтверждения — connect.py). Отдельный процесс не наследует наши os.environ
    автоматически в нужном виде, поэтому собираем явно и передаём в Popen(env=...)."""
    env = dict(os.environ)
    env.update(read_env())
    env["GRADEBOOK_DB_URL"] = _db_url_for_runtime()
    env["GRADEBOOK_PORT"] = str(port)          #run.py читает GRADEBOOK_PORT
    try:
        from data import app_settings
        host_dev = app_settings.get_device_id()
        if host_dev:
            env["GRADEBOOK_HOST_DEVICE_ID"] = host_dev
    except Exception as e:
        log.get("server_control").warning(f"[server_control] device_id хоста не выставлен: {e}")
    return env


def _server_command() -> list:
    """Команда запуска сервера отдельным процессом.
      • dev (из исходников): python server/run.py — run.py поднимает uvicorn;
      • frozen (.exe): тот же exe со спец-флагом --run-server (внешнего python нет,
        поэтому сервер = наш же exe, который по флагу поднимает uvicorn вместо GUI)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-server"]
    return [sys.executable, os.path.join(SERVER_DIR, "run.py")]


def start_server_process(port: int = DEFAULT_PORT) -> tuple:
    """Поднимает сервер ОТДЕЛЬНЫМ процессом (переживает закрытие программы).
    Если сервер уже отвечает — подхватываем (не плодим второй). (ok, сообщение)."""
    if server_running(port):
        #Подхватили живой фоновый сервер (пережил прошлый сеанс). ВАЖНО записать его
        #PID, иначе «Остановить» потом не нашёл бы кого гасить — раньше PID-файла при
        #подхвате не было, и сервер казался «неубиваемым».
        if not _pid_alive(_read_pid(SERVER_PID)):
            for p in _pids_on_port(port):
                _write_pid(SERVER_PID, p)
                break
        return True, "Сервер уже запущен (подхвачен)."
    #Уже стартует из прошлого вызова — подождём немного его /health ниже.
    if not os.path.isdir(SERVER_DIR):
        return False, f"Папка сервера не найдена: {SERVER_DIR}"
    if _port_busy(port):
        return False, f"Порт {port} занят другим процессом."

    #Гарантируем .env с движком БД и секретом JWT (их прочитает дочерний процесс).
    env_vals = read_env()
    if "GRADEBOOK_DB_URL" not in env_vals:
        env_vals["GRADEBOOK_DB_URL"] = SQLITE_URL
    _write_env(_ensure_jwt_secret(env_vals))

    try:
        logf = open(SERVER_LOG, "a", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            _server_command(), cwd=SERVER_DIR, env=_runtime_env(port),
            stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
            close_fds=True, creationflags=_detached_flags(),
            start_new_session=(os.name != "nt"))
    except Exception as e:
        return False, (f"Не удалось запустить процесс сервера: {e}\n"
                       "Проверьте зависимости: pip install -r server/requirements.txt")
    _write_pid(SERVER_PID, proc.pid)

    for _ in range(30):                          #до ~15 секунд на старт
        if server_running(port):
            return True, f"Сервер запущен (фоновый процесс) на порту {port}."
        if proc.poll() is not None:
            return False, ("Сервер не стартовал. Подробности — в server/server.log "
                           "(проверьте БД и зависимости сервера).")
        time.sleep(0.5)
    return False, "Сервер запускается дольше обычного — проверьте состояние позже."


def stop_server(port: int = DEFAULT_PORT) -> tuple:
    """Останавливает ФОНОВЫЙ процесс сервера по сохранённому PID."""
    pid = _read_pid(SERVER_PID)
    if pid:
        _pid_kill(pid)
    try:
        os.remove(SERVER_PID)
    except OSError:
        pass
    #Запасной путь: если сохранённый PID потерян/устарел (сервер подхватили из прошлого
    #сеанса), но порт ещё кто-то слушает — находим слушателя напрямую и гасим его.
    #Именно из-за этого раньше выскакивало «Сервер ещё отвечает».
    if server_running(port):
        for p in _pids_on_port(port):
            _pid_kill(p)
    #Дать порту освободиться и проверить, что /health больше не отвечает.
    for _ in range(6):
        if not server_running(port):
            return True, "Сервер остановлен."
        time.sleep(0.5)
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


def ensure_tunnel_name() -> str:
    """Гарантирует ПОСТОЯННОЕ имя поддомена serveo и возвращает его.

    Раньше без имени serveo выдавал случайный адрес при каждом запуске — и клиентам
    приходилось «делать ссылку заново». Теперь, если имя не задано, генерим стабильное
    `gradebook-<8 hex>` и сохраняем в .env. С этого момента публичный адрес постоянный:
    `https://<name>.serveo.net` (serveo закрепляет поддомен за ssh-ключом этого ПК)."""
    name = get_tunnel_name()
    if not name:
        name = f"gradebook-{secrets.token_hex(4)}"
        set_tunnel_name(name)
    return name


def public_tunnel_url(name: str = "") -> str:
    """Детерминированный публичный адрес туннеля по имени поддомена. Имя постоянно,
    поэтому адрес можно вычислить, не разбирая вывод ssh (а значит — и для фонового
    процесса, чей stdout мы не держим)."""
    name = (name or get_tunnel_name()).strip()
    return f"https://{name}.serveo.net" if name else ""


#Свой домен + HTTPS через Caddy — боевая альтернатива serveo. TLS терминируется на
#ЭТОМ ПК под своим доменом (напр. esstu.gradebook.ru), без иностранного посредника —
#это и нужно для 152-ФЗ. Домен храним в .env, чтобы адрес был постоянным.
def get_domain() -> str:
    return read_env().get("GRADEBOOK_DOMAIN", "").strip()


def _norm_domain(domain: str) -> str:
    """Чистое имя хоста из того, что ввёл админ: без схемы, слэшей и пробелов."""
    d = (domain or "").strip().lower()
    for pref in ("https://", "http://"):
        if d.startswith(pref):
            d = d[len(pref):]
    return d.strip("/ ").split("/")[0]


def set_domain(domain: str) -> bool:
    env = read_env()
    env["GRADEBOOK_DOMAIN"] = _norm_domain(domain)
    return _write_env(env)


def public_domain_url(domain: str = "") -> str:
    domain = _norm_domain(domain or get_domain())
    return f"https://{domain}" if domain else ""


def _find_caddy() -> str:
    """Путь к Caddy: рядом с программой, в SERVER_DIR или в PATH ('' — не найден)."""
    import shutil
    names = ["caddy.exe", "caddy"] if os.name == "nt" else ["caddy"]
    for base in (_HERE, SERVER_DIR):
        for n in names:
            p = os.path.join(base, n)
            if os.path.isfile(p):
                return p
    return shutil.which("caddy") or ""


def caddy_alive() -> bool:
    """True, если фоновый Caddy ещё жив (по сохранённому PID)."""
    return _pid_alive(_read_pid(CADDY_PID))


def _write_caddyfile(domain: str, port: int) -> None:
    """Минимальный Caddyfile: домен → reverse_proxy на локальный uvicorn. Caddy сам
    получит и продлит сертификат Let's Encrypt. X-Forwarded-For доходит до сервера
    (нужен серверному анти-брутфорсу)."""
    with open(CADDYFILE, "w", encoding="utf-8") as f:
        f.write(f"{domain} {{\n\treverse_proxy 127.0.0.1:{port}\n}}\n")


def start_caddy_process(domain: str, port: int = DEFAULT_PORT) -> tuple:
    """Поднимает Caddy ОТДЕЛЬНЫМ процессом (переживает закрытие программы): HTTPS на
    своём домене → 127.0.0.1:port (там и API, и сайт). Возвращает (ok, 'https://domain'
    | причина).

    Что нужно один раз (инфраструктура, прога её не создаёт): домен куплен; A-запись
    домена → публичный IP этого ПК; порты 80 и 443 открыты/проброшены; установлен Caddy
    (один .exe с caddyserver.com рядом с программой или в PATH)."""
    domain = _norm_domain(domain or get_domain())
    if not domain:
        return False, "Не задан домен (например, esstu.gradebook.ru)."
    if caddy_alive():
        return True, public_domain_url(domain)
    caddy = _find_caddy()
    if not caddy:
        return False, ("Не найден Caddy. Скачайте один файл caddy.exe с caddyserver.com "
                       "и положите рядом с программой (или добавьте в PATH).")
    _write_caddyfile(domain, port)
    try:
        logf = open(CADDY_LOG, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            [caddy, "run", "--config", CADDYFILE, "--adapter", "caddyfile"],
            stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
            close_fds=True, creationflags=_detached_flags(),
            start_new_session=(os.name != "nt"), cwd=SERVER_DIR)
    except Exception as e:
        return False, f"Не удалось запустить Caddy: {e}"
    _write_pid(CADDY_PID, proc.pid)
    #Даём Caddy подняться (получение сертификата — секунды). Сразу упал — честно скажем.
    time.sleep(2.5)
    if proc.poll() is not None:
        return False, ("Caddy сразу завершился (см. server/caddy.log). Проверьте A-запись "
                       "домена на этот ПК и открытость портов 80/443.")
    return True, public_domain_url(domain)


def stop_caddy() -> tuple:
    """Останавливает фоновый Caddy по сохранённому PID."""
    pid = _read_pid(CADDY_PID)
    if pid:
        _pid_kill(pid)
    try:
        os.remove(CADDY_PID)
    except OSError:
        pass
    return True, "Caddy остановлен."


#Режим доступа к серверу — чтобы при следующем открытии админки восстановить выбор
#типа сервера. 'serveo' — доступ из интернета через туннель; 'direct' — сервер
#виден напрямую (локальная сеть / свой домен). Это настройка ПК-хоста, живёт в .env
#рядом с прочей серверной конфигурацией.
def get_access_mode() -> str:
    """'serveo' | 'domain' | 'direct' (по умолчанию — 'direct', ВСГУТУ-сервер в ЛВС)."""
    mode = read_env().get("GRADEBOOK_ACCESS_MODE", "").strip().lower()
    return mode if mode in ("serveo", "domain") else "direct"


def set_access_mode(mode: str) -> bool:
    env = read_env()
    m = (mode or "").strip().lower()
    env["GRADEBOOK_ACCESS_MODE"] = m if m in ("serveo", "domain") else "direct"
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


def tunnel_alive() -> bool:
    """True, если ФОНОВЫЙ ssh-туннель ещё жив (по сохранённому PID)."""
    return _pid_alive(_read_pid(TUNNEL_PID))


def _confirm_tunnel(timeout: float = 12.0) -> str:
    """Ждёт строку с публичным адресом в tunnel.log (подтверждение, что serveo принял
    форвард). Возвращает найденный URL или '' (адрес всё равно знаем из имени)."""
    pat = re.compile(r"Forwarding\s+HTTP\s+traffic\s+from\s+(https?://\S+)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(TUNNEL_LOG, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = pat.search(line)
                    if m:
                        return m.group(1).rstrip("/")
        except Exception:
            pass
        time.sleep(0.5)
    return ""


def start_tunnel_process(port: int = DEFAULT_PORT, name: str = "") -> tuple:
    """Поднимает ssh-туннель ОТДЕЛЬНЫМ процессом (переживает закрытие программы) с
    ПОСТОЯННЫМ именем поддомена. Возвращает (ok, 'https://…' | причина).

    Если туннель уже жив — подхватываем. Вывод ssh пишем в tunnel.log (не PIPE: трубу
    мы держать не можем, она умерла бы с GUI, а файл переживает и помогает диагностике).
    Форвардим на 127.0.0.1 (IPv4): на чистом IPv4 (типично для РФ) localhost ушёл бы в
    IPv6 ::1, куда сервер не слушает, и serveo отдавал бы 502."""
    if tunnel_alive():
        return True, (public_tunnel_url() or "Туннель уже запущен.")
    name = (name or get_tunnel_name()).strip() or ensure_tunnel_name()
    remote = f"{name}:80:127.0.0.1:{port}"
    cmd = [
        "ssh", "-4", "-R", remote, "serveo.net",
        #accept-new — не зависаем на host-key; ServerAlive — держим соединение;
        #ExitOnForwardFailure — падаем сразу, если поддомен занять не удалось.
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=60",
        "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes",
    ]
    try:
        logf = open(TUNNEL_LOG, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
            close_fds=True, creationflags=_detached_flags(),
            start_new_session=(os.name != "nt"))
    except FileNotFoundError:
        return False, ("Не найден ssh. Он встроен в Windows 10/11 — включите "
                       "компонент «Клиент OpenSSH» (Параметры → Приложения → "
                       "Дополнительные компоненты).")
    except Exception as e:
        return False, f"Не удалось запустить туннель: {e}"
    _write_pid(TUNNEL_PID, proc.pid)

    #Подтверждаем установление (serveo выдаёт строку в лог за 2–5 c). Если ssh сразу
    #умер — честно сообщаем; иначе адрес известен из постоянного имени.
    confirmed = _confirm_tunnel()
    if proc.poll() is not None:
        return False, ("ssh-туннель сразу завершился (см. server/tunnel.log). Проверьте "
                       "интернет и доступность serveo.net — он бывает перегружен.")
    return True, (confirmed or public_tunnel_url(name))


def stop_tunnel() -> tuple:
    """Останавливает фоновый ssh-туннель по сохранённому PID."""
    pid = _read_pid(TUNNEL_PID)
    if pid:
        _pid_kill(pid)
    try:
        os.remove(TUNNEL_PID)
    except OSError:
        pass
    return True, "Туннель остановлен."


def stop_processes(port: int = DEFAULT_PORT) -> tuple:
    """Останавливает фоновые процессы хоста: сервер и туннель. Зовётся кнопкой
    «Остановить» в админке (закрытие программы их НЕ гасит — это и есть цель)."""
    stop_tunnel()
    stop_caddy()
    return stop_server(port)


#Единый запуск из админки (одна кнопка «Запустить сервер»)
def launch(access: str, engine: str, port: int = DEFAULT_PORT,
           name: str = "", pg: dict = None, domain: str = "") -> tuple:
    """Поднимает сервер «под ключ» по выбранному типу и возвращает адрес, который
    надо сохранить в программе как адрес сервера синхронизации.

    Шаги: записать движок БД в .env → запустить сервер (in-process FastAPI — это и
    есть «сам API») → для serveo поднять ssh-туннель и взять публичный адрес; для
    прямого доступа вернуть локальный адрес этого ПК.

    access: 'serveo' (доступ из интернета) | 'direct' (ЛВС/домен).
    engine: 'sqlite' | 'postgres'.
    Возвращает (ok: bool, url: str, message: str). url — что сохранить как адрес
    сервера ('' при ошибке)."""
    a = (access or "").lower()
    access = a if a in ("serveo", "domain") else "direct"
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

    #Запомним выбранный режим доступа и порт, чтобы восстановить их при автозапуске.
    set_access_mode(access)
    set_server_port(port)

    #2. Сам сервер (API) — ОТДЕЛЬНЫМ процессом. При уже запущенном — подхват.
    ok, msg = start_server_process(port)
    if not ok:
        return False, "", msg

    #3. Доступ к серверу. Свой адрес у хоста — всегда 127.0.0.1 (сервер локальный);
    #публичный адрес для ДРУГИХ ПК отдаём в сообщении.
    local_url = f"http://127.0.0.1:{port}"

    #Свой домен + HTTPS (Caddy): адрес — красивый https://<домен>, он же и сервер, и сайт.
    if access == "domain":
        dom = _norm_domain(domain or get_domain())
        if not dom:
            return False, "", "Не задан домен для HTTPS (например, esstu.gradebook.ru)."
        set_domain(dom)
        ok, res = start_caddy_process(dom, port)
        if not ok:
            return False, "", f"Сервер запущен, но HTTPS-домен не поднялся: {res}"
        public = public_domain_url(dom)
        return True, public, (f"Сервер и сайт запущены под своим доменом (фоновые — "
                              f"работают и без программы).\nАдрес (сервер + сайт):\n{public}")

    if access == "serveo":
        ensure_tunnel_name()                      #гарантируем ПОСТОЯННОЕ имя
        ok, res = start_tunnel_process(port, name or get_tunnel_name())
        if not ok:
            return False, "", f"Сервер запущен, но доступ из интернета не открылся: {res}"
        #В serveo-режиме адресом сервера сохраняем именно ПУБЛИЧНУЮ ссылку serveo (а не
        #127.0.0.1): её же видят клиенты, она по https (проходит проверку защищённости
        #канала), и поле «Адрес сервера» теперь показывает реальный адрес, а не локалхост.
        #Туннель форвардит публичный адрес на локальный порт, так что хост ходит к себе же.
        public = (res or public_tunnel_url(name)).strip() or local_url
        return True, public, (f"Сервер запущен (фоновый — работает и без программы).\n"
                              f"Постоянная ссылка (этот же адрес у клиентов):\n{public}")

    #Прямой доступ: на ЭТОМ ПК клиент ходит на 127.0.0.1, остальным даём адрес в ЛВС.
    ip = lan_ip() or "127.0.0.1"
    hint = (f"Сервер запущен (фоновый — работает и без программы) на порту {port}.\n"
            f"Адрес для других ПК в сети: http://{ip}:{port}")
    return True, local_url, hint


def autostart(port: int = None) -> tuple:
    """Поднимает фоновый сервер ПК-хоста по УЖЕ сохранённой в .env конфигурации — без
    участия администратора. Зовётся при старте программы, если включён автозапуск
    (app_settings.host_autostart_enabled). Если сервер/туннель уже работают (фоновые
    процессы пережили прошлый сеанс) — ПОДХВАТЫВАЕМ их, не плодя второй.

    Свой адрес хоста — всегда http://127.0.0.1:port (сервер локальный).
    Возвращает (ok, local_url, message)."""
    if port is None:
        port = get_server_port()

    ok, msg = start_server_process(port)          #подхватит уже запущенный
    if not ok:
        return False, "", msg

    mode = get_access_mode()
    if mode == "serveo":
        try:
            start_tunnel_process(port, ensure_tunnel_name())   #подхватит живой туннель
        except Exception as e:
            log.get("server_control").warning(f"[server_control] автозапуск туннеля пропущен: {e}")
    elif mode == "domain":
        try:
            start_caddy_process(get_domain(), port)            #подхватит живой Caddy
        except Exception as e:
            log.get("server_control").warning(f"[server_control] автозапуск Caddy пропущен: {e}")

    return True, f"http://127.0.0.1:{port}", f"Сервер хоста запущен на порту {port}."
