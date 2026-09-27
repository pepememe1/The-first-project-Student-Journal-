"""
test_mirror_cursor.py — зеркало программы по НОМЕРУ изменения (26.09.2026, исследование
синка П7/П9/П16; серверная половина — `server/tests/test_sync_change_seq.py`).

━━ ЧТО ДЕРЖИТСЯ ━━
• проход страницами доводит копию до головы, курсор и протокол запоминаются;
• строка копии не откатывается страницей с МЕНЬШИМ номером (последняя увиденная боевая
  версия — закон);
• удалённое на бою уходит из копии, а строка с неотправленной правкой — нет;
• сброс от боя (сменилась область видимости) — полная сверка, и в её конце уходит всё
  неувиденное, кроме правок в очереди и того, что бой принял от нас уже после прохода;
• бой до 4.1 (ответ без курсора) — прежний путь по времени, и тогда полная сверка на
  старте остаётся (§4.5);
• очередь берёт базу правки номером из копии ещё при постановке («сирота» уходит с
  базой), разворачивает цепочку своих правок и не выдаёт строку без номера за «строки
  не было»;
• «Сверщик» сверяет отпечатки той же формулой, что бой, и при расхождении просит полную
  сверку.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН (`rev_mirror.py` захода): убрать правило «номер не
откатывается» — краснеет тест отката; не убирать неувиденное в конце полной сверки —
краснеет тест сброса; `_local_seq`, отдающий None, — краснеет тест сироты; убрать
`_mapped_base_seq` — краснеет тест цепочки; `0` вместо None для строки без номера —
краснеет тест старой копии; убрать `request_rebuild` у Сверщика — краснеет его тест.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from desktop import desk_outbox, local_api, local_mirror

SID = "stud:ivanov"
LESSON = "0a8f3c4e-1111-4222-8333-944455556666"


@pytest.fixture()
def copy(tmp_path, monkeypatch):
    """Очередь и зеркало на ВРЕМЕННОЙ копии со схемой сервера; вошедший — t1."""
    local_api.prepare_env()
    from app import db as _db
    from app.models import Base
    old_url, old_key = _db.DATABASE_URL, _db.DB_KEY
    _db.rebind(f"sqlite:///{(tmp_path / 'copy.db').as_posix()}", "")
    Base.metadata.create_all(_db.engine)
    monkeypatch.setattr(local_api, "_session_login", lambda: "t1")
    monkeypatch.setattr(local_mirror, "PAGE_LIMIT", 2)
    yield desk_outbox
    _db.rebind(old_url, old_key)


def _gid(sid=SID, lesson=LESSON):
    from app.models import grade_id
    return grade_id(sid, lesson)


def _grade_row(value, seq, sid=SID, lesson=LESSON):
    return {"id": _gid(sid, lesson), "student_f": "Иванов", "student_n": "Иван",
            "lesson_id": lesson, "grade": value, "device": "web",
            "updated_at": "2026-09-26T10:00:00+00:00", "deleted": False,
            "student_id": sid, "change_seq": seq}


class FakeProd:
    """Бой в миниатюре: строки с номерами, журнал удалений, область и метка базы."""

    def __init__(self):
        self.rows = {}              #(таблица, ключ) → строка
        self.deletes = []           #(номер, таблица, ключ)
        self.head = 0
        self.scope, self.epoch = "S1", "E1"

    def put(self, table, row):
        self.head += 1
        row = dict(row, change_seq=self.head)
        self.rows[(table, row.get("id") or row.get("key"))] = row
        return self.head

    def drop(self, table, key):
        self.head += 1
        self.rows.pop((table, key), None)
        self.deletes.append((self.head, table, key))

    def pull_page(self, cursor=0, limit=2000, scope="", epoch=""):
        base = {"head": self.head, "scope": self.scope, "epoch": self.epoch}
        if cursor > 0 and (scope != self.scope or epoch != self.epoch or cursor > self.head):
            return dict(base, reset="scope", cursor=0, more=True, changes={}, removed={})
        entries = sorted([(r["change_seq"], "row", t, r) for (t, _k), r in self.rows.items()
                          if cursor < r["change_seq"] <= self.head]
                         + [(s, "del", t, k) for s, t, k in self.deletes
                            if cursor < s <= self.head], key=lambda e: e[0])
        page = entries[:limit]
        upper = page[-1][0] if len(entries) > limit else self.head
        changes, removed = {}, {}
        for _s, kind, table, obj in page:
            if kind == "row":
                changes.setdefault(table, []).append(dict(obj))
            else:
                removed.setdefault(table, []).append(obj)
        return dict(base, cursor=upper, more=upper < self.head, changes=changes,
                    removed=removed)

    def digest(self):
        from app.routers.sync import table_digest
        tables = {}
        for name in ("grades", "lessons", "users"):
            items = [r for (t, _k), r in self.rows.items() if t == name]
            d = table_digest(items, "id")
            d["last"] = max([d["last"]] + [s for s, t, _k in self.deletes if t == name])
            tables[name] = d
        return {"head": self.head, "epoch": self.epoch, "scope": self.scope,
                "tables": tables}


def _local(table="grades", key=None):
    from app.db import SessionLocal
    from app.models import SYNC_MODELS
    db = SessionLocal()
    try:
        row = db.get(SYNC_MODELS[table], key or _gid())
        return None if row is None else (getattr(row, "grade", None), row.change_seq)
    finally:
        db.close()


def _put_local(value, seq, sid=SID, lesson=LESSON):
    from app.db import SessionLocal
    from app.models import Grade
    db = SessionLocal()
    try:
        data = _grade_row(value, seq, sid, lesson)
        db.merge(Grade(**data))
        db.commit()
    finally:
        db.close()


# ── проход по курсору ────────────────────────────────────────────────────────────────
def test_pages_bring_the_copy_to_the_head(copy):
    prod = FakeProd()
    for i in range(5):
        prod.put("grades", _grade_row(str(i % 5 + 1), 0, sid=f"stud:s{i}"))
    res = local_mirror.mirror_once(client=prod)
    assert res["ok"] and res.get("full"), res
    st = local_mirror.state()
    assert st["cursor"] == prod.head and st["protocol"] == "seq" and st["full_at"]
    assert all(_local(key=_gid(f"stud:s{i}")) is not None for i in range(5))
    #Дальше — дельта: новая правка доезжает, полной сверки больше нет.
    prod.put("grades", _grade_row("2", 0, sid="stud:s0"))
    res = local_mirror.mirror_once(client=prod)
    assert res["ok"] and not res.get("full") and _local(key=_gid("stud:s0"))[0] == "2"
    assert not local_mirror.full_at_start(), "с боем 4.1 полная сверка на старте не нужна"


def test_older_page_never_rolls_back_a_newer_row(copy):
    _put_local("5", 10)
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        local_mirror.apply_changes(db, {"grades": [_grade_row("3", 7)]})
        db.commit()
    finally:
        db.close()
    assert _local() == ("5", 10), "страница со старым номером откатила строку"


def test_removed_rows_leave_the_copy_but_pending_edits_stay(copy):
    prod = FakeProd()
    prod.put("grades", _grade_row("4", 0))
    prod.put("grades", _grade_row("3", 0, sid="stud:other"))
    local_mirror.mirror_once(client=prod)
    #По второй строке в очереди правка — её зеркало не трогает даже при удалении.
    body = {"surname": "Иванов", "name": "Иван", "lesson_id": LESSON, "grade": "5",
            "student_id": "stud:other"}
    copy.enqueue("t1", "POST", "/web/teacher/grade", "", json.dumps(body).encode(),
                 "application/json")
    prod.drop("grades", _gid())
    prod.drop("grades", _gid("stud:other"))
    assert local_mirror.mirror_once(client=prod)["ok"]
    assert _local() is None, "удалённую на бою строку оставили в копии"
    assert _local(key=_gid("stud:other")) is not None, "удаление смело неотправленную правку"


def test_scope_reset_full_pass_drops_unseen_rows_but_keeps_ours(copy):
    prod = FakeProd()
    prod.put("grades", _grade_row("4", 0))
    local_mirror.mirror_once(client=prod)
    #В копии лишнее: строка, которой на бою в этой области больше нет, и строка, которую
    #бой принял от нас уже ПОСЛЕ прохода (её номер выше курсора).
    _put_local("2", 1, sid="stud:gone")
    _put_local("5", 0, sid="stud:mine")
    from sqlalchemy import text
    with copy._tx() as c:
        c.execute(text("INSERT INTO desk_seq_versions (row_key, base_seq, prod_seq, "
                       "created_at) VALUES (:k, 0, 999, :t)"),
                  {"k": _gid("stud:mine"), "t": datetime.now(timezone.utc).isoformat()})
    prod.scope = "S2"
    res = local_mirror.mirror_once(client=prod)
    assert res["ok"] and res.get("full"), res
    assert _local(key=_gid("stud:gone")) is None, "полная сверка не убрала неувиденное"
    assert _local(key=_gid("stud:mine")) is not None, "сверка стёрла правку, принятую боем"
    assert _local() is not None
    assert local_mirror.state()["scope"] == "S2"


def test_row_deleted_and_recreated_in_one_page_survives_a_full_pass(copy):
    """Оценку стёрли на бою и поставили заново: в одной странице полной сверки едут и
    старое удаление, и новая строка. Строка обязана остаться — её номер новее удаления
    (дефект нашёл симулятор синка W-19: живая строка стиралась в конце сверки)."""
    prod = FakeProd()
    prod.put("grades", _grade_row("4", 0))
    prod.drop("grades", _gid())
    prod.put("grades", _grade_row("5", 0))
    res = local_mirror.rebuild(client=prod)
    assert res["ok"], res
    assert _local() is not None and _local()[0] == "5", "полная сверка стёрла живую оценку"


def test_legacy_server_keeps_the_old_time_path(copy):
    class Legacy:
        def pull_page(self, *a, **k):
            return {"server_time": "2026-09-26T10:00:00+00:00",
                    "changes": {"grades": [_grade_row("4", 0)]}}

        def pull(self, since=""):
            return self.pull_page()

    res = local_mirror.mirror_once(client=Legacy())
    assert res["ok"] and _local() is not None
    assert local_mirror.state()["protocol"] == "time"
    assert local_mirror.full_at_start(), "со старым боем сверка на старте обязана остаться"


def test_full_pass_is_due_again_after_a_week(copy):
    st = {"cursor": 5, "full_at": datetime.now(timezone.utc).isoformat()}
    assert not local_mirror.needs_full(st)
    st["full_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    assert local_mirror.needs_full(st)
    assert local_mirror.needs_full({"cursor": 0, "full_at": st["full_at"]})


# ── очередь: база номером ────────────────────────────────────────────────────────────
def _enqueue(value="5", sid=SID):
    body = {"surname": "Иванов", "name": "Иван", "lesson_id": LESSON, "grade": value,
            "student_id": sid}
    return desk_outbox.enqueue("t1", "POST", "/web/teacher/grade", "",
                               json.dumps(body).encode(), "application/json")


def _auth():
    return "https://prod.test", "prod-token", ""


def test_orphan_edit_goes_out_with_its_base_number(copy, monkeypatch):
    """W-14: процесс упал между постановкой и ответом обработчика — правка «сирота».
    Раньше она уходила без базы вовсе и затирала чужую правку на бою молча."""
    _put_local("2", 42)
    _enqueue("5")
    monkeypatch.setattr(desk_outbox, "ORPHAN_AFTER_S", -1)
    sent = []

    def send(method, url, body, headers):
        sent.append(json.loads(body))
        return 200, {"updated_at": "x", "change_seq": 50}

    assert desk_outbox.flush(login="t1", auth=_auth, send=send)["sent"] == 1
    assert sent[0].get("base_seq") == 42, sent


def test_chain_of_own_edits_maps_to_the_number_prod_gave_us(copy):
    _put_local("2", 42)
    s1 = _enqueue("5")
    desk_outbox.mark_ready(s1, {"id": _gid(), "base_updated_at": "t0", "base_seq": 42,
                                "updated_at": "L1"})
    s2 = _enqueue("4")
    desk_outbox.mark_ready(s2, {"id": _gid(), "base_updated_at": "L1", "base_seq": 42,
                                "updated_at": "L2"})
    sent, seqs = [], iter([50, 51])

    def send(method, url, body, headers):
        sent.append(json.loads(body))
        return 200, {"updated_at": "p", "change_seq": next(seqs)}

    assert desk_outbox.flush(login="t1", auth=_auth, send=send)["sent"] == 2
    assert [b["base_seq"] for b in sent] == [42, 50], \
        "вторая правка ушла с базой до нашей же первой — конфликт с самим собой"
    assert desk_outbox.mirror_guard()["sent_seq"][_gid()] == 51


def test_row_without_number_is_not_passed_off_as_missing(copy, monkeypatch):
    """Копия до 4.1: строка есть, номера нет. `0` значил бы «строки не было», и бой счёл
    бы любую правку конфликтом. Проверяется на «сироте» — там базу берёт сама очередь
    при постановке, без ответа обработчика."""
    _put_local("2", 0)
    _enqueue("5")
    monkeypatch.setattr(desk_outbox, "ORPHAN_AFTER_S", -1)
    sent = []

    def send(method, url, body, headers):
        sent.append(json.loads(body))
        return 200, {"updated_at": "p"}

    desk_outbox.flush(login="t1", auth=_auth, send=send)
    assert "base_seq" not in sent[0], sent


def test_absent_row_is_base_zero_for_an_orphan(copy, monkeypatch):
    """Строки в копии нет вовсе — это и есть «строки не было» (0), а не «неизвестно»."""
    _enqueue("5")
    monkeypatch.setattr(desk_outbox, "ORPHAN_AFTER_S", -1)
    sent = []

    def send(method, url, body, headers):
        sent.append(json.loads(body))
        return 200, {"updated_at": "p"}

    desk_outbox.flush(login="t1", auth=_auth, send=send)
    assert sent[0].get("base_seq") == 0, sent


# ── Сверщик ──────────────────────────────────────────────────────────────────────────
def test_verifier_confirms_a_matching_copy_and_flags_a_broken_one(copy):
    from sync import verifier
    prod = FakeProd()
    prod.put("grades", _grade_row("4", 0))
    local_mirror.mirror_once(client=prod)
    res = verifier.verify(prod)
    assert res["ok"] and "grades" in res["checked"], res
    assert not desk_outbox.take_rebuild_request()
    _put_local("5", 0, sid="stud:stray")        #строка, которой на бою нет
    res = verifier.verify(prod)
    assert not res["ok"] and res["mismatch"][0]["table"] == "grades", res
    assert desk_outbox.take_rebuild_request(), "расхождение нашли, а сверку не попросили"


# ── сторож головы ────────────────────────────────────────────────────────────────────
def test_head_watcher_wakes_the_cycle_when_prod_moved(copy, monkeypatch):
    from sync import sync_runner
    prod = FakeProd()
    prod.put("grades", _grade_row("4", 0))
    local_mirror.mirror_once(client=prod)
    mgr = sync_runner.SyncManager()
    mgr._running = True

    class Probe:
        token = "t"

        def head(self, after=-1, wait=0):
            mgr._running = False
            return {"head": after + 3}

    mgr._client = Probe()
    import threading
    stop = threading.Event()
    mgr._wake.clear()
    mgr._watch_head(stop)
    assert mgr._wake.is_set(), "бой ушёл вперёд, а цикл синка не разбудили"
