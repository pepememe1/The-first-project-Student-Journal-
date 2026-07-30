"""
test_db_migrations.py — идемпотентные мини-миграции ALTER TABLE (server/app/db.py).

Обычный тестовый фикстура `client` пересоздаёт схему через Base.metadata.create_all,
которая для СВЕЖЕЙ таблицы включает ВСЕ текущие колонки сразу — поэтому ветка «колонки
не было, добавляем ALTER-ом» в обычных тестах никогда не срабатывает и ловит регрессии
только на боевой БД, где таблица появилась РАНЬШЕ новых колонок. Ровно так один раз уже
проехало в бою (§ролей, 3.1.5): create_all не досоздаёт колонки в СУЩЕСТВУЮЩЕЙ таблице,
conversation_participants на проде осталась без custom_role_id/silenced до первого
рестарта после деплоя миграции — conversation_info/send_message падали бы «no such
column» на любой группе/канале. Здесь эта ветка эмулируется явно.
"""
from sqlalchemy import text, inspect

from app.db import (engine, _ensure_participant_state_columns,
                    _ensure_subject_hours_teacher_column, _ensure_subject_hours_zet_column)


def test_ensure_participant_state_columns_adds_role_columns_to_old_schema(client):
    """Таблица без custom_role_id/silenced (схема ДО §ролей) — миграция должна дописать
    обе колонки ALTER-ом, а не молча оставить их отсутствующими."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE conversation_participants"))
        conn.execute(text("""CREATE TABLE conversation_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id VARCHAR, user_id VARCHAR,
            role VARCHAR, joined_at VARCHAR, last_read_at VARCHAR,
            muted BOOLEAN DEFAULT 0, pinned BOOLEAN DEFAULT 0, cleared_at VARCHAR DEFAULT '',
            hidden BOOLEAN DEFAULT 0, archived BOOLEAN DEFAULT 0,
            cleared_upto_id INTEGER DEFAULT 0
        )"""))
    #Сбросить пул: у SQLite соединение, открытое ДО этого DROP/CREATE (например, во время
    #старта приложения в фикстуре `client`), держит снимок схемы с прошлой транзакции —
    #без dispose() следующий PRAGMA table_info на ТОЙ ЖЕ пуловой коннекции видит СТАРУЮ
    #схему и ALTER падает «duplicate column». В бою это не воспроизводится: миграция
    #гоняется ОДИН раз на холодном движке сразу после create_all, старых соединений в
    #пуле ещё нет — здесь дублируем именно эту (тёплый пул) особенность теста, не бага.
    engine.dispose()
    _ensure_participant_state_columns()
    cols = {c["name"] for c in inspect(engine).get_columns("conversation_participants")}
    assert "custom_role_id" in cols and "silenced" in cols


def test_ensure_participant_state_columns_is_idempotent(client):
    """Повторный вызов на уже мигрированной таблице не падает (обычный старт сервера
    гоняет эти функции при КАЖДОМ запуске, не только один раз)."""
    _ensure_participant_state_columns()
    _ensure_participant_state_columns()
    cols = {c["name"] for c in inspect(engine).get_columns("conversation_participants")}
    assert "custom_role_id" in cols and "silenced" in cols


def test_ensure_subject_hours_teacher_column_adds_to_old_schema(client):
    """Таблица без teacher_id (схема ДО назначений препод↔предмет↔группа) — миграция
    должна дописать колонку ALTER-ом. Тот же прогретый-пул нюанс, что и выше — dispose()."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE subject_hours"))
        conn.execute(text("""CREATE TABLE subject_hours (
            id VARCHAR PRIMARY KEY, group_name VARCHAR, subject VARCHAR,
            year VARCHAR, semester INTEGER DEFAULT 0, hours_total INTEGER DEFAULT 0,
            updated_at VARCHAR DEFAULT '', deleted BOOLEAN DEFAULT 0
        )"""))
    engine.dispose()
    _ensure_subject_hours_teacher_column()
    cols = {c["name"] for c in inspect(engine).get_columns("subject_hours")}
    assert "teacher_id" in cols
    _ensure_subject_hours_teacher_column()  # идемпотентность — второй вызов не падает


def test_ensure_subject_hours_zet_column_adds_to_old_schema(client):
    """Таблица без zet (схема ДО ЗЕТ, docs/PLAN-ZET.md) — миграция должна дописать
    колонку ALTER-ом, как и teacher_id выше."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE subject_hours"))
        conn.execute(text("""CREATE TABLE subject_hours (
            id VARCHAR PRIMARY KEY, group_name VARCHAR, subject VARCHAR,
            year VARCHAR, semester INTEGER DEFAULT 0, hours_total INTEGER DEFAULT 0,
            updated_at VARCHAR DEFAULT '', deleted BOOLEAN DEFAULT 0,
            teacher_id VARCHAR DEFAULT ''
        )"""))
    engine.dispose()
    _ensure_subject_hours_zet_column()
    cols = {c["name"] for c in inspect(engine).get_columns("subject_hours")}
    assert "zet" in cols
    _ensure_subject_hours_zet_column()  # идемпотентность — второй вызов не падает
