"""
test_desk_sync_races.py — зеркало и очередь досылки программы не портят друг другу копию,
а одна «ядовитая» правка не держит очередь (исследование синка 25.09.2026, находки W-07,
W-08, W-10).

━━ ЧТО ЗДЕСЬ ДЕРЖИТСЯ ━━
Зеркало качает снимок боя по сети (до 45 с) и применяет его к копии, а очередь в то же
время досылает правки и принимает новые. Общего замка и правил между ними не было, и три
перемежения портили копию:
  • досылка проходила, пока зеркало качало снимок, — и снимок, снятый ДО неё, откатывал
    только что отправленную оценку: «сохранил, а она вернулась»; следующая правка той же
    клетки уходила со старой версией и получала конфликт с самой собой;
  • правка вставала в очередь и ложилась в копию уже после того, как зеркало посчитало
    защищённые строки, — и зеркало тут же её затирало;
  • два прохода зеркала разом: более старый снимок применялся последним.
Плюс W-10: правка, на которой сервер падал ошибкой, останавливала очередь НАВСЕГДА, и
W-08: занятие из программы досылалось без периода, которым его проштамповала копия.

Обратный ход (проверен): убрать правило `sent` из `apply_changes` — краснеет
`test_snapshot_taken_before_the_send_does_not_roll_back_the_grade`; убрать `in_flight` —
`test_edit_in_flight_without_a_key_postpones_the_snapshot`; `row_key_hint`, отдающий '', —
`test_key_is_known_at_enqueue_so_the_rest_still_applies`; снять замок с `enqueue` —
`test_enqueue_waits_while_the_mirror_applies`; убрать сверку с водяным знаком —
`test_older_snapshot_never_overwrites_a_newer_one`; убрать условие `sent` в `rebuild` —
`test_full_resync_keeps_a_lesson_sent_after_the_snapshot`; вернуть прежнее ожидание через
`wait_for(run_in_threadpool(...))` — `test_save_waits_for_the_mirror_no_longer_than_promised`
(пять сохранений заводят пять параллельных проходов зеркала).
"""
import asyncio
import json
import threading
import time

import pytest

from desktop import desk_outbox, local_api, local_mirror

SID = "stud:ivanov"
LESSON = "0a8f3c4e-1111-4222-8333-944455556666"
T0 = "2026-09-25T10:00:00+00:00"          #боевая версия ДО нашей правки
SNAP = "2026-09-25T10:03:00+00:00"        #водяной знак снимка, снятого ДО досылки
LOCAL = "2026-09-25T10:04:00.123+00:00"   #метка, которую поставила копия (часы ПК)
#Период — ИЗ ПРОДУКТА, а не числом: учебный год, записанный литералом, протухает
#1 сентября (сторож `test_no_calendar_bound_tests.py`). Здесь значение любое — важно
#лишь, что досылка несёт тот период, который проставила копия.
from data.terms import current_term as _current_term  # noqa: E402
TERM_YEAR = _current_term()[0]
T1 = "2026-09-25T10:05:00+00:00"          #боевая версия, которую бой дал НАШЕЙ правке
T2 = "2026-09-25T10:20:00+00:00"          #позже поправили на сайте


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
    yield desk_outbox
    _db.rebind(old_url, old_key)


def _gid(sid=SID):
    from app.models import grade_id
    return grade_id(sid, LESSON)


def _put_grade(value, ts):
    from app.db import SessionLocal
    from app.models import Grade
    db = SessionLocal()
    try:
        db.merge(Grade(id=_gid(), student_f="Иванов", student_n="Иван", lesson_id=LESSON,
                       grade=value, device="web", updated_at=ts, deleted=False,
                       student_id=SID))
        db.commit()
    finally:
        db.close()


def _grade(gid=None):
    from app.db import SessionLocal
    from app.models import Grade
    db = SessionLocal()
    try:
        row = db.get(Grade, gid or _gid())
        return None if row is None else (row.grade, row.updated_at)
    finally:
        db.close()


def _grade_item(value, ts, sid=SID, surname="Иванов", name="Иван"):
    return {"id": _gid(sid), "student_f": surname, "student_n": name, "lesson_id": LESSON,
            "grade": value, "device": "web", "updated_at": ts, "deleted": False,
            "student_id": sid}


def _enqueue_grade(ob, value="5"):
    body = {"surname": "Иванов", "name": "Иван", "lesson_id": LESSON, "grade": value,
            "student_id": SID}
    return ob.enqueue("t1", "POST", "/web/teacher/grade", "", json.dumps(body).encode(),
                      "application/json")


