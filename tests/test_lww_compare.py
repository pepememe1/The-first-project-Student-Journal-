"""
test_lww_compare.py — сравнение меток времени в LWW (`_ts_key` / `_should_apply`).

Эти две функции решают, ПЕРЕЗАПИСАТЬ ли локальную строку входящей, и через них проходит
каждая оценка, каждое занятие и каждое надгробие. Прямых тестов у них не было ни одного:
всё покрытие шло косвенно, через сценарии синка, — то есть ошибка в самом сравнении
выглядела бы не падением теста, а тихой потерей чужой правки у одного человека.

Проверяется СВОЙСТВО («новее побеждает», «надгробие не воскресает»), а не внутреннее
устройство ключа: ключ — деталь реализации, и переписать его должно быть можно, не
переписывая тесты.
"""
from datetime import datetime, timedelta, timezone

import sync_engine
from sync_engine import _should_apply, _ts_key

OLD = "2026-08-12T14:30:00.000000+00:00"
NEW = "2026-08-12T14:30:01.000000+00:00"


def test_later_timestamp_wins():
    assert _should_apply(NEW, OLD, False) is True
    assert _should_apply(OLD, NEW, False) is False


def test_equal_timestamp_applies_only_deletion():
    """Надгробие не должно «воскресать» из-за живого пуша с той же меткой.

    Обратная сторона того же правила: живая правка с РАВНОЙ меткой не применяется —
    иначе устаревший пуш, пришедший вторым, отменял бы уже принятое удаление."""
    assert _should_apply(OLD, OLD, True) is True
    assert _should_apply(OLD, OLD, False) is False


def test_z_suffix_and_offset_are_the_same_instant():
    """Ровно тот случай, ради которого метки РАЗБИРАЮТСЯ, а не сравниваются как текст:
    «Z» лексикографически больше «+00:00», и голое строковое сравнение сочло бы одну и
    ту же секунду более свежей — то есть перезаписало бы правку саму собой."""
    z = "2026-08-12T14:30:00.000000Z"
    off = "2026-08-12T14:30:00.000000+00:00"
    assert _ts_key(z) == _ts_key(off)
    assert _should_apply(z, off, False) is False
    assert _should_apply(off, z, False) is False


def test_dropped_microseconds_do_not_look_newer():
    """`datetime.isoformat()` выбрасывает микросекунды, когда они нулевые. Как текст
    «…:00+00:00» БОЛЬШЕ, чем «…:00.000001+00:00», хотя на деле оно на микросекунду
    старше."""
    round_second = "2026-08-12T14:30:00+00:00"
    a_bit_later = "2026-08-12T14:30:00.000001+00:00"
    assert _should_apply(a_bit_later, round_second, False) is True
    assert _should_apply(round_second, a_bit_later, False) is False


def test_naive_timestamp_is_read_as_utc():
    """Метка без зоны приходит от старых клиентов; считать её локальной означало бы
    сдвиг на часовой пояс — у нас это восемь часов, то есть заведомо неверный победитель."""
    naive = "2026-08-12T14:30:00.000000"
    aware = "2026-08-12T14:30:00.000000+00:00"
    assert _ts_key(naive) == _ts_key(aware)


def test_parsed_beats_garbage_even_when_garbage_sorts_higher():
    """Ключевой случай для сравнения кортежей целиком: строка «zzz» лексикографически
    больше любой ISO-метки, и сравнение по одному лишь значению отдало бы победу мусору.
    Вид метки стоит ПЕРВЫМ элементом пары именно поэтому."""
    garbage = "zzz-не-дата"
    assert _should_apply(OLD, garbage, False) is True
    assert _should_apply(garbage, OLD, False) is False


def test_empty_current_timestamp_never_blocks_incoming():
    """Пустая локальная метка (строка заведена до появления меток) не должна удерживать
    приезжающую правку — иначе такие строки застыли бы навсегда."""
    assert _should_apply(OLD, "", False) is True
    assert _should_apply("", "", True) is True


def test_two_unparsable_timestamps_compare_as_text_without_crashing():
    assert _should_apply("bbb", "aaa", False) is True
    assert _should_apply("aaa", "bbb", False) is False


def test_mixed_kinds_never_raise():
    """Сравнение float с str в Python — TypeError. Пара (вид, значение) обязана его
    исключать при ЛЮБОМ сочетании входов, иначе синк падал бы на одной битой строке."""
    samples = [OLD, NEW, "", "zzz", "2026-08-12", "2026-08-12T14:30:00Z", None]
    for inc in samples:
        for cur in samples:
            for deleted in (False, True):
                assert isinstance(_should_apply(inc, cur, deleted), bool)


def test_matches_the_explicit_branching_it_replaced():
    """Сравнение кортежей схлопнуто в одну строку (`a > b or (a == b and deleted)`) —
    раньше вид метки разбирался отдельной веткой. Здесь закреплено, что поведение от
    этого не изменилось НИ НА ОДНОМ сочетании: сокращение кода в LWW имеет право быть
    только буквально равносильным."""
    def previous_form(inc_ts, cur_ts, inc_deleted):
        a, b = _ts_key(inc_ts), _ts_key(cur_ts)
        if a[0] != b[0]:
            return a[0] > b[0]
        if a > b:
            return True
        return a == b and bool(inc_deleted)

    samples = [OLD, NEW, "", "zzz", "aaa", "2026-08-12T14:30:00Z",
               "2026-08-12T14:30:00+00:00", "2026-08-12T14:30:00.000001+00:00", None]
    for inc in samples:
        for cur in samples:
            for deleted in (False, True):
                assert _should_apply(inc, cur, deleted) == previous_form(inc, cur, deleted), (
                    f"расхождение на inc={inc!r} cur={cur!r} deleted={deleted}")


def test_now_is_utc_and_parses_back():
    """`_now()` — источник меток при локальной правке; она обязана быть разбираемой
    тем же `_ts_key`, иначе своя же запись попала бы в ветку «мусор»."""
    kind, value = _ts_key(sync_engine._now())
    assert kind == 1
    assert abs(value - datetime.now(timezone.utc).timestamp()) < 60


def test_a_day_apart_is_ordered_correctly():
    base = datetime(2026, 8, 12, 14, 30, tzinfo=timezone.utc)
    older = base.isoformat()
    newer = (base + timedelta(days=1)).isoformat()
    assert _should_apply(newer, older, False) is True
    assert _should_apply(older, newer, True) is False
