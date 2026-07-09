"""
db.py — Подключение к базе (SQLAlchemy).

Один и тот же код работает и с SQLite (разработка), и с PostgreSQL (боевой
сервер ВСГУТУ) — отличается только строка подключения GRADEBOOK_DB_URL.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL, DB_KEY

_IS_SQLITE = DATABASE_URL.startswith("sqlite")
#Для SQLite нужен check_same_thread=False (FastAPI работает в нескольких потоках).
_connect_args = {"check_same_thread": False} if _IS_SQLITE else {}


def _build_engine():
    """Движок БД. Если задан GRADEBOOK_DB_KEY и доступен драйвер sqlcipher3 — поднимаем
    движок поверх SQLCipher: файл БД шифруется ЦЕЛИКОМ (AES-256), ПДн at rest (152-ФЗ).
    Ключ (64 hex, raw 256-bit) задаётся PRAGMA key ПЕРВОЙ операцией КАЖДОГО соединения.
    Нет ключа/драйвера (напр. Windows-dev, CI без ключа) → обычный SQLite: схема id и
    тесты не меняются. Ключ БД нигде не логируем."""
    if _IS_SQLITE and DB_KEY:
        try:
            import sqlcipher3
        except ImportError:
            print("[db] GRADEBOOK_DB_KEY задан, но драйвер sqlcipher3 не установлен "
                  "(на Windows-dev это нормально) — БД работает БЕЗ шифрования файла.")
        else:
            path = DATABASE_URL.split("sqlite:///", 1)[-1]

            def _creator():
                conn = sqlcipher3.connect(path, check_same_thread=False)
                conn.execute("PRAGMA key = \"x'%s'\"" % DB_KEY)   # ДО любых других операций
                return conn

            print("[db] Файл БД шифруется (SQLCipher, AES-256).")
            return create_engine("sqlite://", creator=_creator, pool_pre_ping=True)
    return create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)


engine = _build_engine()


if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):
        """Настраиваем КАЖДОЕ SQLite-соединение под конкурентную нагрузку.

        Зачем: под утренним «гердом» входов колледжа несколько запросов пишут в БД
        одновременно (вход теперь ещё и создаёт строки сессии — auth_sessions). Без
        этих PRAGMA SQLite сериализует запись и при конфликте СРАЗУ падает «database is
        locked». С WAL читатели не блокируют писателя, а busy_timeout заставляет
        писателей ЖДАТЬ освобождения блокировки, а не падать. (Как в десктопном core.py.)
        Для настоящего масштаба всё равно PostgreSQL — но SQLite так держится дольше."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")     #параллельные читатели + один писатель
        cur.execute("PRAGMA busy_timeout=5000")    #ждать блокировку до 5 c, а не падать
        cur.execute("PRAGMA synchronous=NORMAL")   #безопасно и быстрее при WAL
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """Зависимость FastAPI: открыть сессию на запрос и гарантированно закрыть."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Создаёт таблицы, если их нет. Вызывается при старте приложения."""
    from . import models  #noqa: F401 — регистрируем модели в метаданных
    Base.metadata.create_all(bind=engine)
    _ensure_user_prefs_column()


def _ensure_user_prefs_column():
    """Идемпотентная мини-миграция: добавляет столбец users.prefs на УЖЕ
    существующей базе. create_all создаёт только отсутствующие ТАБЛИЦЫ, новые
    столбцы он не досоздаёт — поэтому на старой базе колледжа prefs надо добавить
    ALTER-ом. На свежей БД столбец уже создан через create_all, и мы просто выходим."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    try:
        columns = {c["name"] for c in insp.get_columns("users")}
    except Exception:
        return  #таблицы ещё нет — её только что создал create_all со столбцом
    if "prefs" in columns:
        return
    #Тип столбца для JSON: в SQLite это TEXT, в PostgreSQL — JSON/JSONB. Берём
    #нейтральный JSON — SQLAlchemy/драйвер отобразит его в подходящий тип СУБД.
    is_pg = engine.url.get_backend_name().startswith("postgres")
    coltype = "JSONB" if is_pg else "JSON"
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE users ADD COLUMN prefs {coltype}"))
