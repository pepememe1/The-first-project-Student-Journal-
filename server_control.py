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
import sys
import socket
import threading

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
