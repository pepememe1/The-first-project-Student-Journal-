"""
test_groups_table.py — Группы в ТАБЛИЦЕ (план техдолга №2, пилот): прямой синк без
переводчика, миграция старых kv-баз, надгробия/LWW. Публичный API data_store сохранён,
поэтому UI не затронут.
"""
import pytest

from sync import sync_engine
from data.core import DBManager
from data.data_store import get_store, _kv_set, _kv_get

G = "ИС-21"


def _group_rows_count(name):
    conn = DBManager.get_conn(); cur = conn.cursor()
    n = cur.execute("SELECT COUNT(*) FROM groups WHERE name=?", (name,)).fetchone()[0]
    conn.close()
    return n


def test_set_get_groups_via_table(fresh_db):
    st = get_store()
    st.set_groups([{"name": G, "subjects": ["Математика"]}])
    assert [g["name"] for g in st.get_groups()] == [G]
    assert [g["subjects"] for g in st.get_groups()] == [["Математика"]]
    assert _group_rows_count(G) == 1          #лежит в таблице, не в kv
    assert _kv_get("groups", None) is None     #kv-ключ групп больше не используется


def test_groups_collect_server_shape(fresh_db):
    get_store().set_groups([{"name": G, "subjects": ["Математика"]}])
    row = [x for x in sync_engine.collect_local()["groups"] if x["name"] == G]
    assert row and row[0]["id"] == "grp:ИС-21" and row[0]["subjects"] == ["Математика"]


