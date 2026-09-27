"""
verifier.py — «Сверщик»: сверка копии программы с боем. ТОЛЬКО ЧТЕНИЕ.

━━ ОТКУДА (идея Ярослава, 25.09.2026) ━━
Старый движок синка (`sync_engine.py`) когда-то сам сливал данные и сам решал конфликты.
С 25.09.2026 записью занимаются очередь досылки и зеркало, и движок остался без дела.
Ярослав предложил не выбросить его «дух», а дать ему новую роль: не писать ничего, а
проверять — сходится ли копия, по которой рисуется журнал, с тем, что на бою, — и
показывать это человеку значком «сверено». Мёртвый код слияния выведен (W-17), роль
живёт здесь.

━━ КАК СВЕРЯЕТ ━━
Бой отдаёт отпечаток того, что эта копия ОБЯЗАНА содержать (`GET /sync/digest`): по
каждой таблице — число строк области видимости, sha256 пар «ключ:номер изменения» и
последний номер, тронувший таблицу. Сверщик считает то же по копии ТОЙ ЖЕ функцией
(`app.routers.sync.table_digest`) и сравнивает только таблицы, которые не менялись после
курсора копии: иначе разница — это ещё не скачанная правка, а не расхождение.
Номера изменения в копии — боевые (правка в копии их не трогает), поэтому неотправленная
правка оценки сверку не ломает; строки, созданные офлайн и ещё не досланные, из сверки
исключаются по очереди досылки.

━━ ЧТО ДЕЛАЕТ ПРИ РАСХОЖДЕНИИ ━━
Ничего не правит сам — просит полную сверку зеркала (`desk_outbox.request_rebuild`) и
пишет в журнал, ЧТО разошлось. Решает по-прежнему бой: «сервер = истина» (§4.5).
⚠️ Таблица `config` не сверяется: рядом с боевыми ключами в ней лежат служебные метки
самой копии (курсор зеркала и т. п.), и сверка краснела бы всегда.
"""
import time
from datetime import datetime, timezone

import log

_log = log.get("verifier")

#Раз в час: сверка на бою дорогая (область видимости по всем таблицам), а расхождение
#без причины — событие редкое. Сервер и сам не пустит чаще (`DIGEST_LIMIT`).
VERIFY_EVERY_S = 3600
_SKIP_TABLES = frozenset({"config"})


def local_digest(names, protected=frozenset()) -> dict:
    """{таблица: {count, hash, last}} по копии — той же формулой, что на бою."""
    from app.models import SYNC_MODELS
    from app.routers.sync import table_digest
    from desktop import local_mirror
    db = local_mirror._local_session()
    try:
        out = {}
        for name in names:
            model = SYNC_MODELS.get(name)
            if model is None:
                continue
            pk = list(model.__table__.primary_key.columns)[0]
            rows = db.query(pk, model.change_seq).all()
            items = [{pk.name: k, "change_seq": s} for k, s in rows
                     if (name, k) not in protected]
            out[name] = table_digest(items, pk.name)
        return out
    finally:
        db.close()


def verify(client) -> dict:
    """Одна сверка. {ok, at, checked, skipped, mismatch, error}.

    `ok` — сверка ПРОШЛА (что-то было сравнено и всё сошлось). Не удалось сравнить ничего
    (копия отстаёт на каждой таблице) — это не «сверено», а «пока нечем проверить»."""
    at = datetime.now(timezone.utc).isoformat()
    result = {"ok": False, "at": at, "checked": [], "skipped": [], "mismatch": [],
              "error": ""}
    try:
        from desktop import desk_outbox, local_mirror
        srv = client.digest() or {}
        st = local_mirror.state()
        if not st.get("cursor"):
            result["error"] = "копия ещё не собрана"
            return result
        if srv.get("epoch") and srv.get("epoch") != st.get("epoch"):
            result["mismatch"].append({"table": "*", "why": "база на сервере сменилась"})
        elif srv.get("scope") and srv.get("scope") != st.get("scope"):
            result["mismatch"].append({"table": "*", "why": "изменилась область видимости"})
        if not result["mismatch"]:
            with desk_outbox.APPLY_LOCK:
                guard = desk_outbox.mirror_guard()
                cursor = local_mirror.state().get("cursor") or 0
                tables = srv.get("tables") or {}
                names = [n for n, t in tables.items()
                         if n not in _SKIP_TABLES and int((t or {}).get("last") or 0) <= cursor]
                mine = local_digest(names, protected=guard["keys"])
            for name, theirs in sorted(tables.items()):
                if name in _SKIP_TABLES:
                    continue
                if name not in mine:
                    result["skipped"].append(name)
                    continue
                ours = mine[name]
                if ours["hash"] == theirs.get("hash") and ours["count"] == theirs.get("count"):
                    result["checked"].append(name)
                else:
                    result["mismatch"].append({"table": name, "server": theirs.get("count"),
                                               "local": ours["count"]})
        if result["mismatch"]:
            _log.warning(f"[сверщик] копия расходится с сервером: {result['mismatch']} — "
                         "прошу полную сверку")
            desk_outbox.request_rebuild()
        result["ok"] = bool(result["checked"]) and not result["mismatch"]
    except Exception as e:      # noqa: BLE001 — сверка не имеет права ронять синк
        result["error"] = f"{type(e).__name__}: {e}"
        _log.info(f"[сверщик] сверка не выполнена: {result['error']}")
    return result


class Schedule:
    """Когда сверять: не чаще раза в `VERIFY_EVERY_S` и не во время досылки правок."""

    def __init__(self):
        self.last_try = 0.0
        self.last = {}

    def due(self) -> bool:
        return time.monotonic() - self.last_try >= VERIFY_EVERY_S

    def run(self, client) -> dict:
        self.last_try = time.monotonic()
        self.last = verify(client)
        return self.last