def _lesson_rows():
    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        return {r.id for r in db.query(Lesson).all()}
    finally:
        db.close()


def _put_lesson(lid, ts):
    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        db.merge(Lesson(id=lid, group_name="К-24", subject="Математика", type="Практика",
                        number=1, topic="", date="", retake_date="", hour=0, extra={},
                        year=TERM_YEAR, semester=1, subgroup=0, updated_at=ts,
                        deleted=False))
        db.commit()
    finally:
        db.close()


def _watermark():
    db = local_mirror._local_session()
    try:
        return local_mirror._get_watermark(db)
    finally:
        db.close()


class _Client:
    """Подменный бой для зеркала: `during_pull` исполняется, пока «идёт сеть»."""

    def __init__(self, payload, during_pull=None):
        self.payload, self.during_pull = payload, during_pull

    def pull(self, since=""):
        if self.during_pull:
            self.during_pull()
        return self.payload


def _auth():
    return "https://prod.test", "prod-token", ""


def _send_ok(ts, calls=None):
    def send(method, url, body, headers):
        if calls is not None:
            calls.append(json.loads(body or b"{}"))
        return 200, {"updated_at": ts}
    return send


def _grade_sent_while_the_mirror_downloads(ob):
    """Копия: «5» поставлена поверх боевой «2»; досылка проходит, пока зеркало качает."""
    _put_grade("2", T0)
    seq = _enqueue_grade(ob, "5")
    _put_grade("5", LOCAL)                      #обработчик копии записал правку
    ob.mark_ready(seq, {"id": _gid(), "base_updated_at": T0, "updated_at": LOCAL})

    def send_during_pull():
        assert ob.flush(login="t1", auth=_auth, send=_send_ok(T1))["sent"] == 1

    return send_during_pull


# ── W-07: гонки зеркала и очереди ────────────────────────────────────────────────────
def test_snapshot_taken_before_the_send_does_not_roll_back_the_grade(copy):
    during = _grade_sent_while_the_mirror_downloads(copy)
    snapshot = {"server_time": SNAP, "changes": {"grades": [_grade_item("2", T0)]}}
    res = local_mirror.mirror_once(client=_Client(snapshot, during))
    assert res["ok"], res
    assert _grade()[0] == "5", "снимок, снятый ДО досылки, откатил отправленную оценку"


def test_the_accepted_version_and_later_edits_still_arrive(copy):
    """Правило «не откатывать» не имеет права глушить законные обновления с боя."""
    during = _grade_sent_while_the_mirror_downloads(copy)
    local_mirror.mirror_once(client=_Client(
        {"server_time": SNAP, "changes": {"grades": [_grade_item("2", T0)]}}, during))
    local_mirror.mirror_once(client=_Client(
        {"server_time": T1, "changes": {"grades": [_grade_item("5", T1)]}}))
    assert _grade() == ("5", T1), "копия не получила боевую версию своей же правки"
    local_mirror.mirror_once(client=_Client(
        {"server_time": T2, "changes": {"grades": [_grade_item("3", T2)]}}))
    assert _grade() == ("3", T2), "правка с сайта после нашей не доехала до копии"


def test_edit_in_flight_without_a_key_postpones_the_snapshot(copy):
    """Итоговая без периода: ключ строки узнаем только из ответа обработчика. Пока он не
    пришёл, снимок не применяется вовсе — и метка дельты стоит на месте."""
    body = {"surname": "Иванов", "name": "Иван", "subject": "Математика", "group": "К-24",
            "grade": "5", "student_id": SID}
    copy.enqueue("t1", "POST", "/web/teacher/term-grade", "", json.dumps(body).encode(),
                 "application/json")
    res = local_mirror.mirror_once(client=_Client(
        {"server_time": SNAP, "changes": {"grades": [_grade_item("2", T0)]}}))
    assert res.get("deferred"), res
    assert _grade() is None and _watermark() == "", "снимок применился мимо правки в полёте"


def test_key_is_known_at_enqueue_so_the_rest_still_applies(copy):
    """Оценка с id студента защищена ключом ещё ДО ответа обработчика: зеркало обходит
    ровно её строку, а остальное применяет, не откладывая весь снимок."""
    _put_grade("5", LOCAL)
    _enqueue_grade(copy, "5")                   #ответа обработчика ещё нет
    other = _grade_item("4", T0, sid="stud:petrov", surname="Петров", name="Пётр")
    res = local_mirror.mirror_once(client=_Client(
        {"server_time": SNAP, "changes": {"grades": [_grade_item("2", T0), other]}}))
    assert res["ok"] and not res.get("deferred"), res
    assert _grade()[0] == "5", "зеркало затёрло правку, стоящую в очереди"
    assert _grade(other["id"]) == ("4", T0), "соседняя строка снимка не применилась"


