"""
test_users_table.py — Пользователи в ТАБЛИЦЕ users (план №2, Стадия 2): payload зашифрован
blob'ом (хеши/ПДн не оголены), прямой синк без переводчика, миграция старых kv-баз, надгробия,
офлайн-вход после round-trip, админ остаётся в config.
"""
from data.core import DBManager
from data.data_store import get_store, _kv_set, _kv_get
from data.security import verify_password


def _blob_of(uid):
    conn = DBManager.get_conn(); cur = conn.cursor()
    row = cur.execute("SELECT blob FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return row[0] if row else None


def test_set_get_students_via_table(fresh_db):
    st = get_store()
    st.set_students([{"surname": "Иванов", "name": "Иван", "group": "ИС-21",
                      "login": "ivan", "password": "secret1"}])
    s = st.get_students()
    assert len(s) == 1 and s[0]["surname"] == "Иванов" and s[0]["group"] == "ИС-21"
    #лежит в таблице users, роль student
    conn = DBManager.get_conn(); cur = conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0] == 1
    conn.close()


def test_password_hash_encrypted_at_rest(fresh_db):
    """Хеш пароля НЕ лежит в открытом виде: blob зашифрован, но get_students отдаёт
    рабочий хеш (офлайн-вход жив)."""
    st = get_store()
    st.set_students([{"surname": "П", "name": "Пётр", "group": "ИС-21",
                      "login": "p", "password": "mypass"}])
    hashed = st.get_students()[0]["password_hash"]
    assert verify_password("mypass", hashed) and not verify_password("wrong", hashed)
    blob = _blob_of("stud:p")
    assert blob and hashed not in blob, "хеш не должен лежать в blob открытым текстом"


def test_users_migrate_from_kv(fresh_db):
    """Старая база: студенты/преподаватели в kv → мигрируют в таблицу при первом доступе."""
    _kv_set("students", [{"surname": "Старый", "name": "Стас", "group": "ИС-99",
                          "login": "old", "password_hash": "h", "deleted": False}], wake=False)
    _kv_set("teachers", {"Петров П.П.": {"login": "petrov", "password_hash": "h",
                                         "subjects": ["Физика"]}}, wake=False)
    st = get_store()
    assert "Старый" in [s["surname"] for s in st.get_students()]
    assert "Петров П.П." in st.get_teachers()
    #kv НЕ удалён (недеструктивная миграция — бэкап для отката)
    assert _kv_get("students", None) is not None


