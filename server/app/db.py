"""
db.py — Подключение к базе (SQLAlchemy).

Один и тот же код работает и с SQLite (разработка), и с PostgreSQL (боевой
сервер ВСГУТУ) — отличается только строка подключения GRADEBOOK_DB_URL.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")

#Для SQLite нужен check_same_thread=False (FastAPI работает в нескольких потоках).
#timeout — сколько секунд писатель ждёт освобождения БД, прежде чем отдать ошибку
#«database is locked»: под нагрузкой запись в SQLite сериализуется, и без ожидания
#параллельные пуши падали бы. С ожиданием они становятся в очередь.
_connect_args = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}

#Пул соединений. По умолчанию SQLAlchemy даёт всего 5 (+10 overflow) — этого мало:
#каждый запрос держит соединение на всё своё время (включая ~55 мс PBKDF2 при
#входе), и при одновременной работе колледжа пул мгновенно исчерпывался
#(«QueuePool limit reached», вход «висел» до pool_timeout). Поднимаем до 200
#одновременных соединений — это покрывает реалистичный бурст. Для PostgreSQL это
#обычные соединения (на боевом сервере согласуй с max_connections БД); для SQLite —
#дешёвые файловые дескрипторы. ⚠️ Тысячи ОДНОВРЕМЕННЫХ входов в одну секунду (вся
#школа разом) упрутся в число ядер (PBKDF2 — CPU) и в один процесс: для такого
#масштаба разворачивай несколько воркеров uvicorn и PostgreSQL (см. DEPLOY.md).
engine = create_engine(
    DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True,
    pool_size=50, max_overflow=150, pool_timeout=30,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


if _is_sqlite:
    #ВАЖНО: journal_mode=WAL ставим ОДИН раз при инициализации, а не на каждом
    #подключении. Смена journal_mode требует эксклюзивной блокировки БД; если делать
    #её на КАЖДОМ из десятков соединений под нагрузкой, они встают в очередь за
    #блокировкой до busy_timeout — вход «висит» секундами на ровном месте. WAL
    #сохраняется в заголовке файла БД, поэтому достаточно включить его единожды.
    #На каждом соединении задаём только ДЕШЁВЫЕ per-connection прагмы (без блокировок):
    #synchronous и busy_timeout (сколько ждать освобождения БД вместо «database is locked»).
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
        finally:
            cur.close()


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
    if _is_sqlite:
        #WAL включаем единожды при старте (он сохраняется в файле БД и наследуется
        #всеми последующими соединениями). Это даёт конкурентное чтение во время
        #записи — несколько pull не блокируются одним push.
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