def test_enqueue_waits_while_the_mirror_applies(copy):
    done = threading.Event()

    def worker():
        _enqueue_grade(copy, "5")
        done.set()

    with copy.APPLY_LOCK:
        threading.Thread(target=worker, daemon=True).start()
        assert not done.wait(0.3), "правка встала в очередь посреди применения снимка"
    assert done.wait(5), "после применения снимка правка так и не встала в очередь"


def test_older_snapshot_never_overwrites_a_newer_one(copy):
    """Два прохода зеркала разом: второй успел применить более свежий снимок, пока
    первый ещё качал свой. Более старый не применяется вовсе."""
    newer = {"server_time": "2026-09-25T11:00:00+00:00",
             "changes": {"grades": [_grade_item("3", "2026-09-25T10:59:00+00:00")]}}

    def other_pass_finishes_first():
        assert local_mirror.mirror_once(client=_Client(newer))["ok"]

    res = local_mirror.mirror_once(client=_Client(
        {"server_time": SNAP, "changes": {"grades": [_grade_item("2", T0)]}},
        other_pass_finishes_first))
    assert res.get("superseded"), res
    assert _grade()[0] == "3", "старый снимок откатил более свежий"


def test_full_resync_keeps_a_lesson_sent_after_the_snapshot(copy):
    """Полная сверка не удаляет занятие, которое бой принял от нас уже ПОСЛЕ снятия
    снимка, — но настоящий призрак (на бою его нет и не было) убирает, как и должна."""
    _put_lesson(LESSON, LOCAL)
    _put_lesson("ghost-lesson", T0)
    seq = copy.enqueue("t1", "POST", "/web/teacher/lesson", "",
                       json.dumps({"group": "К-24", "subject": "Математика",
                                   "type": "Практика", "id": LESSON}).encode(),
                       "application/json")
    copy.mark_ready(seq, {"id": LESSON, "updated_at": LOCAL, "base_updated_at": ""})

    def send_during_pull():
        assert copy.flush(login="t1", auth=_auth, send=_send_ok(T1))["sent"] == 1

    res = local_mirror.rebuild(client=_Client(
        {"server_time": SNAP, "changes": {"lessons": []}}, send_during_pull))
    assert res["ok"], res
    rows = _lesson_rows()
    assert LESSON in rows, "сверка удалила занятие, досланное после снятия снимка"
    assert "ghost-lesson" not in rows, "сверка перестала убирать настоящие призраки"


# ── W-08: период при досылке ─────────────────────────────────────────────────────────
def test_replay_carries_the_term_the_copy_stamped(copy):
    seq = copy.enqueue("t1", "POST", "/web/teacher/lesson", "",
                       json.dumps({"group": "К-24", "subject": "Математика",
                                   "type": "Практика", "id": LESSON}).encode(),
                       "application/json")
    copy.mark_ready(seq, {"id": LESSON, "updated_at": LOCAL, "base_updated_at": "",
                          "year": TERM_YEAR, "semester": 1})
    body = {"surname": "Иванов", "name": "Иван", "subject": "Математика", "group": "К-24",
            "grade": "5", "student_id": SID, "year": TERM_YEAR, "semester": 2}
    seq2 = copy.enqueue("t1", "POST", "/web/teacher/term-grade", "",
                        json.dumps(body).encode(), "application/json")
    copy.mark_ready(seq2, {"id": "x", "updated_at": LOCAL, "base_updated_at": "",
                           "year": TERM_YEAR, "semester": 1})
    calls = []
    copy.flush(login="t1", auth=_auth, send=_send_ok(T1, calls))
    assert (calls[0].get("year"), calls[0].get("semester")) == (TERM_YEAR, 1), (
        "создание занятия ушло на бой без периода — бой проштамповал бы его своим")
    assert calls[1]["semester"] == 2, "период, названный клиентом, перезаписывать нельзя"


# ── W-10: ядовитая правка ─────────────────────────────────────────────────────────────
def _two_grades(ob):
    a = ob.enqueue("t1", "POST", "/web/teacher/grade", "", b'{"grade": "5"}',
                   "application/json")
    ob.mark_ready(a, {"id": "G-poison", "base_updated_at": T0, "updated_at": LOCAL})
    b = ob.enqueue("t1", "POST", "/web/teacher/grade", "", b'{"grade": "4"}',
                   "application/json")
    ob.mark_ready(b, {"id": "G-fine", "base_updated_at": T0, "updated_at": LOCAL})
    return a, b


