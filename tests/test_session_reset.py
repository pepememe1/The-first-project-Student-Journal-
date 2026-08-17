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
from sync import sync_engine
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


def test_force_full_pull(fresh_db):
    sync_engine._session.full_pull_done = True
    sync_engine.force_full_pull()
    assert sync_engine._session.full_pull_done is False


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


def test_reconcile_pushes_offline_edits_before_wipe(fresh_db):
    """Регрессия потери данных: reconcile обязан ОТПРАВИТЬ локальные правки (напр.
    оценки, выставленные преподавателем офлайн) ДО reset_synced_local_data(). Иначе
    сброс кэша уничтожит их до синхронизации — безвозвратно."""
    _seed_synced_data()   #среди данных — оценка Петров/Пётр/L1 = 5 (как офлайн-правка)
    client = _FakeClient()

    sync_engine.reconcile(client)

    assert client.pushes, "reconcile должен был вызвать push"
    first = client.pushes[0]           #ПЕРВЫЙ push — до очистки кэша
    grades = first.get("grades", [])
    assert any(g.get("student_f") == "Петров" and g.get("lesson_id") == "L1"
               and g.get("grade") == "5" for g in grades), (
        "первый push обязан содержать офлайн-оценку — иначе reset сотрёт её до отправки")


def test_reconcile_keeps_cache_when_push_fails(fresh_db):
    """Если push перед сбросом не удался (сервер отпал) — кэш НЕ стираем: данные важнее
    «чистоты». reconcile пробрасывает исключение, локальные оценки остаются на месте."""
    _seed_synced_data()

    class _Boom:
        def push(self, data):
            raise RuntimeError("сеть отвалилась")

        def pull(self, since=""):
            return {"changes": {}}

    with pytest.raises(RuntimeError):
        sync_engine.reconcile(_Boom())

    conn = DBManager.get_conn(); cur = conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 1, \
        "оценка должна уцелеть — кэш не стираем при неудачном push"
    conn.close()
