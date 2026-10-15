"""Архив 15.10.2026: тесты выведенного sync/sync_engine.py (продукт его не зовёт с
25.09.2026, см. tests/test_legacy_sync_engine_fenced.py). Перенесены ДОСЛОВНО из
tests/test_session_reset.py; не исполняются. Инварианты живого пути держат
desktop/local_mirror, desktop/desk_outbox и server/tests/test_sync*.py."""

def test_force_full_pull(fresh_db):
    sync_engine._session.full_pull_done = True
    sync_engine.force_full_pull()
    assert sync_engine._session.full_pull_done is False


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


