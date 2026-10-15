"""
test_session_reset.py — Сброс синхронизируемого кэша и персистентный вход (без GUI).

Проверяем, что reset_synced_local_data() стирает данные, синхронизируемые с сервером
(students/teachers/groups/занятия/оценки + метку дельты), но СОХРАНЯЕТ
локальные настройки ПК (адрес сервера, device_id, токен, сохранённую сессию). Плюс
lookup_session() и force_full_pull().
"""
import pytest

from data import data_store
from data import app_settings
from data.core import DBManager
from data.data_store import get_store, reset_synced_local_data, local_get, local_set
#ℹ️ `subjects.py` удалён 17.08.2026 (решение Ярослава: зависим чисто от портала
#ВСГУТУ). Локального файла предметов больше нет — охранять от прогона нечего, а в
#программу список приезжает синком в зеркальную копию `local_app.db`.




def _seed_synced_data():
    """Кладёт немного синхронизируемых данных всех видов."""
    st = get_store()
    st.set_groups([{"name": "ИС-21", "subjects": ["Математика"]}])
    st.set_teachers({"Иванов И.И.": {"login": "ivanov", "password_hash": "h",
                                     "subjects": ["Математика"]}})
    st.set_students([{"surname": "Петров", "name": "Пётр", "group": "ИС-21",
                      "login": "petrov", "password_hash": "h"}])
    conn = DBManager.get_conn(); cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO lessons (id,group_name,subject,updated_at,deleted) "
                "VALUES ('L1','ИС-21','Математика','2026-01-01T00:00:00+00:00',0)")
    cur.execute("INSERT OR REPLACE INTO grades (student_f,student_n,lesson_id,grade,updated_at,deleted) "
                "VALUES ('Петров','Пётр','L1','5','2026-01-01T00:00:00+00:00',0)")
    conn.commit(); conn.close()
    data_store.set_sync_watermark("2026-01-01T00:00:00+00:00")


def test_reset_clears_synced_keeps_local(fresh_db):
    #Локальные настройки ПК (должны ПЕРЕЖИТЬ сброс).
    app_settings.set_api_url("http://10.0.0.5:8000")
    dev = app_settings.get_device_id()
    app_settings.set_saved_token("petrov", "tok123")
    app_settings.set_saved_session("petrov", "student")
    local_set("custom_local_flag", "keep-me")

    _seed_synced_data()
    #Контроль: данные на месте до сброса.
    assert get_store().get_students() and get_store().get_groups()

    reset_synced_local_data()

    #Синхронизируемое — стёрто.
    st = get_store()
    assert st.get_students() == []
    assert st.get_teachers() == {}
    assert st.get_groups() == []
    assert data_store.get_sync_watermark() == ""
    conn = DBManager.get_conn(); cur = conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 0
    assert cur.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 0
    conn.close()

    #Локальные настройки — сохранены.
    assert app_settings.get_api_url() == "http://10.0.0.5:8000"
    assert app_settings.get_device_id() == dev
    assert app_settings.get_saved_token("petrov") == "tok123"
    assert app_settings.get_saved_session().get("login") == "petrov"
    assert local_get("custom_local_flag") == "keep-me"


def test_lookup_session(fresh_db):
    st = get_store()
    st.set_teachers({"Иванов И.И.": {"login": "ivanov", "password_hash": "h"}})
    st.set_students([{"surname": "Петров", "name": "Пётр", "group": "ИС-21",
                      "login": "petrov", "password_hash": "h"}])

    admin_login = st.get_admin_login()
    assert st.lookup_session(admin_login) == ("admin", None)

    role, payload = st.lookup_session("ivanov")
    assert role == "teacher" and payload[0] == "Иванов И.И."

    role, payload = st.lookup_session("petrov")
    assert role == "student" and payload == {"f": "Петров", "n": "Пётр", "g": "ИС-21"}

    assert st.lookup_session("ghost") is None
    assert st.lookup_session("") is None


class _FakeClient:
    """Дублёр SyncClient: запоминает КАЖДЫЙ снимок, переданный в push, чтобы проверить,
    что офлайн-правки ушли на сервер ДО очистки кэша."""
    def __init__(self):
        self.pushes = []

    def push(self, data):
        import copy
        self.pushes.append(copy.deepcopy(data))

    def pull(self, since=""):
        #Сервер «пуст» — после сброса локаль останется пустой; нам важен факт push.
        return {"server_time": "2026-02-02T00:00:00+00:00", "changes": {}}


