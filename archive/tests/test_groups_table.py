"""Архив 15.10.2026: тесты выведенного sync/sync_engine.py (продукт его не зовёт с
25.09.2026, см. tests/test_legacy_sync_engine_fenced.py). Перенесены ДОСЛОВНО из
tests/test_groups_table.py; не исполняются. Инварианты живого пути держат
desktop/local_mirror, desktop/desk_outbox и server/tests/test_sync*.py."""

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


