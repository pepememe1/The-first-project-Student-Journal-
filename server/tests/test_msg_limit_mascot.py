"""
test_msg_limit_mascot.py — «маскот-замедление» мессенджера (§D2 плана), эскалация кулдауна.

Проверяем чистую функцию msg_limit.mascot_check() напрямую (без HTTP): порог всплеска,
эскалацию 8→20→60 c по истории нарушений, и что одна затянувшаяся перегрузка не плодит
нарушения на каждый повторный вызов. Время НЕ ждём по-настоящему (иначе тест шёл бы 10
минут) — состариваем метки вручную, как test_throttle_gc.py.
"""
import time

from app import msg_limit


def setup_function():
    msg_limit.reset()


def _send_ok(uid, n):
    """Смоделировать n «успешных» отправок — кладём метки НАПРЯМУЮ в _events (как это
    делает check() при 0), а не через сам check(): при накоплении >10 вызовов за один
    прогон теста БАЗОВЫЙ лимит (10 сообщений/5 c) сам начал бы резать серию и мешал бы
    тестировать именно эскалацию МАСКОТА, а не взаимодействие двух лимитеров."""
    now = time.time()
    for _ in range(n):
        msg_limit._events[uid].append(now)


def test_no_cooldown_under_burst_threshold():
    """Меньше порога всплеска (5 за 8 c) — маскот молчит, писать можно."""
    uid = "stud:a"
    _send_ok(uid, 4)
    wait, violations = msg_limit.mascot_check(uid)
    assert wait == 0 and violations == 0


def test_first_violation_is_short_cooldown():
    """Впервые превысили всплеск — самый мягкий кулдаун (8 c)."""
    uid = "stud:b"
    _send_ok(uid, 5)
    wait, violations = msg_limit.mascot_check(uid)
    assert wait == 8 and violations == 1


def test_repeated_violation_within_5min_escalates_to_20s():
    """Повторное нарушение в течение 5 минут — эскалация до 20 c."""
    uid = "stud:c"
    _send_ok(uid, 5)
    msg_limit.mascot_check(uid)                    # 1-е нарушение зафиксировано
    #«состариваем» само нарушение за пределы окна всплеска, чтобы следующий вызов
    #засчитался НОВЫМ нарушением (а не тем же самым нескончаемым всплеском).
    msg_limit._violations[uid][-1] -= msg_limit._MASCOT_BURST_WINDOW + 1
    wait, violations = msg_limit.mascot_check(uid)
    assert wait == 20 and violations == 2


def test_systematic_violation_within_10min_escalates_to_60s():
    """Третье нарушение за 10 минут — систематика, самый строгий кулдаун (60 c)."""
    uid = "stud:d"
    #Готовим 2 уже «остывших» нарушения (иначе они считались бы одним и тем же всплеском).
    for _ in range(2):
        _send_ok(uid, 5)
        msg_limit.mascot_check(uid)
        msg_limit._violations[uid][-1] -= msg_limit._MASCOT_BURST_WINDOW + 1
    #Третье, свежее — должно распознаться как систематика (3-е за 10 минут).
    _send_ok(uid, 5)
    wait, violations = msg_limit.mascot_check(uid)
    assert wait == 60 and violations == 3


def test_single_ongoing_overload_does_not_multiply_violations():
    """Повторные попытки ВНУТРИ ОДНОГО всплеска (без «остывания») не плодят нарушения —
    иначе один затянувшийся спам-клик мгновенно улетал бы в «систематику»."""
    uid = "stud:e"
    _send_ok(uid, 5)
    w1, v1 = msg_limit.mascot_check(uid)
    w2, v2 = msg_limit.mascot_check(uid)            # тот же всплеск, без остывания
    assert v1 == v2 == 1 and w1 == w2 == 8


def test_old_violations_outside_10min_window_expire():
    """Нарушение старше 10 минут не учитывается в счётчике систематичности."""
    uid = "stud:f"
    _send_ok(uid, 5)
    msg_limit.mascot_check(uid)
    #Состариваем нарушение за пределы окна систематичности (10 мин).
    msg_limit._violations[uid][-1] = time.time() - msg_limit._VIOLATION_WINDOW - 1
    _send_ok(uid, 5)
    wait, violations = msg_limit.mascot_check(uid)
    assert violations == 1, "старое нарушение должно было истечь из окна"
    assert wait == 8


def test_empty_user_id_never_limited():
    assert msg_limit.mascot_check("") == (0, 0)
