"""
test_throttle_gc.py — анти-брутфорс не течёт по памяти и не банит за старые опечатки.

Две проблемы, которые тут закрыты:
 1) УТЕЧКА: сервер в интернете долбят боты с тысяч IP. Каждая пара (IP, логин) оставляла
    запись НАВСЕГДА → словари росли безгранично. Теперь протухшие записи вытесняются.
 2) СЧЁТЧИК БЕЗ ОКНА: неудачи копились вечно (обнулялись только после блокировки), и
    7 опечаток за полгода давали бан живому человеку. Теперь скользящее окно.
"""
import time

from app import throttle


def setup_function():
    throttle.reset()


def test_stale_entries_are_evicted():
    """Записи без блокировки и без активности дольше IDLE_TTL — вычищаются."""
    for i in range(50):
        throttle.register_failure(f"10.0.0.{i}", "user")
    assert throttle.sizes()[0] == 50

    #«состарим» записи вручную (эквивалент простоя дольше IDLE_TTL)
    old = time.time() - throttle.IDLE_TTL - 1
    for rec in list(throttle._pairs.values()) + list(throttle._ips.values()):
        rec["last"] = old
    pairs, ips, _ = throttle.gc_now()
    assert pairs == 0 and ips == 0, "протухшие записи должны быть вытеснены"


def test_entries_with_fails_are_also_evicted():
    """Мусор с fails>0 (бот сделал пару попыток и ушёл) тоже вычищается — иначе утечка
    осталась бы почти нетронутой (типовой ботнет-паттерн)."""
    throttle.register_failure("203.0.113.7", "admin")      #1 неудача, блокировки нет
    rec = throttle._pairs[throttle._pair_key("203.0.113.7", "admin")]
    assert rec["fails"] > 0
    rec["last"] = time.time() - throttle.IDLE_TTL - 1
    for r in throttle._ips.values():
        r["last"] = time.time() - throttle.IDLE_TTL - 1
    assert throttle.gc_now()[0] == 0


def test_locked_entries_survive_gc():
    """Заблокированные НЕ вычищаются раньше срока — иначе наказание терялось бы."""
    for _ in range(throttle.MAX_FAILS):
        throttle.register_failure("198.51.100.5", "victim")
    assert throttle.seconds_until_unlocked("198.51.100.5", "victim") > 0
    #даже «состаренные» по last, но заблокированные — остаются
    for rec in throttle._pairs.values():
        rec["last"] = time.time() - throttle.IDLE_TTL - 1
    throttle.gc_now()
    assert throttle.seconds_until_unlocked("198.51.100.5", "victim") > 0


def test_old_failures_do_not_accumulate_into_lockout():
    """Скользящее окно: давние неудачи не складываются с новыми (нет ложного бана)."""
    ip, login = "192.0.2.10", "student"
    for _ in range(throttle.MAX_FAILS - 1):        #на одну меньше порога
        throttle.register_failure(ip, login)
    assert throttle.seconds_until_unlocked(ip, login) == 0

    #прошло больше окна — серия должна начаться заново
    key = throttle._pair_key(ip, login)
    throttle._pairs[key]["last"] = time.time() - throttle.FAIL_WINDOW - 1
    throttle.register_failure(ip, login)
    assert throttle.seconds_until_unlocked(ip, login) == 0, \
        "старые неудачи не должны докидывать до блокировки"
    assert throttle._pairs[key]["fails"] == 1, "счётчик начинается заново"


def test_fast_series_still_locks():
    """Быстрая серия (реальный перебор) по-прежнему блокируется."""
    ip, login = "192.0.2.20", "student"
    for _ in range(throttle.MAX_FAILS):
        throttle.register_failure(ip, login)
    assert throttle.seconds_until_unlocked(ip, login) > 0
