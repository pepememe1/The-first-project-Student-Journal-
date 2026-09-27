"""
test_desk_outbox.py — очередь правок журнала, сделанных в программе, на бой (аудит
22.09.2026, находки F-02, F-05, F-09, P1).

━━ ЧТО ДЕРЖАТ ЭТИ ТЕСТЫ ━━
До починки оценка, выставленная в программе, ложилась в локальную копию, получала
«сохранено» и не доходила до боя НИКОГДА: старый синк собирал правки из другой базы.
Очередь — недостающая половина пути. Здесь проверяются её правила, от которых зависит
сохранность журнала:
  • досылка строго по порядку (оценка к занятию не уезжает раньше занятия);
  • версия, которую видел человек, доезжает до боя, в том числе у второй правки той же
    оценки (она снята с ЛОКАЛЬНОЙ версии первой — подставляется боевая);
  • конфликт не решается молча: правка ждёт человека, а поздняя правка той же строки —
    вместе с ней;
  • отказ по существу не останавливает остальных; сеть и 5xx — останавливают, ничего не
    перескакивая;
  • создание занятия досылается с тем же id, что в копии.
Правила проверяются подменой отправки (`send`) — проверяется правило, а не интернет.
Сквозная проводка «запрос интерфейса → очередь» — в `test_journal_write_goes_to_the_outbox`.
"""
import json
import time

import pytest

from desktop import desk_outbox, local_api


@pytest.fixture()
def outbox(tmp_path, monkeypatch):
    """Очередь на ВРЕМЕННОЙ копии; вошедший — t1."""
    local_api.prepare_env()
    from app import db as _db
    old_url, old_key = _db.DATABASE_URL, _db.DB_KEY
    _db.rebind(f"sqlite:///{(tmp_path / 'outbox.db').as_posix()}", "")
    monkeypatch.setattr(local_api, "_session_login", lambda: "t1")
    yield desk_outbox
    _db.rebind(old_url, old_key)


def _queue(ob, method, path, body, response, login="t1"):
    seq = ob.enqueue(login, method, path, "", json.dumps(body).encode(), "application/json")
    ob.mark_ready(seq, response)
    return seq


