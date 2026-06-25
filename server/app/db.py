"""
db.py — Подключение к базе (SQLAlchemy).

Один и тот же код работает и с SQLite (разработка), и с PostgreSQL (боевой
сервер ВСГУТУ) — отличается только строка подключения GRADEBOOK_DB_URL.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL

#Для SQLite нужен check_same_thread=False (FastAPI работает в нескольких потоках).
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
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
