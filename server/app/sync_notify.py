"""
sync_notify.py — «толчок» для долгого опроса `/sync/head` (исследование синка W-20).

━━ ЗАЧЕМ ━━
Каждая программа спрашивала бой раз в 30 секунд «что нового» полным pull'ом: сервер
каждый раз считал область видимости преподавателя и выбирал строки, даже когда нового
не было ничего. Теперь программа ждёт на дешёвом `/sync/head?after=N&wait=20`: ответ
приходит сразу, как только на бою закоммитили правку строки синка, а в тишине — через
20 секунд, и полный pull идёт только когда номер головы действительно вырос.

━━ КАК БУДИМ ━━
• Сессия SQLAlchemy запоминает, что в ней менялись строки `SYNC_MODELS` (`before_flush`),
  и после commit будит ждущих (`after_commit`). Будильник потокобезопасен: писатели
  работают в пуле потоков, а ждущие — в цикле событий.
• Запись мимо ORM (сырой SQL, соседний процесс) будильник не заметит — поэтому ждущий
  ещё и сам перечитывает счётчик раз в `RECHECK_S`. Это страховка, а не основной путь.

⚠️ При нескольких процессах будильник срабатывает только в своём: соседние узнают о
правке перечитыванием раз в `RECHECK_S`. Задержка — секунды, а не потеря: счётчик в базе
общий. Поэтому переносить сюда `shared_state` не нужно (см. `PLAN-MULTIWORKER.md`).
⚠️ Ждущий НЕ держит соединение с базой: оно вернулось бы в пул только через 20 секунд, и
пятнадцать программ разом выбрали бы весь пул — встал бы весь сервер.
"""
import asyncio
import threading

#Как часто ждущий сам перечитывает счётчик (страховка от записи мимо ORM).
RECHECK_S = 2.0


class _Waker:
    """Будильник для ждущих в цикле событий; `poke` можно звать из любого потока."""

    def __init__(self):
        self._lock = threading.Lock()
        self._loop = None
        self._event = None

    def _bind(self):
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._loop is not loop or self._event is None:
                self._loop, self._event = loop, asyncio.Event()
            return self._event

    async def wait(self, timeout: float) -> None:
        event = self._bind()
        try:
            await asyncio.wait_for(event.wait(), timeout=max(0.0, timeout))
        except asyncio.TimeoutError:
            pass

    def poke(self) -> None:
        with self._lock:
            loop, event = self._loop, self._event
            if loop is None or event is None:
                return
            #Следующий ждущий заведёт свежее событие в своём цикле (`_bind`); текущие
            #проснутся от `set` ниже. Создавать Event здесь нельзя: мы не в цикле.
            self._event = None
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:          # цикл закрыт (остановка сервера) — будить некого
            pass


_waker = _Waker()
_installed = False


def poke() -> None:
    _waker.poke()


async def wait(timeout: float) -> None:
    await _waker.wait(timeout)


def install(session_factory) -> None:
    """Повесить слушатели на фабрику сессий (зовётся один раз из `routers/sync.py`)."""
    global _installed
    if _installed:
        return
    _installed = True
    from sqlalchemy import event
    from .models import SYNC_MODELS
    sync_classes = tuple(SYNC_MODELS.values())

    def _before_flush(session, _ctx, _instances):
        if session.info.get("_sync_dirty"):
            return
        for obj in (*session.new, *session.dirty, *session.deleted):
            if isinstance(obj, sync_classes):
                session.info["_sync_dirty"] = True
                return

    def _after_commit(session):
        if session.info.pop("_sync_dirty", False):
            poke()

    #⚠️ `after_soft_rollback` передаёт ДВА аргумента (сессию и откатываемую транзакцию).
    #С одним параметром слушатель падал TypeError на КАЖДОМ `db.rollback()` — то есть
    #любая ручка, откатывающая транзакцию в обработчике ошибки, отвечала бы 500 вместо
    #своего ответа. Поймал полный серверный прогон 27.09.2026 (`test_event_outbox.py`);
    #держит `test_sync_change_seq.py::test_rollback_survives_the_sync_notify_listener`.
    def _after_rollback(session, _previous_transaction):
        session.info.pop("_sync_dirty", None)

    event.listen(session_factory, "before_flush", _before_flush)
    event.listen(session_factory, "after_commit", _after_commit)
    event.listen(session_factory, "after_soft_rollback", _after_rollback)
