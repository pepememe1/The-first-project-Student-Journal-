"""
test_db_pool.py — пул соединений БД: защита от «Cannot operate on a closed database».
"""


def test_sqlcipher_engine_uses_queuepool_not_singletonthread(monkeypatch):
    """SQLCipher-движок ОБЯЗАН использовать QueuePool.

    Регрессия с боя: движок создавался как create_engine("sqlite://", creator=...) —
    файл открывался через creator, но SQLAlchemy по такому URL считал базу in-memory и
    брал SingletonThreadPool (пул для тестов с памятью). Тот закрывает соединения сверх
    своего размера, а FastAPI обслуживает синхронные эндпоинты из пула потоков → пул
    закрывал соединение под живой сессией, и откат падал с
    sqlcipher3.dbapi2.ProgrammingError: Cannot operate on a closed database.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import QueuePool, SingletonThreadPool

    #Так БЫЛО (без poolclass): SQLAlchemy сам выберет SingletonThreadPool — это и есть баг.
    bad = create_engine("sqlite://", pool_pre_ping=True)
    assert isinstance(bad.pool, SingletonThreadPool), \
        "если это упало — SQLAlchemy сменил дефолт, комментарий в db.py надо обновить"

    #Так СТАЛО: пул задан явно.
    good = create_engine("sqlite://", pool_pre_ping=True, poolclass=QueuePool)
    assert isinstance(good.pool, QueuePool)


def test_app_engine_pool_is_safe():
    """У боевого движка приложения пул не должен быть SingletonThreadPool ни при каких
    настройках — ни обычный SQLite-файл, ни SQLCipher."""
    from sqlalchemy.pool import SingletonThreadPool
    from app.db import engine
    assert not isinstance(engine.pool, SingletonThreadPool), \
        f"опасный пул для многопоточного сервера: {type(engine.pool).__name__}"