class _Server:
    """Подменная отправка: записывает запросы и отвечает по сценарию."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, json.loads(body or b"{}"), headers))
        return self.answers.pop(0) if self.answers else (200, {"updated_at": "P-last"})


def _auth():
    return "https://prod.test", "prod-token", ""


def _flush(ob, server):
    return ob.flush(login="t1", auth=_auth, send=server)


def test_sends_in_order_and_chains_the_version_of_our_own_earlier_edit(outbox):
    """Вторая офлайн-правка той же оценки снята с ЛОКАЛЬНОЙ версии первой. Бою нужна
    ЕГО версия — иначе он принял бы нашу же правку за чужую и выдал ложный конфликт."""
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
           {"id": "G1", "base_updated_at": "T0", "updated_at": "L1"})
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "4"},
           {"id": "G1", "base_updated_at": "L1", "updated_at": "L2"})
    srv = _Server((200, {"updated_at": "P1"}), (200, {"updated_at": "P2"}))
    res = _flush(outbox, srv)
    assert res["sent"] == 2, res
    assert [c[2]["grade"] for c in srv.calls] == ["5", "4"], "порядок досылки нарушен"
    assert srv.calls[0][2]["base_updated_at"] == "T0"
    assert srv.calls[1][2]["base_updated_at"] == "P1", (
        "вторая правка ушла с локальной версией первой — бой счёл бы её затиранием")
    assert srv.calls[0][3]["Authorization"] == "Bearer prod-token"
    assert outbox.counts("t1")["pending"] == 0


def test_conflict_waits_for_a_human_and_holds_later_edits_of_the_same_row(outbox):
    a = _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
               {"id": "G1", "base_updated_at": "T0", "updated_at": "LA"})
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "3"},
           {"id": "G1", "base_updated_at": "LA", "updated_at": "LB"})
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "2"},
           {"id": "G2", "base_updated_at": "T9", "updated_at": "LC"})
    conflict = (409, {"detail": {"code": "conflict", "kind": "grade", "id": "G1",
                                 "server": {"grade": "4"}}})
    srv = _Server(conflict, (200, {"updated_at": "PC"}))
    res = _flush(outbox, srv)
    assert res["conflicts"] == 1 and res["sent"] == 1, res
    assert [c[2]["grade"] for c in srv.calls] == ["5", "2"], (
        "поздняя правка той же оценки ушла, не дождавшись решения по конфликту")
    probs = outbox.problems("t1")
    assert len(probs) == 1 and probs[0]["state"] == "conflict"
    assert probs[0]["detail"]["server"]["grade"] == "4", "человеку нужна версия сервера"

    #Решение «оставить моё»: досылаем без сверки версии, следом — отложенная правка.
    assert outbox.resolve(a, "t1", "keep_mine")["ok"]
    srv2 = _Server((200, {"updated_at": "PA"}), (200, {"updated_at": "PB"}))
    _flush(outbox, srv2)
    assert "base_updated_at" not in srv2.calls[0][2], "«моё» обязано уйти без сверки"
    assert srv2.calls[1][2]["base_updated_at"] == "PA"
    assert outbox.counts("t1") == {"available": True, "pending": 0, "conflicts": 0,
                                   "rejected": 0}


def test_keep_server_drops_the_edit_and_asks_for_a_full_resync(outbox):
    a = _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
               {"id": "G1", "base_updated_at": "T0", "updated_at": "L1"})
    _flush(outbox, _Server((409, {"detail": {"code": "conflict", "server": {}}})))
    assert outbox.resolve(a, "t1", "keep_server")["ok"]
    assert outbox.counts("t1")["conflicts"] == 0
    assert outbox.take_rebuild_request() is True, (
        "копия осталась бы с отвергнутым значением: зеркало его уже не перезапишет")
    assert outbox.take_rebuild_request() is False, "просьба сверки — одноразовая"


def test_rejection_is_kept_visible_and_does_not_stop_the_rest(outbox):
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
           {"id": "G1", "base_updated_at": "T0", "updated_at": "L1"})
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "4"},
           {"id": "G2", "base_updated_at": "T0", "updated_at": "L2"})
    srv = _Server((403, {"detail": "Этот предмет вам не назначен"}), (200, {"updated_at": "P"}))
    res = _flush(outbox, srv)
    assert res == {"sent": 1, "conflicts": 0, "rejected": 1, "stopped": ""}, res
    probs = outbox.problems("t1")
    assert probs[0]["state"] == "rejected" and probs[0]["last_status"] == 403
    assert "не назначен" in json.dumps(probs[0]["detail"], ensure_ascii=False)


@pytest.mark.parametrize("status", [0, 408, 425, 429, 500, 503])
def test_transient_failure_stops_without_skipping_anything(outbox, status):
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
           {"id": "G1", "base_updated_at": "T0", "updated_at": "L1"})
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "4"},
           {"id": "G2", "base_updated_at": "T0", "updated_at": "L2"})
    srv = _Server((status, {"detail": "временно"}))
    res = _flush(outbox, srv)
    assert len(srv.calls) == 1, "после временного сбоя очередь перескочила вперёд"
    assert res["stopped"] and res["sent"] == 0 and res["rejected"] == 0, res
    assert outbox.counts("t1")["pending"] == 2, "временный сбой не имеет права терять правку"


def test_expired_token_stops_the_flush(outbox):
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
           {"id": "G1", "base_updated_at": "T0", "updated_at": "L1"})
    res = _flush(outbox, _Server((401, {"detail": "expired"})))
    assert res["stopped"] == "expired"
    assert outbox.counts("t1")["pending"] == 1


def test_no_token_means_no_attempt(outbox):
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
           {"id": "G1", "base_updated_at": "T0", "updated_at": "L1"})
    srv = _Server()
    res = outbox.flush(login="t1", auth=lambda: ("https://x", "", "offline"), send=srv)
    assert res["stopped"] == "offline" and not srv.calls


def test_in_flight_request_blocks_later_ones_but_an_orphan_is_sent(outbox):
    """Запрос, который копия ещё обрабатывает, перескочить нельзя: следующая правка
    может от него зависеть. А «pending», оставшийся от упавшего процесса, — досылается."""
    from sqlalchemy import text
    young = outbox.enqueue("t1", "POST", "/web/teacher/lesson", "", b"{}", "application/json")
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
           {"id": "G1", "base_updated_at": "", "updated_at": "L1"})
    srv = _Server()
    res = _flush(outbox, srv)
    assert res["stopped"] == "in-flight" and not srv.calls

    with outbox._tx() as c:
        c.execute(text("UPDATE desk_outbox SET created_epoch = :e WHERE seq = :s"),
                  {"e": time.time() - outbox.ORPHAN_AFTER_S - 5, "s": young})
    res = _flush(outbox, srv)
    assert res["sent"] == 2, res


def test_lesson_create_is_replayed_with_the_id_the_copy_gave_it(outbox):
    """Иначе бой завёл бы занятие под ДРУГИМ id, и оценки к нему, выставленные офлайн,
    досылались бы к несуществующему на бою занятию."""
    _queue(outbox, "POST", "/web/teacher/lesson", {"group": "К-24", "type": "Практика"},
           {"id": "0a8f3c4e-1111-4222-8333-944455556666", "updated_at": "L1",
            "base_updated_at": ""})
    srv = _Server((200, {"id": "0a8f3c4e-1111-4222-8333-944455556666", "updated_at": "P1"}))
    _flush(outbox, srv)
    sent = srv.calls[0][2]
    assert sent["id"] == "0a8f3c4e-1111-4222-8333-944455556666"
    assert "base_updated_at" not in sent, "у создания базовой версии нет"


def test_handler_refusal_drops_the_queued_edit(outbox):
    seq = outbox.enqueue("t1", "POST", "/web/teacher/grade", "", b"{}", "application/json")
    outbox.drop(seq)
    assert outbox.counts("t1")["pending"] == 0


def test_pending_keys_protect_rows_from_the_mirror(outbox):
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
           {"id": "G1", "base_updated_at": "T0", "updated_at": "L1"})
    _queue(outbox, "PUT", "/web/teacher/lesson/L-7", {"topic": "x"},
           {"id": "L-7", "base_updated_at": "T0", "updated_at": "L2"})
    assert outbox.pending_keys() == {("grades", "G1"), ("lessons", "L-7")}


def test_mirror_does_not_overwrite_a_row_with_an_unsent_edit(outbox):
    """Строку с неотправленной правкой зеркало пропускает — иначе человек видел бы, как
    его оценка «откатилась», пока правка ещё не дошла до боя."""
    from desktop import local_mirror
    from app.db import SessionLocal
    _queue(outbox, "POST", "/web/teacher/grade", {"grade": "5"},
           {"id": "G1", "base_updated_at": "T0", "updated_at": "L1"})
    db = SessionLocal()
    try:
        from app.models import Base
        Base.metadata.create_all(db.get_bind())
        changes = {"grades": [
            {"id": "G1", "student_f": "Иванов", "student_n": "Иван", "lesson_id": "L",
             "grade": "2", "updated_at": "T5"},
            {"id": "G2", "student_f": "Петров", "student_n": "Пётр", "lesson_id": "L",
             "grade": "4", "updated_at": "T5"}]}
        n = local_mirror.apply_changes(db, changes, skip=outbox.pending_keys())
        db.commit()
        assert n == 1, "строку с неотправленной правкой зеркало перезаписало"
    finally:
        db.close()
