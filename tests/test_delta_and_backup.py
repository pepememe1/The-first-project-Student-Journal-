"""
test_delta_and_backup.py — Дельта-синхронизация (метка last_sync, отсутствие
self-wake) и авто-бэкап по расписанию.
"""
import sync_engine
from core import DBManager
from data_store import get_sync_watermark, get_store


class _FakeClient:
    """Заглушка клиента: запоминает since у pull, отдаёт растущий server_time."""
    def __init__(self):
        self.pull_sinces = []
        self.t = 0

    def push(self, changes):
        return {"applied": {}}

    def pull(self, since=""):
        self.pull_sinces.append(since)
        self.t += 1
        return {"server_time": f"T{self.t}", "changes": {}}


def test_delta_watermark_sequence(fresh_db):
    """Первый pull сессии — полный (since=''), дальше — по сохранённой метке."""
    c = _FakeClient()
    sync_engine.sync_once(c)
    sync_engine.sync_once(c)
    sync_engine.sync_once(c)
    assert c.pull_sinces == ["", "T1", "T2"]
    assert get_sync_watermark() == "T3"


def test_watermark_not_pushed_to_server(fresh_db):
    """Метка last_sync — локальная, в выгрузку на сервер не попадает."""
    sync_engine.sync_once(_FakeClient())
    snap = sync_engine.collect_local()
    leaked = any(
        isinstance(x, dict) and x.get("key") == "_sync_watermark"
        for v in snap.values() if isinstance(v, list) for x in v)
    assert not leaked


def test_apply_remote_does_not_wake_sync(fresh_db, monkeypatch):
    """Применение серверных данных НЕ будит синк (иначе apply_remote → wake → синк
    → apply_remote = busy-loop). А обычная UI-правка — будит."""
    import sync_runner
    calls = {"n": 0}
    monkeypatch.setattr(sync_runner, "trigger", lambda: calls.__setitem__("n", calls["n"] + 1))

    sync_engine.apply_remote({
        "groups": [{"name": "ИС-21", "subjects": ["Математика"],
                    "updated_at": "2030-01-01T00:00:00+00:00", "deleted": False}],
        "config": [{"key": "foo", "value": "bar", "deleted": False}],
    })
    assert calls["n"] == 0, "apply_remote не должен будить синк"

    calls["n"] = 0
    get_store().set_groups([{"name": "ИС-22", "subjects": []}])
    assert calls["n"] >= 1, "UI-правка должна будить синк"


def test_backup_if_due_throttles(fresh_db):
    """backup_if_due делает копию не чаще интервала (троттлинг по времени)."""
    p1 = DBManager.backup_if_due(min_interval_sec=1800)
    assert p1
    assert DBManager.backup_if_due(min_interval_sec=1800) == ""   #ещё рано
    p3 = DBManager.backup_if_due(min_interval_sec=0)              #интервал истёк
    assert p3 and p3 != p1
    assert len(DBManager.list_backups()) == 2
