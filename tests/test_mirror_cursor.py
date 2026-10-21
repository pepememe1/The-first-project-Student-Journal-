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
    #Спуск по дереву Меркла: одна строка-сирота — ровно одна корзина, и у нас в ней на
    #строку больше, чем на бою.
    from app.routers.sync import digest_bucket
    assert res["mismatch"][0]["buckets"] == [(digest_bucket(_gid(sid="stud:stray")), 1, 0)], res


# ── дерево Меркла в отпечатке (исследование 20.10.2026) ──────────────────────────────
_ITEMS = [{"id": "stud:a|L1", "change_seq": 3}, {"id": "stud:b|L1", "change_seq": 5},
          {"id": "L7", "change_seq": 9}]


def test_root_hash_formula_is_unchanged_for_programs_already_in_the_field():
    """Корень — прежний `hash`. Программы 4.1 считают его СВОЕЙ вшитой формулой: смени её
    на сервере — и Сверщик у каждого из них краснел бы раз в час и гонял полную сверку."""
    from app.routers.sync import table_digest
    d = table_digest(_ITEMS, "id")
    assert d["hash"] == "e99dfb0eff8d25d41e33a170878a845e5ba8fe43bf2c8ca3a1bea67f0d3b399b"
    assert (d["count"], d["last"]) == (3, 9)


def test_one_changed_row_changes_exactly_one_bucket():
    from app.routers.sync import digest_bucket, diverged_buckets, table_digest
    base = table_digest(_ITEMS, "id")
    moved = table_digest([dict(_ITEMS[0], change_seq=4)] + _ITEMS[1:], "id")
    assert diverged_buckets(moved, base) == [(digest_bucket("stud:a|L1"), 1, 1)]
    assert diverged_buckets(base, table_digest(list(_ITEMS), "id")) == []
    #Корзины распределяются по хешу, а не по первой букве ключа: у ключей общие приставки.
    spread = {digest_bucket(f"stud:s{i}|L1") for i in range(200)}
    assert len(spread) == 16, spread


def test_old_side_without_buckets_says_nothing_instead_of_all_clear():
    """Сервер или программа до 20.10.2026 корзин не шлют — это «нечего сказать», а не
    «корзины совпали»: иначе пустой список читался бы как ложное «всё сошлось»."""
    from app.routers.sync import diverged_buckets, table_digest
    d = table_digest(_ITEMS, "id")
    old = {k: v for k, v in d.items() if k != "buckets"}
    assert diverged_buckets(d, old) == [] and diverged_buckets(old, d) == []


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


# ── бой начал нумерацию заново (восстановление из копии, 21.10.2026) ───────────────────
def _restored_after(copy_values, restored_values, epoch="E2"):
    prod = FakeProd()
    for v in copy_values:
        prod.put("grades", _grade_row(v, 0))
    local_mirror.mirror_once(client=prod)
    restored = FakeProd()
    restored.epoch = epoch
    for v in restored_values:
        restored.put("grades", _grade_row(v, 0))
    return restored


def test_restore_from_backup_with_new_epoch_brings_the_copy_back(copy):
    """🔥 Нашла модель синхронизации: копия видела «5» с номером 5, бой восстановили из
    копии, где у строки «3» с номером 2. Правило «не откатывать к меньшему номеру»
    оставляло «5» навсегда — сверка отчитывалась «строк 0»."""
    restored = _restored_after(("2", "3", "4", "4", "5"), ("2", "3"))
    res = local_mirror.mirror_once(client=restored)
    assert res["ok"] and res.get("full"), res
    assert _local() == ("3", 2), "копия осталась на нумерации до восстановления"


def test_restore_without_new_epoch_is_noticed_by_the_head(copy):
    """Метку базы сменить забыли: голова боя ниже нашего курсора — тот же случай."""
    restored = _restored_after(("2", "3", "4", "4", "5"), ("2", "3"), epoch="E1")
    local_mirror.mirror_once(client=restored)
    assert _local() == ("3", 2)


