"""Архив 15.10.2026: тесты выведенного sync/sync_engine.py (продукт его не зовёт с
25.09.2026, см. tests/test_legacy_sync_engine_fenced.py). Перенесены ДОСЛОВНО из
tests/test_users_table.py; не исполняются. Инварианты живого пути держат
desktop/local_mirror, desktop/desk_outbox и server/tests/test_sync*.py."""

def test_users_collect_server_shape(fresh_db):
    get_store().set_students([{"surname": "Иванов", "name": "Иван", "group": "ИС-21",
                              "login": "ivan", "password": "x"}])
    users = sync_engine.collect_local()["users"]
    u = [x for x in users if x.get("id") == "stud:ivan"]
    assert u and u[0]["role"] == "student" and u[0]["group_name"] == "ИС-21"
    assert verify_password("x", u[0]["password_hash"]), "collect отдаёт расшифрованный хеш серверу"


def test_users_remote_upsert_and_tombstone(fresh_db):
    st = get_store()
    sync_engine.apply_remote({"users": [{
        "id": "stud:ivan", "role": "student", "login": "ivan", "password_hash": "h",
        "surname": "Иванов", "name": "Иван", "group_name": "ИС-21", "prefs": {},
        "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False}]})
    assert [s["surname"] for s in st.get_students()] == ["Иванов"]

    sync_engine.apply_remote({"users": [{
        "id": "stud:ivan", "role": "student", "login": "ivan", "surname": "Иванов",
        "name": "Иван", "group_name": "ИС-21",
        "updated_at": "2099-01-01T00:00:00+00:00", "deleted": True}]})
    assert st.get_students() == []


def test_parent_remote_upsert(fresh_db):
    """§12: роль parent обязана доехать до локальной таблицы так же, как student/teacher —
    иначе вход родителя на десктопе проваливался (сервер подтверждал пароль верным,
    lookup_session/get_parents не находили строку локально после _online_bootstrap)."""
    st = get_store()
    sync_engine.apply_remote({"users": [{
        "id": "par:u:1", "role": "parent", "login": "roditel1", "password_hash": "h",
        "surname": "Сидорова", "name": "Анна", "prefs": {},
        "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False}]})
    parents = st.get_parents()
    assert len(parents) == 1 and parents[0]["login"] == "roditel1"


def test_full_round_trip_preserves_login(fresh_db):
    """set → collect → (стереть) → apply → get: данные и рабочий хеш сохранены."""
    st = get_store()
    st.set_students([{"surname": "Иванов", "name": "Иван", "group": "ИС-21",
                      "login": "ivan", "password": "secret1"}])
    users = sync_engine.collect_local()["users"]
    DBManager.clear_synced_tables()                       #как будто чистый ПК
    assert st.get_students() == []
    sync_engine.apply_remote({"users": users})
    s = st.get_students()
    assert len(s) == 1 and s[0]["login"] == "ivan"
    assert verify_password("secret1", s[0]["password_hash"]), "офлайн-вход после round-trip жив"


def test_teacher_round_trip(fresh_db):
    st = get_store()
    st.set_teachers({"Иванов И.И.": {"login": "ivanov", "password": "tp",
                                     "subjects": ["Математика"]}})
    t = st.get_teachers()
    assert "Иванов И.И." in t and t["Иванов И.И."]["subjects"] == ["Математика"]
    u = [x for x in sync_engine.collect_local()["users"] if x.get("id") == "teach:ivanov"]
    assert u and u[0]["role"] == "teacher" and u[0]["full_name"] == "Иванов И.И."


def test_admin_stays_in_config_not_users_table(fresh_db):
    """role=admin из pull НЕ попадает в таблицу users (его хеш — в config)."""
    sync_engine.apply_remote({"users": [{
        "id": "admin:admin", "role": "admin", "login": "admin", "password_hash": "ah",
        "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False}]})
    conn = DBManager.get_conn(); cur = conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] == 0
    conn.close()
    assert get_store().get_students() == [] and get_store().get_teachers() == {}


def test_apply_remote_users_does_not_wake_sync(fresh_db, monkeypatch):
    from sync import sync_runner
    calls = {"n": 0}
    monkeypatch.setattr(sync_runner, "trigger", lambda: calls.__setitem__("n", calls["n"] + 1))
    sync_engine.apply_remote({"users": [{
        "id": "stud:ivan", "role": "student", "login": "ivan", "surname": "Иванов",
        "name": "Иван", "group_name": "ИС-21",
        "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False}]})
    assert calls["n"] == 0, "применение серверных пользователей не должно будить синк"
    get_store().set_students([{"surname": "Н", "name": "Н", "group": "ИС-21", "login": "n"}])
    assert calls["n"] >= 1, "UI-правка должна будить синк"


