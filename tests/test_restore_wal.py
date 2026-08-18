"""Восстановление локальной базы из копии: чего оно НЕ должно делать (18.08.2026).

История этого файла важнее его содержимого, поэтому записана здесь.

Я предполагал дефект: `restore` подменял `.db`, не трогая соседний журнал `-wal`, —
а SQLite прямо требует убирать `-wal`/`-shm` при подмене файла базы, иначе журнал от
прежней базы накатывается на восстановленную. Написал починку и два теста.

🔥 ОТКАТ ПОКАЗАЛ, ЧТО ДЕФЕКТА НЕТ. Оба теста остались зелёными и на ИСХОДНОМ коде.
Причина в том, что `restore` первым делом зовёт `backup(reason="before_restore")`, а
тот делает `PRAGMA wal_checkpoint(FULL)` — то есть незакреплённых кадров в журнале к
моменту подмены уже нет, и накатывать нечего. Защита была, просто не там, где её
ожидаешь увидеть, и никем не названная.

Те два теста удалены, а не оставлены «на всякий случай»: проверка, зелёная и без
починки, неотличима от исправного кода и хуже отсутствия проверки.

НАСТОЯЩИЙ дефект нашёлся рядом и он мельче, но реальный: `restore` не смотрел на
размер файла копии. Пустой (оборванная закачка, кончилось место при её создании)
копировался поверх рабочей базы совершенно успешно — и человек оставался без данных
вовсе, придя сюда именно за спасением данных. Это и закрыто; держат тесты ниже.
"""
import os
import sqlite3

import pytest

from data.core import DBManager, LOCAL_DB


def _write(marker: str) -> None:
    """Кладём опознаваемую строку в отдельную таблицу — не трогаем рабочие."""
    conn = DBManager.get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS restore_probe (marker TEXT)")
    conn.execute("INSERT INTO restore_probe (marker) VALUES (?)", (marker,))
    conn.commit()
    conn.close()


def _markers() -> list:
    conn = sqlite3.connect(LOCAL_DB, timeout=10)
    try:
        return [r[0] for r in conn.execute("SELECT marker FROM restore_probe").fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def test_restore_actually_restores(fresh_db):
    """ОБРАТНЫЙ ХОД, и он обязателен.

    Проверка выше зелёная и у «починки», которая просто ВСЕГДА возвращает False и ничего
    не делает: журналов рядом тогда тоже не будет. Этот тест требует, чтобы
    восстановление осталось восстановлением — вернуло содержимое копии и убрало то, что
    появилось после неё."""
    _write("до копии")
    backup = DBManager.backup(reason="test")
    _write("после копии")
    assert "после копии" in _markers()

    assert DBManager.restore(backup) is True

    got = _markers()
    assert "до копии" in got, "содержимое копии не вернулось — это не восстановление"
    assert "после копии" not in got, (
        "запись, сделанная ПОСЛЕ копии, пережила восстановление — значит остался журнал "
        "прежней базы и SQLite накатил его поверх")


def test_the_current_database_is_backed_up_before_it_is_overwritten(fresh_db):
    """Страховочная копия делается ДО подмены — иначе неудачное восстановление
    не откатить, а приходят сюда с уже испорченными данными."""
    _write("до копии")
    backup = DBManager.backup(reason="test")
    _write("это должно попасть в страховочную копию")

    before = len(DBManager.list_backups())
    assert DBManager.restore(backup) is True
    assert len(DBManager.list_backups()) > before, \
        "перед подменой базы страховочная копия не создана"


def test_an_empty_backup_file_is_refused(fresh_db):
    """Пустой файл копии — это не «восстановление в пустоту», а потеря рабочей базы:
    `copy2` отработал бы успешно и оставил человека без данных вовсе."""
    _write("рабочие данные")
    empty = os.path.join(os.path.dirname(LOCAL_DB), "empty_backup.db")
    open(empty, "wb").close()

    assert DBManager.restore(empty) is False
    assert "рабочие данные" in _markers(), "рабочая база пострадала от пустой копии"


def test_a_missing_backup_is_refused(fresh_db):
    """ОБРАТНЫЙ ХОД к предыдущему: отказ должен быть по ПРИЧИНЕ, а не «отказываем всему».
    Несуществующий путь — тоже отказ, но рабочая база при этом цела."""
    _write("рабочие данные")
    assert DBManager.restore(os.path.join(os.path.dirname(LOCAL_DB), "нет-такого.db")) is False
    assert "рабочие данные" in _markers()
