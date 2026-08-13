"""test_sync_reliability.py — безотказность синхронизации: три найденных дефекта и
два инварианта, на которых держится дельта.

Почему отдельным файлом, а не в test_delta_push.py: там проверяется, ЧТО уезжает
(состав дельты), здесь — что происходит, когда что-то идёт НЕ ТАК. Это разные вопросы,
и смешивать их значит потерять оба при первом же падении.

Каждый тест ниже закрывает поведение, которого раньше не было ВООБЩЕ, — то есть до
починки он краснел. Это проверено вручную откатом правки, а не предположено.
"""
import threading
import time

import pytest

from sync import sync_engine


class _FakeClient:
    """Клиент, которым можно управлять: что вернуть на push и сколько он длится."""

    def __init__(self, push_result=None, push_delay=0.0):
        self.push_result = push_result if push_result is not None else {}
        self.push_delay = push_delay
        self.pushes = 0
        self.pulls = 0

    def push(self, changes):
        self.pushes += 1
        if self.push_delay:
            time.sleep(self.push_delay)
        return dict(self.push_result)

    def pull(self, since=""):
        self.pulls += 1
        return {"server_time": "2026-08-13T12:00:00+00:00", "changes": {}}


@pytest.fixture(autouse=True)
def _clean_session(fresh_db):
    """Каждый тест — со своим чистым сеансом (иначе флаги протекают между тестами)."""
    sync_engine.reset_session_state()
    yield
    sync_engine.reset_session_state()


# ── 1. Отвергнутые сервером правки больше не исчезают молча ────────────────────────
def test_rejected_rows_are_surfaced_not_swallowed():
    """Сервер возвращает `rejected` — клиент ОБЯЗАН это заметить.

    Живой сценарий: админ снял у преподавателя назначение на предмет, пока тот работал
    офлайн. Push проходит с кодом 200, но часть строк сервер отвергает построчно. Раньше
    ответ push не читался вовсе: водяной знак уезжал вперёд, и отвергнутая оценка больше
    никогда не попадала в дельту — в журнале преподавателя она есть, на сервере её нет,
    и никакого следа об этом.
    """
    client = _FakeClient(push_result={"applied": {"grades": 2},
                                      "rejected": {"grades": 3}})
    assert sync_engine.sync_once(client) is True
    assert sync_engine.last_rejected() == {"grades": 3}


def test_clean_push_reports_nothing_rejected():
    """Обратная сторона: обычный успешный push НЕ должен поднимать ложную тревогу.

    Без этого теста сторож бесполезен — «всегда что-то отклонено» читается так же, как
    «никогда ничего не отклонено»."""
    client = _FakeClient(push_result={"applied": {"grades": 2}})
    assert sync_engine.sync_once(client) is True
    assert sync_engine.last_rejected() == {}


def test_rejection_is_forgotten_after_a_clean_cycle():
    """Отказ относится к ПОСЛЕДНЕМУ push, а не копится вечно: админ вернул назначение —
    следующий цикл прошёл чисто, и индикатор обязан погаснуть."""
    sync_engine.sync_once(_FakeClient(push_result={"rejected": {"grades": 1}}))
    assert sync_engine.last_rejected()
    sync_engine.sync_once(_FakeClient(push_result={"applied": {"grades": 1}}))
    assert sync_engine.last_rejected() == {}


# ── 2. Два цикла одновременно не пересекаются ──────────────────────────────────────
def test_second_cycle_does_not_run_while_first_is_in_flight():
    """Замок сеанса: пока один цикл в середине push, второй НЕ лезет туда же.

    Это не теория: `sync_runner.flush_now()` (закрытие программы) зовёт цикл из другого
    потока, чем фоновый `_loop`. Общая `requests.Session` не потокобезопасна, а водяной
    знак, сдвинутый чужим потоком, уводит правки из дельты навсегда.
    """
    slow = _FakeClient(push_delay=0.6)
    done = []

    t = threading.Thread(target=lambda: done.append(sync_engine.sync_once(slow)))
    t.start()
    time.sleep(0.15)                     #дать первому потоку зайти внутрь push
    #Второй заход с конечным ожиданием — ровно как на закрытии программы.
    assert sync_engine.sync_once(_FakeClient(), wait=0.05) is False, (
        "второй цикл пролез внутрь занятого — замок не работает")
    t.join(timeout=5)
    assert done == [True]
    assert slow.pushes == 1, "медленный цикл не должен был выполниться дважды"


def test_lock_is_released_even_if_cycle_raises():
    """Упавший цикл обязан отпустить замок — иначе одна сетевая ошибка вешает
    синхронизацию до перезапуска программы (замок не отдал бы никто)."""
    class _Boom(_FakeClient):
        def push(self, changes):
            raise RuntimeError("сеть отвалилась")

    with pytest.raises(RuntimeError):
        sync_engine.sync_once(_Boom())
    #Замок свободен — следующий цикл проходит штатно.
    assert sync_engine.sync_once(_FakeClient()) is True


# ── 3. Водяной знак не уезжает вперёд при неудачном push ───────────────────────────
def test_watermark_stays_put_when_push_fails():
    """Push упал — метка НЕ двигается, иначе собранные правки выпали бы из дельты.

    Направление отказа выбрано осознанно: «отправить повторно» дёшево и безопасно
    (сервер делает upsert по ключу), «пропустить» — потеря оценки."""
    from data.data_store import get_push_watermark, set_push_watermark

    set_push_watermark("2026-01-01T00:00:00+00:00")

    class _Boom(_FakeClient):
        def push(self, changes):
            raise RuntimeError("обрыв")

    with pytest.raises(RuntimeError):
        sync_engine.sync_once(_Boom())
    assert get_push_watermark() == "2026-01-01T00:00:00+00:00"


