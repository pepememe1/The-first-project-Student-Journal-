"""test_shared_ip_login.py — вход из-за ОБЩЕГО адреса (VPN, NAT вуза) и защита процессора.

Почему это отдельный файл и почему вообще тест.

В России студенты массово сидят за VPN и мобильным NAT: возле вузов интернет глушат,
работают белые списки — ради этого у GradeBookAI и есть офлайн-режим. Значит за ОДНИМ
выходным адресом оказывается целая группа живых людей.

Прежний анти-брутфорс считал по адресу ЛЮБУЮ неудачу и запирал адрес целиком на 5 минут
после 30-й. Порог набирался буднично: двадцать пять человек первого сентября, каждый
разок опечатался в своём пароле — и вход закрыт всем, включая тех, кто не ошибался. Со
стороны это неотличимо от «сайт сломался», и объяснить человеку причину нечем.

Правило теперь такое: за адрес целиком отвечают только попытки против НЕСУЩЕСТВУЮЩИХ
логинов (подпись перебора и разведки), а подбор конкретного аккаунта по-прежнему ловит
пара (IP, логин). Тесты ниже закрепляют обе стороны — иначе «починка» легко превращается
в «защиты нет».
"""
import threading
import time

from app import throttle


def setup_function(_fn):
    throttle.reset()


def test_group_behind_one_vpn_does_not_lock_itself_out():
    """40 опечаток разных студентов в СВОИХ паролях с одного адреса — адрес НЕ заперт.

    Это и есть живой сценарий: общий выходной IP, у каждого свой существующий логин."""
    ip = "203.0.113.50"
    for i in range(40):
        throttle.register_failure(ip, f"student{i}@esstu.ru", login_exists=True)

    #Ни один из этих студентов не должен получить отказ по вине соседей.
    for i in range(40):
        assert throttle.seconds_until_unlocked(ip, f"student{i}@esstu.ru") == 0, (
            "адрес заперт из-за чужих опечаток — за VPN так закроется вся группа")


def test_spraying_unknown_logins_still_locks_the_address():
    """ОБРАТНЫЙ тест: перебор по НЕсуществующим логинам адрес по-прежнему запирает.

    Без него предыдущая проверка зелёная и при реализации «никогда не запирать адрес» —
    то есть защита от распыления была бы молча выключена, а тесты бы этого не заметили."""
    ip = "198.51.100.77"
    for i in range(throttle.IP_MAX_FAILS + 5):
        throttle.register_failure(ip, f"nobody{i}", login_exists=False)

    assert throttle.seconds_until_unlocked(ip, "whoever") > 0, (
        "распыление по выдуманным логинам осталось безнаказанным")


def test_targeted_bruteforce_on_a_real_account_is_still_stopped():
    """Подбор пароля к ОДНОМУ существующему аккаунту ловится парой (IP, логин).

    Именно поэтому ослабление счётчика по адресу безопасно: целевая атака упирается сюда."""
    ip, login = "203.0.113.9", "victim@esstu.ru"
    for _ in range(throttle.MAX_FAILS):
        throttle.register_failure(ip, login, login_exists=True)

    assert throttle.seconds_until_unlocked(ip, login) > 0
    #А сосед по тому же адресу при этом работает как ни в чём не бывало.
    assert throttle.seconds_until_unlocked(ip, "neighbour@esstu.ru") == 0


def test_hash_slots_are_limited_but_never_ban():
    """Слотов на дорогую сверку пароля конечное число, и лишний получает ОТКАЗ, а не бан.

    Проверяем именно «занято → False», потому что от этого зависит ответ 503 вместо
    молчаливого выедания процессора."""
    held = []
    try:
        for _ in range(throttle.MAX_CONCURRENT_HASHES):
            cm = throttle.hash_slot(wait=0.1)
            assert cm.__enter__() is True
            held.append(cm)

        with throttle.hash_slot(wait=0.1) as got:
            assert got is False, "слоты кончились, а сервер всё равно взялся считать хеш"
    finally:
        for cm in held:
            cm.__exit__(None, None, None)

    #Слот освобождается — следующий входящий проходит сразу. Это не наказание.
    with throttle.hash_slot(wait=0.5) as got:
        assert got is True, "слот не вернулся в оборот — вход встал бы навсегда"


def test_hash_slot_is_released_even_when_the_body_raises():
    """Исключение внутри блока не должно съедать слот НАВСЕГДА.

    Без этого пара ошибок в ветке проверки пароля тихо обнулила бы пропускную способность
    входа, и сервер перестал бы пускать людей вовсе — без единой строки в логе."""
    for _ in range(throttle.MAX_CONCURRENT_HASHES + 2):
        try:
            with throttle.hash_slot(wait=0.5) as got:
                assert got is True
                raise RuntimeError("сбой посреди сверки пароля")
        except RuntimeError:
            pass

    with throttle.hash_slot(wait=0.5) as got:
        assert got is True, "слоты утекли после исключений"


def test_slots_scale_with_the_machine():
    """Слотов не меньше двух и не больше восьми — зашитой двойки быть не должно.

    Цена ошибки в обе стороны реальная: на одноядерном VPS избыток слотов кладёт сайт, а
    на шестиядерном бою (i5-12400F) жёсткая двойка искусственно душит вход в 9:00."""
    assert 2 <= throttle.MAX_CONCURRENT_HASHES <= 8