# ── карантин восстановления (21.10.2026, разбор Ярослава) ─────────────────────────────
def test_restore_puts_grades_the_server_lost_into_quarantine_and_can_return_them(copy):
    restored = _restored_after(("2", "3", "4", "4", "5"), ("2", "3"))
    local_mirror.mirror_once(client=restored)
    assert _local() == ("3", 2), "копия обязана сойтись с боем (§4.5)"
    lost = desk_outbox.quarantined("t1")
    assert [(q["row"]["grade"], q["prod_value"]) for q in lost] == [("5", "3")], lost
    assert desk_outbox.counts("t1")["restored_away"] == 1
    assert desk_outbox.release_quarantined(lost[0]["id"], "t1", "return")["ok"]
    sent = []

    def send(method, url, body, headers):
        sent.append(json.loads(body))
        return 200, {"updated_at": "p", "change_seq": 7}

    desk_outbox.flush(login="t1", auth=_auth, send=send)
    #«Вернуть» уходит со сверкой: база — номер строки боя, который человек видел рядом.
    assert sent and sent[0]["grade"] == "5" and sent[0]["base_seq"] == 2, sent
    assert desk_outbox.quarantined("t1") == []


def test_rows_that_survived_the_restore_are_not_quarantined(copy):
    restored = _restored_after(("2", "3"), ("2", "3"))
    local_mirror.mirror_once(client=restored)
    assert desk_outbox.quarantined("t1") == [] and desk_outbox.counts("t1")["restored_away"] == 0


def test_interrupted_restore_pass_keeps_the_original_value(copy):
    """Сверка оборвалась после первой страницы: строка в копии уже переписана боем.
    Следующая сверка снимет снимок с переписанной копии — исходник обязан пережить это."""
    prod = FakeProd()
    for v in ("4", "5"):
        prod.put("grades", _grade_row(v, 0))
    local_mirror.mirror_once(client=prod)

    class Flaky(FakeProd):
        broken = True

        def pull_page(self, cursor=0, limit=2000, scope="", epoch=""):
            if cursor > 0 and epoch == "E2" and self.broken:   #вторая страница сверки
                self.broken = False
                raise ConnectionError("обрыв посреди сверки")
            return super().pull_page(cursor, limit, scope, epoch)

    restored = Flaky()
    restored.epoch = "E2"
    restored.put("grades", _grade_row("3", 0))                 #наша строка — на 1-й странице
    for i in range(3):
        restored.put("grades", _grade_row("2", 0, sid=f"stud:x{i}"))
    assert not local_mirror.mirror_once(client=restored)["ok"]
    assert _local()[0] == "3", "первая страница уже легла в копию"
    local_mirror.mirror_once(client=restored)
    assert [q["row"]["grade"] for q in desk_outbox.quarantined("t1")] == ["5"]


def test_a_stale_copy_is_not_mistaken_for_a_loss(copy):
    """Полковник, 21.10.2026: ноутбук отстал, а бой восстановили из снимка, где строка
    НОВЕЕ копии. Это не потеря — в карантин нельзя, иначе «Вернуть» предложит устаревшее
    поверх чужой работы."""
    restored = _restored_after(("2", "4"), ("2", "4", "4", "5"))      #копия «4»@2, бой «5»@4
    local_mirror.mirror_once(client=restored)
    assert _local() == ("5", 4)
    assert desk_outbox.quarantined("t1") == []


def test_second_restore_keeps_its_own_original_while_the_first_is_undecided(copy):
    """Полковник: неразобранная запись первого восстановления не глушит снимок второго."""
    restored = _restored_after(("2", "3", "4", "4", "5"), ("2", "3"))
    local_mirror.mirror_once(client=restored)
    assert [q["row"]["grade"] for q in desk_outbox.quarantined("t1")] == ["5"]
    for v in ("4", "4", "2", "4"):                       #на бою снова правили: «4»@6
        restored.put("grades", _grade_row(v, 0))
    local_mirror.mirror_once(client=restored)
    again = FakeProd()
    again.epoch = "E3"
    again.put("grades", _grade_row("2", 0))             #второе восстановление: «2»@1
    local_mirror.mirror_once(client=again)
    assert sorted(q["row"]["grade"] for q in desk_outbox.quarantined("t1")) == ["4", "5"]

