"""
test_throttle_across_workers.py — держится ли защита, когда процессов НЕСКОЛЬКО.

🔑 РАДИ ЭТОГО ФАЙЛА И ДЕЛАЛСЯ ПЕРЕНОС. Всё остальное — примитивы и обвязка; проверяемое
свойство ровно одно: **порог остаётся порогом, а не умножается на число воркеров.**

Дефект, от которого защищаемся, невидим по построению. Счётчик в памяти процесса даёт
каждому воркеру СВОЮ копию: восемь попыток на пару (IP, логин) превращаются в 8×N,
и обнаружить это можно только подобрав пароль — ни один тест на одном процессе не
покраснеет, потому что там N = 1.

⚠️ Поэтому здесь моделируется именно ВТОРОЙ ПРОЦЕСС: `shared_state.reset_for_tests()`
забывает выбранный движок и все локальные объекты — то есть ведёт себя как свежий
uvicorn, поднявшийся рядом и подключившийся к тому же Redis. Хранилище при этом ОДНО
и то же (общий `FakeServer`), как на настоящей машине.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import shared_state as S  # noqa: E402
from app import throttle           # noqa: E402

IP, LOGIN = "203.0.113.77", "victim"


@pytest.fixture
def cluster(request, monkeypatch):
    """«Кластер» из процессов, разделяющих одно хранилище.

    Параметр — движок. `memory` здесь не для симметрии, а как ОБРАТНЫЙ ХОД: на нём
    проверка обязана краснеть, иначе она не проверяет ничего.
    """
    engine = request.param

    if engine == "redis":
        import fakeredis
        import redis as real_redis
        srv = fakeredis.FakeServer()          #одно хранилище на все «процессы»

        class _Shared:
            @staticmethod
            def from_url(_url, **kw):
                return fakeredis.FakeRedis(
                    server=srv, decode_responses=kw.get("decode_responses", False))

        monkeypatch.setattr(real_redis, "Redis", _Shared)
        monkeypatch.setenv("GRADEBOOK_REDIS_URL", "redis://localhost:6379/0")
    else:
        monkeypatch.delenv("GRADEBOOK_REDIS_URL", raising=False)

    def restart_worker():
        """Сменить процесс: состояние в памяти теряется, общее — остаётся."""
        S.reset_for_tests()

    S.reset_for_tests()
    throttle.reset()
    yield restart_worker
    S.reset_for_tests()


@pytest.mark.parametrize("cluster", ["redis"], indirect=True)
def test_failures_from_different_workers_add_up_to_one_lockout(cluster):
    """Восемь попыток по разным воркерам обязаны запереть так же, как восемь по одному.

    Это и есть «5×N», только с нашими числами: раздели серию между процессами, и при
    поворкерном счётчике замок не защёлкнется НИКОГДА.
    """
    for i in range(throttle.MAX_FAILS):
        if i:                       #каждую попытку принимает СЛЕДУЮЩИЙ воркер
            cluster()
        throttle.register_failure(IP, LOGIN)

    cluster()
    assert throttle.seconds_until_unlocked(IP, LOGIN) > 0, (
        "серия, размазанная по воркерам, не заперла вход — счётчик поворкерный")


@pytest.mark.parametrize("cluster", ["memory"], indirect=True)
def test_reverse_on_process_memory_the_lockout_never_happens(cluster):
    """🔒 ОБРАТНЫЙ ХОД: без общего хранилища тот же сценарий защиту НЕ включает.

    Проверка, зелёная и до починки, неотличима от исправного кода и хуже отсутствия
    проверки. Здесь она краснеет: в памяти процесса каждая «смена воркера» стирает
    счётчик, и восемь попыток не дают ни одной блокировки.
    """
    for i in range(throttle.MAX_FAILS):
        if i:
            cluster()
        throttle.register_failure(IP, LOGIN)

    cluster()
    assert throttle.seconds_until_unlocked(IP, LOGIN) == 0, (
        "в памяти процесса замок защёлкнулся — значит «смена воркера» смоделирована "
        "неверно, и первый тест зелёный не по той причине")


@pytest.mark.parametrize("cluster", ["redis"], indirect=True)
def test_a_ban_from_one_worker_holds_in_all_of_them(cluster):
    """Бан по приманке. Иначе сканер, забаненный в одном процессе из N, спокойно
    продолжает через остальные — то есть приманка перестаёт быть защитой."""
    assert throttle.ban_ip("198.51.100.9", 300) is True
    cluster()
    assert throttle.seconds_until_unbanned("198.51.100.9") > 0


@pytest.mark.parametrize("cluster", ["redis"], indirect=True)
def test_the_recovery_cooldown_is_an_hour_not_an_hour_over_n(cluster):
    """Остуда сброса пароля. `POST /auth/recover` меняет пароль без подтверждения по
    ссылке, поэтому «час» здесь — единственное, что стоит между чужой почтой и
    выбиванием студента из журнала. Час/N этой работы не делает."""
    throttle.register_recover("student@esstu.ru")
    cluster()
    assert throttle.seconds_until_recover_allowed("student@esstu.ru") > 0


@pytest.mark.parametrize("cluster", ["redis"], indirect=True)
def test_suspicion_sees_the_attack_spread_over_workers(cluster):
    """Признак подозрения собирается ПО ЛОГИНУ со всех адресов — в этом весь смысл.

    При поворкерном счётчике каждый процесс видел бы свою долю неудач, порог не
    набирался бы, и ступенчатый второй фактор просто перестал бы спрашиваться. Отказ
    тихий: защита выключена, а выглядит всё исправным.
    """
    for i in range(throttle.SUSPICION_FAILS):
        if i:
            cluster()
        throttle.register_login_attack(LOGIN, "10.0.0.%d" % i)

    cluster()
    got = throttle.suspicion(LOGIN)
    assert got["suspicious"] is True, got
    assert got["fails"] == throttle.SUSPICION_FAILS, (
        "неудачи разных воркеров не сложились: %r" % (got,))
    assert got["ips"] == throttle.SUSPICION_FAILS, (
        "адреса разных воркеров не сложились — множество потеряно при переносе в JSON")


@pytest.mark.parametrize("cluster", ["redis"], indirect=True)
def test_clearing_suspicion_clears_it_everywhere(cluster):
    """Снятие признака вторым фактором обязано действовать во всех процессах.

    Иначе человек подтвердил код, а соседний воркер продолжает требовать его снова —
    и выглядит это как «сайт не принимает правильный код».
    """
    throttle.register_login_attack(LOGIN, "10.0.0.1")
    throttle.register_login_attack(LOGIN, "10.0.0.2")
    assert throttle.is_suspicious(LOGIN)
    throttle.clear_suspicion(LOGIN)
    cluster()
    assert not throttle.is_suspicious(LOGIN)