def test_groups_remote_upsert_and_tombstone(fresh_db):
    st = get_store()
    sync_engine.apply_remote({"groups": [{
        "id": "grp:ИС-21", "name": G, "subjects": ["Физика"],
        "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False}]})
    assert [g["subjects"] for g in st.get_groups() if g["name"] == G] == [["Физика"]]

    sync_engine.apply_remote({"groups": [{
        "id": "grp:ИС-21", "name": G, "subjects": [],
        "updated_at": "2099-01-01T00:00:00+00:00", "deleted": True}]})
    assert G not in [g["name"] for g in st.get_groups()]


def test_groups_set_stamp_makes_tombstone(fresh_db):
    st = get_store()
    st.set_groups([{"name": "A", "subjects": []}, {"name": "B", "subjects": []}])
    st.set_groups([{"name": "A", "subjects": []}])          #B исчезла
    assert [g["name"] for g in st.get_groups()] == ["A"]     #B не видна в live
    tomb = [g for g in st.get_groups_raw() if g["name"] == "B"]
    assert tomb and tomb[0]["deleted"] is True               #B стала надгробием (уедет на сервер)


def test_groups_migrate_from_kv(fresh_db):
    #Старая база: группы лежат в kv_store, таблица пуста.
    _kv_set("groups", [{"name": "ИС-99", "subjects": ["X"],
                        "updated_at": "2020-01-01T00:00:00+00:00", "deleted": False}], wake=False)
    st = get_store()
    assert "ИС-99" in [g["name"] for g in st.get_groups()]    #первый доступ мигрирует
    assert _group_rows_count("ИС-99") == 1                    #данные в таблице
    assert _kv_get("groups", None) is None                   #старый kv-ключ убран


def test_category_survives_set_groups_round_trip(fresh_db):
    """Регрессия: get_groups()/set_groups() раньше не знали о category вовсе — любая
    правка через них (например, редактирование предметов ОДНОЙ группы) молча стирала
    category у ВСЕХ групп при следующей записи (_groups_write_raw делает DELETE +
    полный реinsert списком, вернувшимся из get_groups()). category приезжает
    ТОЛЬКО с сервера (импорт по категории расписания/специальности) — этот тест
    эмулирует такую строку напрямую и проверяет, что get_groups() её видит и что
    set_groups() (типичная UI-правка другой группы) её не роняет."""
    sync_engine.apply_remote({"groups": [
        {"id": "grp:Б165", "name": "Б165", "subjects": [], "category": "bakalavriat",
         "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False},
        {"id": f"grp:{G}", "name": G, "subjects": ["Физика"],
         "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False},
    ]})
    st = get_store()
    by_name = {g["name"]: g for g in st.get_groups()}
    assert by_name["Б165"]["category"] == "bakalavriat"
    assert by_name[G].get("category") in ("", None)   # без категории — не "bakalavriat"

    #Типичная UI-правка: get_groups() → мутировать ОДНУ группу → set_groups(целиком).
    groups = st.get_groups()
    for g in groups:
        if g["name"] == G:
            g["subjects"] = ["Физика", "Химия"]
    st.set_groups(groups)

    by_name2 = {g["name"]: g for g in st.get_groups()}
    assert by_name2["Б165"]["category"] == "bakalavriat"   # НЕ стёрлась чужой правкой
    assert by_name2[G]["subjects"] == ["Физика", "Химия"]


def test_apply_remote_groups_does_not_wake_sync(fresh_db, monkeypatch):
    from sync import sync_runner
    calls = {"n": 0}
    monkeypatch.setattr(sync_runner, "trigger", lambda: calls.__setitem__("n", calls["n"] + 1))
    sync_engine.apply_remote({"groups": [{
        "id": "grp:ИС-21", "name": G, "subjects": [],
        "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False}]})
    assert calls["n"] == 0, "применение серверных групп не должно будить синк"
    get_store().set_groups([{"name": "ИС-22", "subjects": []}])
    assert calls["n"] >= 1, "UI-правка групп должна будить синк"


def test_unreadable_groups_table_is_not_reported_as_empty(fresh_db, monkeypatch):
    """🔥 РЕАЛЬНЫЙ ДЕФЕКТ, найденный при уборке. Сбой SELECT'а по таблице групп гасился
    в `rows = []`, и «базу не прочитать» становилось неотличимо от «групп нет».

    Цена не теоретическая: `set_groups(stamp=True)` строит НАДГРОБИЯ сравнением нового
    списка с тем, что сейчас в базе. Прочитали «пусто» — сравнивать не с чем, надгробий
    нет, и удаление группы не уедет на сервер НИКОГДА (удаление ходит только надгробием).
    Ровно эту мину уже обезвредили в `_users_table_read`, но тогда починили одну таблицу
    из двух.

    Проверяем поведение, а не текст: чтение обязано ПАДАТЬ, а не возвращать [].
    """
    import sqlite3

    from data import data_store as ds

    st = ds.get_store()
    st.set_groups([{"name": "К74/1", "subjects": ["Математика"]}])
    assert [g["name"] for g in st.get_groups()] == ["К74/1"]

    class _BrokenCursor:
        def execute(self, *a, **kw):
            raise sqlite3.OperationalError("database is locked")

    class _BrokenConn:
        def cursor(self):
            return _BrokenCursor()

        def close(self):
            pass

    monkeypatch.setattr(ds.DBManager, "get_conn", classmethod(lambda cls: _BrokenConn()))
    with pytest.raises(sqlite3.OperationalError):
        ds._groups_read_raw()


def test_broken_subjects_json_does_not_hide_the_whole_group(fresh_db):
    """Обратная сторона той же правки: одна битая строка НЕ имеет права ронять список.

    Без этого теста «пробрасывать исключения» легко довести до абсурда — и тогда
    единственная испорченная запись закрывала бы экран групп целиком. Группа обязана
    остаться видимой, просто без предметов."""
    from data import data_store as ds

    st = ds.get_store()
    st.set_groups([{"name": "К74/1", "subjects": ["Математика"]}])

    conn = ds.DBManager.get_conn()
    conn.execute("UPDATE groups SET subjects=? WHERE name=?", ("{не json", "К74/1"))
    conn.commit()
    conn.close()

    rows = {g["name"]: g for g in st.get_groups()}
    assert "К74/1" in rows, "битый JSON у одной группы скрыл её целиком"
    assert rows["К74/1"]["subjects"] == []
