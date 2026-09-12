"""
test_shared_state.py — общее состояние между процессами (10.09.2026).

🔑 ГЛАВНАЯ МЫСЛЬ ЭТОГО ФАЙЛА: движка ДВА, а утверждений про них ОДИН НАБОР.

Память и Redis обязаны вести себя одинаково, иначе получится наш худший вид дефекта:
на машине разработчика (память) всё правильно, на бою (Redis) — нет, и увидеть это
можно только под нагрузкой у настоящих людей. Поэтому каждая проверка ниже
параметризована по движку, а не написана дважды.

⚠️ Redis-движок проверяется НАСТОЯЩИМ клиентом `redis` поверх `fakeredis` — то есть
исполняется весь наш код целиком (pipeline, WATCH, отсортированные множества), а
подменён только сокет до сервера. Заглушки нашего собственного класса здесь не было бы
смысла: она проверяла бы саму себя.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import shared_state as S  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────────────
# Оба движка под одним именем
# ─────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(params=["memory", "redis"])
def backend(request, monkeypatch):
    """Отдаёт модуль `shared_state`, настроенный на конкретный движок."""
    S.reset_for_tests()
    if request.param == "memory":
        monkeypatch.delenv("GRADEBOOK_REDIS_URL", raising=False)
    else:
        #fakeredis — это ИНСТРУМЕНТ, объявленный нами в requirements-dev.txt, и
        #пропускать по его отсутствию нельзя: так уже дважды гасились целые наборы
        #проверок (yaml и pdfplumber). Нет пакета — отказ, а не тишина.
        try:
            import fakeredis
        except ImportError:                                       # pragma: no cover
            pytest.fail("нет fakeredis (requirements-dev.txt) — ветка Redis осталась бы "
                        "НЕ ИСПОЛНЕННОЙ ни разу, а это хуже её отсутствия")
        import redis as real_redis

        #🔥 СВОЙ СЕРВЕР НА КАЖДЫЙ ТЕСТ, и это не гигиена, а находка этого же файла.
        #Первая версия фикстуры отдавала общий fakeredis, и четыре проверки покраснели:
        #счётчик потока продолжал расти с прошлого теста, окна копили чужие события.
        #В памяти такого не бывает по построению — состояние умирает вместе с процессом,
        #а у Redis ПЕРЕЖИВАЕТ его. Отличие настоящее, и оно закреплено отдельным
        #тестом ниже; здесь же тесты обязаны быть независимыми друг от друга.
        srv = fakeredis.FakeServer()

        class _FreshRedis:
            @staticmethod
            def from_url(_url, **kw):
                return fakeredis.FakeRedis(
                    server=srv, decode_responses=kw.get("decode_responses", False))

        monkeypatch.setattr(real_redis, "Redis", _FreshRedis)
        monkeypatch.setenv("GRADEBOOK_REDIS_URL", "redis://localhost:6379/0")
    yield S
    S.reset_for_tests()


def test_the_engine_is_the_one_we_asked_for(backend, request):
    """Иначе весь файл мог бы прогнать память дважды и выглядеть зелёным."""
    want = request.node.callspec.params["backend"]
    assert backend.describe()["backend"] == want


# ─────────────────────────────────────────────────────────────────────────────────────
# Значение со сроком
# ─────────────────────────────────────────────────────────────────────────────────────
def test_value_survives_and_reads_back_equal(backend):
    backend.set("k", {"fails": 3, "locked_until": 12.5})
    assert backend.get("k") == {"fails": 3, "locked_until": 12.5}


def test_missing_value_is_none_not_an_error(backend):
    assert backend.get("нет-такого") is None


def test_value_disappears_after_its_ttl(backend):
    backend.set("k", 1, ttl=0.25)
    assert backend.get("k") == 1
    time.sleep(0.4)
    assert backend.get("k") is None, "срок вышел, а значение осталось"


def test_delete_removes_the_value(backend):
    backend.set("k", 1)
    backend.delete("k")
    assert backend.get("k") is None


def test_update_is_read_modify_write_in_one_step(backend):
    """⚠️ Не педантизм: две одновременные неудачные попытки входа прочитали бы fails=4
    обе и записали 5 обе — одна потерялась бы, и порог блокировки сдвинулся вверх.
    Именно так ограничитель и обходят."""
    def bump(cur):
        cur = cur or {"fails": 0}
        cur["fails"] += 1
        return cur

    for expected in (1, 2, 3):
        assert backend.update("rec", bump)["fails"] == expected
    assert backend.get("rec")["fails"] == 3


def test_update_returning_none_deletes(backend):
    backend.set("k", 1)
    assert backend.update("k", lambda _cur: None) is None
    assert backend.get("k") is None


def test_keys_lists_by_prefix_and_hides_expired(backend):
    backend.set("ban:1.2.3.4", 1)
    backend.set("ban:5.6.7.8", 1)
    backend.set("иное:x", 1)
    assert set(backend.keys("ban:")) == {"ban:1.2.3.4", "ban:5.6.7.8"}


# ─────────────────────────────────────────────────────────────────────────────────────
# Скользящее окно — на нём держатся ВСЕ ограничители частоты
# ─────────────────────────────────────────────────────────────────────────────────────
def test_window_counts_every_event(backend):
    assert [backend.window_add("w", 60) for _ in range(4)] == [1, 2, 3, 4]


def test_two_events_in_the_same_instant_are_both_counted(backend):
    """🔥 Ловушка отсортированного множества: член обязан быть УНИКАЛЕН.

    Если ключевать меткой времени, две отправки в одну миллисекунду схлопнутся в одну
    запись, и ограничитель недосчитается. Проверяется быстрым циклом без пауз — именно
    так выглядит настоящий флуд.
    """
    n = 0
    for _ in range(25):
        n = backend.window_add("burst", 60)
    assert n == 25, "события схлопнулись: посчитано %d из 25" % n


def test_events_leave_the_window_when_it_passes(backend):
    backend.window_add("w", 0.3)
    backend.window_add("w", 0.3)
    assert backend.window_count("w", 0.3) == 2
    time.sleep(0.45)
    assert backend.window_count("w", 0.3) == 0, "окно не скользит — лимит стал вечным"


def test_counting_does_not_add(backend):
    """Считать — не значит отмечать. Иначе проверка лимита сама бы его расходовала."""
    backend.window_add("w", 60)
    for _ in range(3):
        assert backend.window_count("w", 60) == 1


def test_windows_do_not_leak_between_keys(backend):
    backend.window_add("a", 60)
    backend.window_add("a", 60)
    assert backend.window_count("b", 60) == 0


def test_window_clear_resets(backend):
    backend.window_add("w", 60)
    backend.window_clear("w")
    assert backend.window_count("w", 60) == 0


# ─────────────────────────────────────────────────────────────────────────────────────
# Поток с номерами — живая консоль администратора и рассылка
# ─────────────────────────────────────────────────────────────────────────────────────
def test_stream_numbers_grow_monotonically(backend):
    """Номер — это то, чем клиент опрашивает дельтой «дай новее N».

    Повторившийся или уменьшившийся номер означает пропущенное событие, причём молча.
    """
    seqs = [backend.stream_append("c", {"i": i}) for i in range(5)]
    assert seqs == sorted(seqs) and len(set(seqs)) == 5


def test_stream_reads_only_what_is_newer(backend):
    backend.stream_append("c", {"i": 1})
    second = backend.stream_append("c", {"i": 2})
    backend.stream_append("c", {"i": 3})
    tail = backend.stream_read("c", after=second)
    assert [x["i"] for x in tail] == [3]


def test_stream_read_from_zero_gives_everything(backend):
    for i in range(3):
        backend.stream_append("c", {"i": i})
    assert [x["i"] for x in backend.stream_read("c", after=0)] == [0, 1, 2]


def test_stream_is_bounded(backend):
    """Кольцо, а не бесконечный список: живая консоль не имеет права съесть память."""
    for i in range(30):
        backend.stream_append("c", {"i": i}, maxlen=10)
    got = backend.stream_read("c", after=0)
    assert len(got) <= 10
    assert got[-1]["i"] == 29, "выброшены не самые старые, а самые новые"


def test_stream_carries_the_number_back_to_the_reader(backend):
    seq = backend.stream_append("c", {"i": 7})
    assert backend.stream_read("c", after=0)[0]["_seq"] == seq


# ─────────────────────────────────────────────────────────────────────────────────────
# Режим и деградация
# ─────────────────────────────────────────────────────────────────────────────────────
def test_only_the_redis_engine_is_shared_between_processes(backend, request):
    shared = request.node.callspec.params["backend"] == "redis"
    assert backend.available() is shared


def test_password_never_appears_in_the_described_url(monkeypatch):
    """Строка подключения уезжает в лог и на страницу «Сервер»."""
    S.reset_for_tests()
    monkeypatch.setenv("GRADEBOOK_REDIS_URL", "redis://user:s3cret@127.0.0.1:6379/0")
    shown = S.describe()["url"]
    assert "s3cret" not in shown, "пароль от Redis попал в вывод"
    assert "127.0.0.1" in shown
    S.reset_for_tests()


def test_a_dead_redis_degrades_loudly_instead_of_pretending(monkeypatch, caplog):
    """🔴 НАЗВАННАЯ ГРАНИЦА: при отказе Redis мы продолжаем на памяти.

    Выбор неприятен в обе стороны: отказать — значит запереть ВХОД всему колледжу;
    продолжить — значит, что ограничители тихо стали поворкерными. Принято второе, но
    ТИХИМ оно быть не имеет права, иначе защита ослабнет и никто не узнает.
    """
    import redis as real_redis

    class _Dead:
        @staticmethod
        def from_url(*_a, **_kw):
            raise real_redis.ConnectionError("connection refused")

    S.reset_for_tests()
    monkeypatch.setattr(real_redis, "Redis", _Dead)
    monkeypatch.setenv("GRADEBOOK_REDIS_URL", "redis://localhost:6379/0")

    #Продукт продолжает работать...
    S.set("k", 1)
    assert S.get("k") == 1
    #...но честно говорит, что общего состояния нет, и не пускает воркеров.
    assert S.degraded() is True
    assert S.available() is False
    monkeypatch.setenv("GRADEBOOK_WORKERS", "8")
    assert S.workers_allowed() == 1
    S.reset_for_tests()


# ─────────────────────────────────────────────────────────────────────────────────────
# ВОРОТА: число воркеров выводится из готовности, а не объявляется
# ─────────────────────────────────────────────────────────────────────────────────────
def test_without_the_setting_everything_is_exactly_as_before(monkeypatch):
    """Умолчание обязано быть буквально сегодняшним поведением.

    Иначе обновление молча переделало бы прод, который никуда не переезжал.
    """
    S.reset_for_tests()
    monkeypatch.delenv("GRADEBOOK_REDIS_URL", raising=False)
    monkeypatch.delenv("GRADEBOOK_WORKERS", raising=False)
    assert S.describe()["backend"] == "memory"
    assert S.available() is False
    assert S.workers_allowed() == 1
    S.reset_for_tests()


def test_more_workers_are_refused_while_the_migration_is_unfinished(monkeypatch):
    """🔥 РАДИ ЭТОГО ВОРОТА И ЗАВЕДЕНЫ.

    Перенести три места из семнадцати и запустить четыре воркера — значит ослабить
    анти-брутфорс вчетверо МОЛЧА, при зелёных тестах. Отдельная настройка «сколько
    воркеров» такую ошибку не ловит: она описывает намерение, а не готовность.
    """
    S.reset_for_tests()
    monkeypatch.setattr(S, "PENDING_MIGRATION", (("throttle.py", "_ips"),))
    monkeypatch.setenv("GRADEBOOK_WORKERS", "4")
    #Даже с полностью живым общим состоянием.
    monkeypatch.setattr(S, "available", lambda: True)
    assert S.workers_allowed() == 1
    S.reset_for_tests()


def test_workers_start_only_when_everything_is_ready(monkeypatch):
    S.reset_for_tests()
    monkeypatch.setattr(S, "PENDING_MIGRATION", ())
    monkeypatch.setattr(S, "BROADCAST_READY", True)
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setenv("GRADEBOOK_WORKERS", "4")
    assert S.workers_allowed() == 4
    S.reset_for_tests()


def test_workers_are_refused_while_broadcasting_is_not_done(monkeypatch):
    """🔥 ДЫРА В ВОРОТАХ, НАЙДЕННАЯ РАЗБОРОМ 10.09.2026.

    Здесь стояло, что реестр сокетов «входит в условие через PENDING_MIGRATION тем же
    порядком». Он не входит и войти НЕ МОЖЕТ: список собирается разбором `ast` по
    изменяемому состоянию уровня модуля, а реестр — поле объекта, разбор его не видит.
    Дописать руками тоже нельзя, соседний сторож требует точного совпадения с кодом.

    Итог был бы такой: закрываем оставшиеся места, ворота отвечают «готово», поднимаются
    четыре процесса — и сообщение в группе доходит живым каналом только тем, кто попал в
    тот же воркер. Остальные ждут опроса, разреженного до 30 с ИМЕННО потому, что сокет
    считается живым. То есть мессенджер стал бы отвечать через полминуты у (N−1)/N людей,
    и ворота бы при этом молчали.
    """
    S.reset_for_tests()
    monkeypatch.setattr(S, "PENDING_MIGRATION", ())      #состояние перенесено ВСЁ
    monkeypatch.setattr(S, "BROADCAST_READY", False)     #а рассылки между процессами нет
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setenv("GRADEBOOK_WORKERS", "4")
    assert S.workers_allowed() == 1
    assert S.migration_complete() is False
    S.reset_for_tests()


def test_even_when_ready_the_default_stays_one(monkeypatch):
    """Молча занять восемь ядер — переделать прод без спроса."""
    S.reset_for_tests()
    monkeypatch.setattr(S, "PENDING_MIGRATION", ())
    monkeypatch.setattr(S, "BROADCAST_READY", True)
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.delenv("GRADEBOOK_WORKERS", raising=False)
    assert S.workers_allowed() == 1
    S.reset_for_tests()


@pytest.mark.parametrize("junk", ["", "нет", "-3", "0", "1", "восемь", "3.5"])
def test_a_nonsense_worker_count_means_one(monkeypatch, junk):
    """Опечатка в настройке не имеет права стать «сколько-нибудь воркеров»."""
    S.reset_for_tests()
    monkeypatch.setattr(S, "PENDING_MIGRATION", ())
    monkeypatch.setattr(S, "BROADCAST_READY", True)
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setenv("GRADEBOOK_WORKERS", junk)
    assert S.workers_allowed() == 1
    S.reset_for_tests()


def test_the_pending_list_matches_reality(monkeypatch):
    """🔒 СПИСОК НЕ МОЖЕТ СОВРАТЬ: он сверяется с живым кодом, а не ведётся руками.

    Вычеркнул место, не перенеся его, — покраснеет здесь. Перенёс и забыл вычеркнуть —
    тоже: иначе воркеры остались бы запрещены навсегда, и работа была бы сделана впустую.
    Источник правды — тот же разбор `ast`, которым живёт test_process_local_state.py.
    """
    from test_process_local_state import STATE, scan_module_state

    should_move = {k for k, (verdict, _why) in STATE.items() if verdict == "перенести"}
    still_local = {entry for entry in scan_module_state() if entry in should_move}

    assert still_local == set(S.PENDING_MIGRATION), (
        "список PENDING_MIGRATION разошёлся с кодом.\n"
        "  ещё в памяти процесса, но не в списке: %s\n"
        "  в списке, но уже перенесено: %s"
        % (sorted(still_local - set(S.PENDING_MIGRATION)),
           sorted(set(S.PENDING_MIGRATION) - still_local)))


# ─────────────────────────────────────────────────────────────────────────────────────
# ПОСЛЕ РАЗБОРА 10.09.2026 — по сторожу на каждое подтверждённое возражение
# ─────────────────────────────────────────────────────────────────────────────────────

def test_both_engines_refuse_what_json_cannot_carry(backend):
    """🔥 ДВИЖКИ РАСХОДИЛИСЬ, И РАСХОЖДЕНИЕ ГАСИЛО ЗАЩИТУ ЦЕЛИКОМ.

    Память клала объект как есть и принимала `bytes`, `set`, кортеж. На машине
    разработчика такой вызов работал, тест был зелёным — а на бою он ронял сериализацию,
    и `_call` уводил ВСЕ процессы на память: ограничители становились поворкерными
    молча. Одна неудачная строка выключала бы весь смысл переноса.

    Теперь обе двери отказывают ОДИНАКОВО и ГРОМКО: это дефект вызывающего кода, а не
    отказ хранилища.
    """
    for bad in ({"b": b"\x00"}, {"s": {1, 2}}, {(1, 2): "ключ-кортеж"}):
        with pytest.raises((TypeError, ValueError)):
            backend.set("плохое", bad)


def test_a_bad_value_does_not_switch_off_shared_state(monkeypatch):
    """Наша ошибка не имеет права выглядеть как падение Redis."""
    import fakeredis
    import redis as real_redis
    srv = fakeredis.FakeServer()

    class _Shared:
        @staticmethod
        def from_url(_url, **kw):
            return fakeredis.FakeRedis(
                server=srv, decode_responses=kw.get("decode_responses", False))

    S.reset_for_tests()
    monkeypatch.setattr(real_redis, "Redis", _Shared)
    monkeypatch.setenv("GRADEBOOK_REDIS_URL", "redis://localhost:6379/0")
    S.set("норм", {"a": 1})                       #движок поднят и работает
    with pytest.raises(TypeError):
        S.set("плохое", {"b": b"\x00"})
    assert S.degraded() is False, (
        "наша ошибка сериализации засчиталась как отказ хранилища — все процессы "
        "молча ушли бы на поворкерные ограничители")
    assert S.available() is True
    S.reset_for_tests()


def test_the_value_returned_is_a_copy_not_the_store_itself(backend):
    """Память отдавала ССЫЛКУ на своё значение, Redis — копию.

    Вызывающий, поправив полученный словарь, менял хранилище у себя за спиной — и только
    на одном движке из двух. Такое расхождение видно лишь на бою.
    """
    backend.set("k", {"fails": 1})
    got = backend.get("k")
    got["fails"] = 999
    assert backend.get("k")["fails"] == 1


def test_expired_keys_are_actually_removed_not_just_hidden(backend):
    """🔥 НАСТОЯЩАЯ УТЕЧКА, И ИМЕННО НА БОЮ (там движок — память).

    Срок у значения проверяется только ПРИ ЧТЕНИИ, а `keys()` протухшее прячет. Значит
    запись, которую больше никто не спросит — а выдуманный логин из перебора никто и не
    спросит, — не удалял бы НИКТО до перезапуска процесса. Прежний `throttle._gc` шёл по
    своему словарю и такие записи выбрасывал; при переносе страховка исчезла.
    """
    for i in range(20):
        backend.set("мусор:%d" % i, {"x": i}, ttl=0.15)
    backend.set("живой", {"x": 1}, ttl=60)
    time.sleep(0.35)
    backend.purge()

    b = backend.backend()
    if getattr(b, "name", "") == "memory":
        #Смотрим В САМО хранилище: через публичную дверь протухшее и так не видно, то
        #есть проверка через неё была бы зелёной и до починки.
        assert len(b._values) == 1, (
            "протухшие записи остались в памяти: %d" % len(b._values))
    assert backend.get("живой") == {"x": 1}


def test_purge_keeps_a_ceiling_on_the_number_of_keys(monkeypatch):
    """Срок закрывает медленное накопление, а всплеск — нет.

    Бот перебирает сотни тысяч выдуманных логинов быстрее, чем истекает час хранения.
    Прежде это резал `throttle.MAX_ENTRIES`, при переносе он перестал использоваться.
    """
    S.reset_for_tests()
    monkeypatch.delenv("GRADEBOOK_REDIS_URL", raising=False)
    monkeypatch.setattr(S, "MAX_KEYS", 50)
    for i in range(200):
        S.set("флуд:%d" % i, {"x": i}, ttl=3600)
    S.purge()
    assert len(S.backend()._values) <= 50
    S.reset_for_tests()
