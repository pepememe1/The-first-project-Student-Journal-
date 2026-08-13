"""
test_sync_client_retry.py — Клиент синка устойчив к транзиентным сетевым блипам.

Регрессионный гард на фикс «отложено (попытка 1): Read timed out / RemoteDisconnected»:
у сессии клиента должны быть авто-ретраи (одиночный блип канала до РФ-VPS гасится на
уровне HTTP и не всплывает как сбой), а таймауты — кортежи (connect, read).
"""
from sync.sync_client import SyncClient, DEFAULT_TIMEOUT, SYNC_TIMEOUT, HEALTH_TIMEOUT


def _retries(client, retry_post: bool):
    return client._sess(retry_post).get_adapter("https://example.test").max_retries


def test_session_has_retry_adapter():
    c = SyncClient("https://example.test")
    retries = _retries(c, retry_post=False)
    assert retries.total and retries.total >= 2, "должны быть авто-ретраи"
    assert retries.connect and retries.connect >= 2, "ретраи на connect-блипы"
    assert 502 in retries.status_forcelist and 503 in retries.status_forcelist


def test_post_is_not_retried_blindly():
    """POST по умолчанию НЕ повторяется — иначе блип сети даёт ДУБЛЬ записи.

    Повтор безопасен только там, где сервер делает upsert (`push`) или выдаёт токен
    (`login`/`refresh`). А `create_event`/`approve_registration`/`create_parent` при
    повторе создают вторую сущность, и оба запроса при этом «успешны» — заметить такое
    можно только по лишней строке в базе."""
    c = SyncClient("https://example.test")
    assert "POST" not in _retries(c, retry_post=False).allowed_methods
    #Обратная сторона: у идемпотентных вызовов повтор обязан остаться, иначе один блип
    #канала снова начнёт всплывать как «сбой синхронизации».
    assert "POST" in _retries(c, retry_post=True).allowed_methods


def test_sessions_are_per_thread():
    """`requests.Session` не потокобезопасна — у каждого потока должна быть своя.

    Потоков реально несколько: фоновый цикл синка, прокси мессенджера в локальном
    сервере, отправка темы, закрытие программы."""
    import threading

    c = SyncClient("https://example.test")
    mine = c._sess(False)
    seen = []
    #Держим САМ объект, а не id(): после завершения потока его сессия освобождается, и
    #CPython переиспользует тот же адрес — сравнение id дало бы ложное «совпадает».
    t = threading.Thread(target=lambda: seen.append(c._sess(False)))
    t.start(); t.join()
    assert seen and seen[0] is not mine, "сессия общая на два потока"


def test_empty_base_url_is_refused_loudly():
    """Пустой адрес раньше давал относительный запрос и невнятную ошибку внутри requests."""
    import pytest
    with pytest.raises(ValueError):
        SyncClient("")


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
