"""
test_personal_backup.py — снимок ЛИЧНОЙ копии при выходе (исследование синка, находка W-12).

━━ ЧТО БЫЛО ━━
При закрытии окна копия снималась с `vsgutu_grades.db` — старой базы синхронизации, из
которой интерфейс давно не читает. Очередь досылки (оценки, которых бой ещё не видел)
живёт в личной копии `local_app_*.enc.db`, и её не копировал никто: испортись файл —
неотправленная работа пропадала целиком при исправно «снятой» копии рядом.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: заменить `VACUUM INTO` копированием файла — краснеет «снимок
несёт и то, что ещё в -wal»; положить снимки в общую папку копий — краснеет «не
попадает в восстановление базы синхронизации»; убрать уборку — краснеет «десять на
человека»; убрать вызов из закрытия окна — краснеет проводка.
"""
import os
import sys

import pytest

#Программа существует только под Windows, и драйвер SQLCipher клиенту объявлен только там
#(requirements.txt). Под Linux предмета проверки нет — это пропуск по ПРЕДМЕТУ, а не по
#инструменту: на Windows отсутствие драйвера обязано уронить тест громко.
pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="личная копия программы существует только под Windows")

KEY = "5a" * 32


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("GRADEBOOK_DB_KEY", KEY)
    from desktop import local_api
    return local_api


def _open(path):
    import sqlcipher3
    con = sqlcipher3.connect(path)
    con.execute(f"PRAGMA key=\"x'{KEY}'\"")
    return con


def _make_copy(api, login, rows):
    """Личная копия с очередью; писатель ОСТАЁТСЯ открытым — строки лежат в -wal."""
    path = api.local_db_file(login, encrypted=True)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    con = _open(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE desk_outbox (seq INTEGER PRIMARY KEY, body TEXT)")
    con.executemany("INSERT INTO desk_outbox(body) VALUES (?)", [(r,) for r in rows])
    con.commit()
    return con


def test_snapshot_is_encrypted_and_carries_what_is_still_in_the_wal(api):
    writer = _make_copy(api, "pb_1", ["оценка-1", "оценка-2"])
    try:
        snap = api.backup_personal_copy("pb_1")
    finally:
        writer.close()
    assert snap and os.path.exists(snap), "снимок не снят"
    with open(snap, "rb") as f:
        assert not f.read(16).startswith(b"SQLite format 3"), "снимок с ПДн лёг ОТКРЫТЫМ"
    con = _open(snap)
    try:
        got = [r[0] for r in con.execute("SELECT body FROM desk_outbox ORDER BY seq")]
    finally:
        con.close()
    assert got == ["оценка-1", "оценка-2"], "в снимок не попала очередь из -wal"


def test_without_a_device_key_no_snapshot_is_written(api, monkeypatch):
    writer = _make_copy(api, "pb_2", ["x"])
    writer.close()
    monkeypatch.setenv("GRADEBOOK_DB_KEY", "")
    before = set(os.listdir(api.personal_backup_dir())) \
        if os.path.isdir(api.personal_backup_dir()) else set()
    assert api.backup_personal_copy("pb_2") == ""
    after = set(os.listdir(api.personal_backup_dir())) \
        if os.path.isdir(api.personal_backup_dir()) else set()
    assert after == before, "без ключа на диск лёг снимок"


def test_snapshot_does_not_show_up_in_the_sync_database_restore(api):
    """Восстановление `DBManager.restore` кладёт выбранный файл на место базы
    синхронизации — личная копия там была бы восстановлена не в тот файл."""
    writer = _make_copy(api, "pb_3", ["x"])
    try:
        snap = api.backup_personal_copy("pb_3")
    finally:
        writer.close()
    assert snap
    from data.core import DBManager
    listed = " ".join(str(b) for b in DBManager.list_backups())
    assert os.path.basename(snap) not in listed, "снимок личной копии попал в список восстановления"


def test_ten_snapshots_per_person_and_others_are_left_alone(api):
    writer = _make_copy(api, "pb_4", ["x"])
    writer.close()
    other = _make_copy(api, "pb_5", ["y"])
    other.close()
    other_snap = api.backup_personal_copy("pb_5")
    for _ in range(api.PERSONAL_BACKUP_KEEP + 3):
        assert api.backup_personal_copy("pb_4")
    import hashlib
    who = hashlib.sha256(b"pb_4").hexdigest()[:16]
    mine = [f for f in os.listdir(api.personal_backup_dir()) if f.startswith(f"local_app_{who}_")]
    assert len(mine) == api.PERSONAL_BACKUP_KEEP, f"снимков {len(mine)}"
    assert os.path.exists(other_snap), "уборка одного человека снесла снимок другого"


def test_closing_the_window_snapshots_the_personal_copy(api, monkeypatch):
    """Проводка: закрытие окна зовёт снимок личной копии (иначе функция — без вызывающего)."""
    from desktop import webview2_app
    from data.core import DBManager
    from sync import sync_runner
    called = []
    monkeypatch.setattr(sync_runner, "flush", lambda *a, **k: None)
    monkeypatch.setattr(DBManager, "backup", classmethod(lambda cls, reason="": ""))
    monkeypatch.setattr(api, "backup_personal_copy_on_exit", lambda: called.append(1) or "")
    webview2_app._flush_sync()
    assert called, "закрытие окна не снимает копию личной базы"