def _time_passes(ob):
    from sqlalchemy import text
    with ob._tx() as c:
        c.execute(text("UPDATE desk_outbox SET next_at = 0"))


def _answer_by_grade(bad_status, calls):
    def send(method, url, body, headers):
        data = json.loads(body or b"{}")
        calls.append(data["grade"])
        return (bad_status, {"detail": "boom"}) if data["grade"] == "5" else (200, {"updated_at": T1})
    return send


def test_poisoned_edit_is_set_aside_and_the_queue_moves_on(copy):
    a, _b = _two_grades(copy)
    calls = []
    send = _answer_by_grade(500, calls)
    res = copy.flush(login="t1", auth=_auth, send=send)
    assert res["stopped"] == "server 500" and calls == ["5"], res
    #Пауза перед повтором: раньше срока правку не шлём и очередь не перескакиваем.
    res = copy.flush(login="t1", auth=_auth, send=send)
    assert res["stopped"] == "waiting" and calls == ["5"], res
    for _ in range(copy.MAX_SERVER_ERRORS - 1):
        _time_passes(copy)
        res = copy.flush(login="t1", auth=_auth, send=send)
    assert res["rejected"] == 1 and res["sent"] == 1, res
    assert calls.count("5") == copy.MAX_SERVER_ERRORS and calls[-1] == "4", calls
    probs = copy.problems("t1")
    assert [p["seq"] for p in probs] == [a] and probs[0]["last_status"] == 500
    assert "повторить" in probs[0]["detail"]["message"]


def test_gateway_errors_never_count_against_the_edit(copy):
    """502/503/504 — сервер лежит целиком. Долгая авария не имеет права отбраковать
    правку: иначе очередь таяла бы по одной записи за каждые полчаса простоя."""
    _two_grades(copy)
    calls = []
    for _ in range(copy.MAX_SERVER_ERRORS * 2):
        _time_passes(copy)
        copy.flush(login="t1", auth=_auth, send=_answer_by_grade(502, calls))
    assert copy.counts("t1") == {"available": True, "pending": 2, "conflicts": 0,
                                 "rejected": 0}
    assert set(calls) == {"5"}, "очередь перескочила недоставленную правку"


def test_retry_only_for_edits_set_aside_by_server_errors(copy):
    a, _b = _two_grades(copy)
    calls = []
    for _ in range(copy.MAX_SERVER_ERRORS):
        _time_passes(copy)
        copy.flush(login="t1", auth=_auth, send=_answer_by_grade(500, calls))
    assert copy.resolve(a, "t1", "retry")["ok"]
    assert copy.counts("t1")["rejected"] == 0 and copy.counts("t1")["pending"] == 1

    c = copy.enqueue("t1", "POST", "/web/teacher/grade", "", b'{"grade": "3"}',
                     "application/json")
    copy.mark_ready(c, {"id": "G-foreign", "base_updated_at": T0, "updated_at": LOCAL})
    copy.flush(login="t1", auth=_auth,
               send=lambda m, u, b, h: (403, {"detail": "Этот предмет вам не назначен"})
               if b'"3"' in (b or b"") else (200, {"updated_at": T1}))
    refused = copy.resolve(c, "t1", "retry")
    assert not refused["ok"], "повтор отказа по существу бесполезен — кнопки быть не должно"


# ── зеркало после записи, пересланной на бой ─────────────────────────────────────────
def test_save_waits_for_the_mirror_no_longer_than_promised(monkeypatch):
    """«Сохранить» ждёт зеркало не дольше `_MIRROR_AFTER_WRITE_S`, а пять сохранений
    подряд не заводят пять параллельных проходов по сети."""
    calls = []

    def slow_mirror(*_a, **_k):
        calls.append(time.monotonic())
        time.sleep(0.6)
        return {"ok": True}

    monkeypatch.setattr(local_mirror, "mirror_once", slow_mirror)
    monkeypatch.setattr(local_api, "_MIRROR_AFTER_WRITE_S", 0.2)

    async def five_saves():
        await asyncio.gather(*(local_api._refresh_mirror_after_write() for _ in range(5)))

    started = time.monotonic()
    asyncio.run(five_saves())
    waited = time.monotonic() - started
    deadline = time.monotonic() + 10
    while local_api._refresh["thread"] is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert waited < 0.5, f"«Сохранить» ждало зеркало {waited:.2f} с вместо 0.2"
    assert 1 <= len(calls) <= 2, f"пять сохранений завели {len(calls)} проходов зеркала"
