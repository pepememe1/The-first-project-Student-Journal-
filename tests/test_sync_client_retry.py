"""
test_sync_client_retry.py — Клиент синка устойчив к транзиентным сетевым блипам.

Регрессионный гард на фикс «отложено (попытка 1): Read timed out / RemoteDisconnected»:
у сессии клиента должны быть авто-ретраи (одиночный блип канала до РФ-VPS гасится на
уровне HTTP и не всплывает как сбой), а таймауты — кортежи (connect, read).
"""
from sync_client import SyncClient, DEFAULT_TIMEOUT, SYNC_TIMEOUT, HEALTH_TIMEOUT


def test_session_has_retry_adapter():
    c = SyncClient("https://example.test")
    adapter = c._session.get_adapter("https://example.test")
    retries = adapter.max_retries
    assert retries.total and retries.total >= 2, "должны быть авто-ретраи"
    assert retries.connect and retries.connect >= 2, "ретраи на connect-блипы"
    assert 502 in retries.status_forcelist and 503 in retries.status_forcelist


def test_timeouts_are_connect_read_tuples():
    for t in (DEFAULT_TIMEOUT, SYNC_TIMEOUT, HEALTH_TIMEOUT):
        assert isinstance(t, tuple) and len(t) == 2, "таймаут = (connect, read)"
    #connect не должен быть впритык (РФ-VPS за Cloudflare) — минимум 5 c.
    assert DEFAULT_TIMEOUT[0] >= 5 and SYNC_TIMEOUT[0] >= 5
    #read у синка длиннее — крупный первый pull/push.
    assert SYNC_TIMEOUT[1] >= 30


def test_health_false_on_unreachable_is_fast():
    #health БЕЗ ретраев → падает быстро (порт 1 на localhost — отказ соединения мгновенно).
    #Это гарантирует, что оффлайн-вход/закрытие не виснут на ретраях.
    import time as _t
    c = SyncClient("http://127.0.0.1:1")
    t0 = _t.time()
    assert c.health() is False
    assert _t.time() - t0 < 5, "health должен падать быстро (без авто-ретраев)"
