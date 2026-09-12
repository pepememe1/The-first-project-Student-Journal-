"""
test_webauthn_challenges.py — задача-вызов passkey переживает смену процесса.

🔥 ПОЧЕМУ ЭТОТ ФАЙЛ ПОЯВИЛСЯ ОТДЕЛЬНО (10.09.2026). В `test_webauthn.py` четыре
проверки, и НИ ОДНА не проходит круг «выдали задачу — получили ответ»: настоящий ответ
браузера требует настоящего аутентификатора, поэтому проверялись только двери
(`login_begin` публичен, `register_begin` требует входа, чужой ключ отвергается).

Значит хранилище задач-вызовов не было покрыто вовсе — и перенос его в общее состояние
прошёл бы «зелёным» независимо от того, работает он или нет. Это ровно наш класс
«зелёный тест рядом с дефектом», только здесь он молчал бы про ВХОД.

Круг проверяется на уровне `_put`/`_pop` — той пары, через которую ходят все четыре
ручки. Аутентификатор для этого не нужен, а свойство проверяется настоящее.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import shared_state as S                       # noqa: E402
from app.routers import webauthn_router as W            # noqa: E402

CHALLENGE = b"\x00\x01\x02\xfe\xff-\xd0\x9f\xd1\x80\xd0\xb8"   #байты, а не текст


@pytest.fixture
def cluster(request, monkeypatch):
    """Хранилище, общее для «процессов». Параметр — движок."""
    if request.param == "redis":
        import fakeredis
        import redis as real_redis
        srv = fakeredis.FakeServer()

        class _Shared:
            @staticmethod
            def from_url(_url, **kw):
                return fakeredis.FakeRedis(
                    server=srv, decode_responses=kw.get("decode_responses", False))

        monkeypatch.setattr(real_redis, "Redis", _Shared)
        monkeypatch.setenv("GRADEBOOK_REDIS_URL", "redis://localhost:6379/0")
    else:
        monkeypatch.delenv("GRADEBOOK_REDIS_URL", raising=False)
    S.reset_for_tests()
    yield S.reset_for_tests          #позвать = «ответ прилетел в другой процесс»
    S.reset_for_tests()


@pytest.mark.parametrize("cluster", ["memory", "redis"], indirect=True)
def test_the_challenge_comes_back_byte_for_byte(cluster):
    """Задача-вызов — БАЙТЫ, а хранилище общее принимает JSON.

    Кодировка тут не деталь: подпись сверяется с этими самыми байтами, и потеря одного
    из них даёт «ключ не подошёл» — то есть отказ, неотличимый от чужого ключа.
    """
    W._put(W._K_REG, "bob", CHALLENGE)
    assert W._pop(W._K_REG, "bob") == CHALLENGE


@pytest.mark.parametrize("cluster", ["memory", "redis"], indirect=True)
def test_a_challenge_is_one_time(cluster):
    """Второй раз забрать нечего — иначе ответ можно повторить."""
    W._put(W._K_AUTH, "bob", CHALLENGE)
    assert W._pop(W._K_AUTH, "bob") == CHALLENGE
    assert W._pop(W._K_AUTH, "bob") is None


@pytest.mark.parametrize("cluster", ["memory", "redis"], indirect=True)
def test_registration_and_login_challenges_do_not_mix(cluster):
    """Разные двери — разные ключи. Иначе заведение ключа открывало бы вход."""
    W._put(W._K_REG, "bob", CHALLENGE)
    assert W._pop(W._K_AUTH, "bob") is None
    assert W._pop(W._K_REG, "bob") == CHALLENGE


@pytest.mark.parametrize("cluster", ["memory", "redis"], indirect=True)
def test_an_expired_challenge_is_not_accepted(cluster, monkeypatch):
    """Срок в пять минут — часть защиты, а не уборка."""
    monkeypatch.setattr(W, "_CHALLENGE_TTL", 0.25)
    W._put(W._K_AUTH, "bob", CHALLENGE)
    time.sleep(0.4)
    assert W._pop(W._K_AUTH, "bob") is None


@pytest.mark.parametrize("cluster", ["redis"], indirect=True)
def test_the_answer_may_arrive_at_a_different_worker(cluster):
    """🔥 РАДИ ЭТОГО ПЕРЕНОС И ДЕЛАЛСЯ.

    Браузер шлёт ответ на ЛЮБОЙ процесс — какой достанется, решает балансировщик, а не
    мы. Пока задача лежала в памяти одного, вход по ключу отваливался в (N−1)/N
    случаев, и выглядело бы это как «passkey иногда не срабатывает».
    """
    W._put(W._K_AUTH, "bob", CHALLENGE)
    cluster()                                   #ответ пришёл в другой процесс
    assert W._pop(W._K_AUTH, "bob") == CHALLENGE


@pytest.mark.parametrize("cluster", ["memory"], indirect=True)
def test_reverse_in_process_memory_the_answer_is_lost(cluster):
    """🔒 ОБРАТНЫЙ ХОД: без общего хранилища та же задача до второго процесса не дойдёт.

    Без него предыдущий тест был бы зелёным и до починки — то есть не проверял бы
    ничего, а лишь создавал уверенность.
    """
    W._put(W._K_AUTH, "bob", CHALLENGE)
    cluster()
    assert W._pop(W._K_AUTH, "bob") is None, (
        "задача пережила смену процесса в памяти — значит «смена» смоделирована неверно")
