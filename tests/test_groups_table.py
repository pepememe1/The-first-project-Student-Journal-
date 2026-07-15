"""
test_groups_table.py — Группы в ТАБЛИЦЕ (план техдолга №2, пилот): прямой синк без
переводчика, миграция старых kv-баз, надгробия/LWW. Публичный API data_store сохранён,
поэтому UI не затронут.
"""
import sync_engine
from core import DBManager
from data_store import get_store, _kv_set, _kv_get

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


def test_apply_remote_groups_does_not_wake_sync(fresh_db, monkeypatch):
    import sync_runner
    calls = {"n": 0}
    monkeypatch.setattr(sync_runner, "trigger", lambda: calls.__setitem__("n", calls["n"] + 1))
    sync_engine.apply_remote({"groups": [{
        "id": "grp:ИС-21", "name": G, "subjects": [],
        "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False}]})
    assert calls["n"] == 0, "применение серверных групп не должно будить синк"
    get_store().set_groups([{"name": "ИС-22", "subjects": []}])
    assert calls["n"] >= 1, "UI-правка групп должна будить синк"