def test_watermark_moves_after_successful_push():
    """Обратный тест: при успехе метка обязана сдвинуться — иначе дельта не сужается
    никогда и «дельта-push» остаётся полным снимком под другим именем."""
    from data.data_store import get_push_watermark, set_push_watermark

    set_push_watermark("2026-01-01T00:00:00+00:00")
    assert sync_engine.sync_once(_FakeClient()) is True
    assert get_push_watermark() != "2026-01-01T00:00:00+00:00"


def test_unreadable_table_does_not_move_the_watermark(monkeypatch):
    """Коллектор упал → метка НЕ двигается, даже если push прошёл успешно.

    Нашлось адверсариальным ревью, а не тестом, и это показательно: шесть коллекторов
    ставили флаг сами, а седьмой (`users`) — нет, потому что защита была расписана по
    семи местам вместо одного. При залоченной базе `users` отдавал пустой список, push
    считался успешным, метка уезжала — и заведённый офлайн студент, переименованный
    преподаватель и надгробие удалённого не уезжали до полного снимка (до 20 циклов).

    Проверяем ИМЕННО users: остальные шесть и раньше были прикрыты, а этот — нет.
    Обратную сторону («при исправном чтении метка обязана сдвинуться») держит
    `test_watermark_moves_after_successful_push` выше — без неё эта проверка была бы
    зелёной и при реализации «никогда не двигать метку»."""
    from data.data_store import get_push_watermark, set_push_watermark

    def boom():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(sync_engine, "_collect_users", boom)
    set_push_watermark("2026-01-01T00:00:00+00:00")

    assert sync_engine.sync_once(_FakeClient()) is True, (
        "одна нечитаемая таблица не должна лишать человека синхронизации целиком")
    assert get_push_watermark() == "2026-01-01T00:00:00+00:00", (
        "метка уехала при непрочитанной таблице — правки выпадут из дельты молча")


# ── 3.1 Часы ушли назад — дельте верить нельзя ─────────────────────────────────────
def _spy_on_collect(monkeypatch) -> list:
    """Записывает, с какой границей звали collect_local: "" — полный снимок, иначе дельта."""
    seen: list = []
    real = sync_engine.collect_local

    def spy(since=""):
        seen.append(since)
        return real(since)

    monkeypatch.setattr(sync_engine, "collect_local", spy)
    return seen


def test_clock_running_backwards_forces_a_full_push(monkeypatch):
    """Водяной знак оказался ПОЗЖЕ текущей границы — значит часы отошли назад, и правки
    «откатившегося» промежутка в дельту не попадут. Единственный безопасный ответ —
    полный снимок.

    Почему это не покрывалось PUSH_SAFETY_LAG_S: тот сдвигает границу на две минуты, то
    есть спасает только от микро-регрессий. Ноутбук, проснувшийся с отставшими на час
    часами, отдал бы дельту, из которой правки этого часа выпали молча."""
    from data.data_store import set_push_watermark

    seen = _spy_on_collect(monkeypatch)
    sync_engine.sync_once(_FakeClient())          #первый цикл сеанса и так полный
    set_push_watermark("2099-01-01T00:00:00+00:00")   #метка из будущего = часы ушли назад
    sync_engine.sync_once(_FakeClient())
    assert seen[-1] == "", (
        "часы ушли назад, а push собрался дельтой — правки промежутка не уедут "
        f"до ближайшего полного снимка (звали collect_local с {seen[-1]!r})")


def test_normal_clock_still_sends_a_delta(monkeypatch):
    """ОБРАТНЫЙ тест: при исправных часах push обязан остаться ДЕЛЬТОЙ.

    Без него проверка выше зелёная при реализации «всегда слать полный снимок» — то есть
    не доказывает ничего, а дельта-push тихо превращается в полный под другим именем."""
    from data.data_store import set_push_watermark

    seen = _spy_on_collect(monkeypatch)
    sync_engine.sync_once(_FakeClient())
    set_push_watermark("2026-01-01T00:00:00+00:00")   #обычная метка в прошлом
    sync_engine.sync_once(_FakeClient())
    assert seen[-1] == "2026-01-01T00:00:00+00:00", (
        f"часы исправны, а уехал полный снимок (звали collect_local с {seen[-1]!r})")


# ── 4. Инвариант формата метки времени ─────────────────────────────────────────────
def test_timestamp_format_is_offset_not_z():
    """Метки времени ОБЯЗАНЫ иметь смещение «+00:00», а не суффикс «Z».

    Зачем пиннить очевидное: серверный `/sync/pull` фильтрует дельту СТРОКОВЫМ
    сравнением (`updated_at >= since`), и это работает ровно потому, что обе стороны
    печатают время одной функцией. Переход на «Z» — типичная «модернизация» — сломал бы
    сравнение внутри одной секунды: 'Z' (0x5A) больше '+' (0x2B) и больше '.' (0x2E),
    поэтому метка с «Z» отсекла бы записи той же секунды, записанные в прежнем формате.
    Потеря была бы редкой, тихой и невоспроизводимой — худший вид.
    """
    ts = sync_engine._now()
    assert ts.endswith("+00:00"), ts
    assert "Z" not in ts


def test_parsed_comparison_survives_mixed_formats():
    """А там, где сравнение НАШЕ (дельта push), формат не должен решать ничего:
    `_ts_key` разбирает метку, поэтому «Z», «+00:00» и отброшенные микросекунды —
    один и тот же момент."""
    a = sync_engine._ts_key("2026-08-13T12:00:00Z")
    b = sync_engine._ts_key("2026-08-13T12:00:00+00:00")
    c = sync_engine._ts_key("2026-08-13T12:00:00.000000+00:00")
    assert a == b == c
