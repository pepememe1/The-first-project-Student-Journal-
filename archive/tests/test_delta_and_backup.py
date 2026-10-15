"""Архив 15.10.2026: тесты выведенного sync/sync_engine.py (продукт его не зовёт с
25.09.2026, см. tests/test_legacy_sync_engine_fenced.py). Перенесены ДОСЛОВНО из
tests/test_delta_and_backup.py; не исполняются. Инварианты живого пути держат
desktop/local_mirror, desktop/desk_outbox и server/tests/test_sync*.py."""

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
    from sync import sync_runner
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


