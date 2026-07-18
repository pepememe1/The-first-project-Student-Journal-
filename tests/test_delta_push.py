"""
test_delta_push.py — push шлёт ДЕЛЬТУ, но не теряет правки.

Раньше каждый цикл уезжал полный снимок локальной базы: сервер применял только
изменившееся, зато трафик рос вместе с числом занятий/оценок. Теперь граница — метка
`_push_watermark`. Опасность дельты ровно одна и она дорогая: правка, не попавшая в
дельту, не уедет НИКОГДА (в отличие от pull, который лечится следующим полным циклом).
Поэтому тут проверяются именно страховки от потери, а не «экономия трафика».
"""
from datetime import datetime, timedelta, timezone

import data_store
import sync_engine
from core import DBManager


class FakeClient:
    """Запоминает всё, что ушло в push; pull отдаёт пустую дельту."""

    def __init__(self):
        self.pushes = []

    def push(self, payload):
        self.pushes.append(payload)

    def pull(self, since=""):
        return {"changes": {}, "server_time": "2026-01-01T00:00:00+00:00"}


def _reset_engine():
    sync_engine._session_full_pull_done = False
    sync_engine._session_full_push_done = False
    sync_engine._push_cycles = 0


def _add_lesson(lid: str, ts: str):
    conn = DBManager.get_conn()
    conn.execute("INSERT OR REPLACE INTO lessons (id,group_name,subject,type,number,topic,"
                 "date,updated_at,deleted) VALUES (?,'К-101','Математика','Лекция',1,'',"
                 "'2026-01-01',?,0)", (lid, ts))
    conn.commit()
    conn.close()


def _ids(payload) -> set:
    return {r["id"] for r in payload.get("lessons", [])}


def test_first_push_of_session_is_full(fresh_db):
    """Старт сессии — полный снимок: пока прога была закрыта, данные могли измениться
    мимо синка (восстановление из бэкапа, ручной импорт), и дельта их не увидела бы."""
    _reset_engine()
    _add_lesson("L1", "2020-01-01T00:00:00+00:00")     #заведомо старее любой метки
    data_store.set_push_watermark("2026-01-01T00:00:00+00:00")

    client = FakeClient()
    sync_engine.sync_once(client)
    assert "L1" in _ids(client.pushes[0]), "первый push сессии обязан быть полным"


def test_subsequent_push_sends_only_changed(fresh_db):
    """Второй цикл шлёт только новое — ради этого дельта и делалась."""
    _reset_engine()
    _add_lesson("L_OLD", "2020-01-01T00:00:00+00:00")
    client = FakeClient()
    sync_engine.sync_once(client)                       #полный: уехало всё

    _add_lesson("L_NEW", datetime.now(timezone.utc).isoformat())
    sync_engine.sync_once(client)
    sent = _ids(client.pushes[1])
    assert "L_NEW" in sent, "новая правка обязана уехать"
    assert "L_OLD" not in sent, "старое повторно слать незачем"


def test_edit_during_push_is_not_lost(fresh_db):
    """Гонка «правка ровно в момент push». Метка берётся ДО сбора данных, поэтому запись,
    появившаяся между сбором и сохранением метки, попадает в СЛЕДУЮЩУЮ дельту. При
    обратном порядке она провалилась бы в щель и не уехала никогда."""
    _reset_engine()
    client = FakeClient()
    sync_engine.sync_once(client)                       #полный push, метка выставлена

    #правка со «старой» меткой — как будто её записали, пока шёл предыдущий push
    _add_lesson("L_RACE", (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    sync_engine.sync_once(client)
    assert "L_RACE" in _ids(client.pushes[1]), "правка во время push не должна теряться"


def test_clock_moved_backwards_still_delivers(fresh_db):
    """Часы отошли назад (синхронизация времени, виртуалка после сна) — правка получает
    метку РАНЬШЕ watermark. Спасает лаг PUSH_SAFETY_LAG_S: последние минуты правок уезжают
    повторно. Push идемпотентен, повтор дешевле потери."""
    _reset_engine()
    client = FakeClient()
    sync_engine.sync_once(client)

    back = datetime.now(timezone.utc) - timedelta(seconds=sync_engine.PUSH_SAFETY_LAG_S - 30)
    _add_lesson("L_BACK", back.isoformat())
    sync_engine.sync_once(client)
    assert "L_BACK" in _ids(client.pushes[1]), "правка с отставшими часами обязана уехать"


def test_failed_push_keeps_watermark(fresh_db):
    """Push упал (сеть) — метку не двигаем, иначе правки этого цикла считались бы
    отправленными и пропали бы навсегда."""
    _reset_engine()
    sync_engine.sync_once(FakeClient())
    mark = data_store.get_push_watermark()

    class Broken(FakeClient):
        def push(self, payload):
            raise ConnectionError("сети нет")

    _add_lesson("L_PENDING", datetime.now(timezone.utc).isoformat())
    try:
        sync_engine.sync_once(Broken())
    except ConnectionError:
        pass
    assert data_store.get_push_watermark() == mark, "после падения метка не двигается"

    client = FakeClient()
    sync_engine.sync_once(client)
    assert "L_PENDING" in _ids(client.pushes[0]), "правка уезжает при следующем успехе"


def test_reset_forces_full_push(fresh_db):
    """После реконсиляции (кэш стёрт) «уже отправленному» верить нельзя — снова полный."""
    _reset_engine()
    sync_engine.sync_once(FakeClient())
    data_store.reset_synced_local_data()
    assert data_store.get_push_watermark() == "", "reset обязан сбросить метку push"
