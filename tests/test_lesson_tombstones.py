"""
test_lesson_tombstones.py — НАДГРОБИЕ ЗАНЯТИЯ на клиенте: уезжает на сервер и приезжает
с него (инвариант §4.5 — удаление не «пропадает молча» и занятие не воскресает).

⚠️ Заведён 31.08.2026 по возражению Полковника. Эти два случая держал `test_tombstones.py`,
удалённый вместе с мёртвым `core.GradeBook`, — и после удаления надгробия ЗАНЯТИЙ не
проверял ни один клиентский тест (у `groups`, `term_grades` и `users` покрытие осталось).
Движок синка табличнообобщённый, поэтому это была потеря ПОКРЫТИЯ, а не дефект; но
регрессия прошла бы зелёной, а это ровно то, от чего у нас заведены сторожа.

От прежней версии тест отличается тем, что занятие заводится ПРЯМОЙ записью в таблицу —
так же, как её наполняет сам синк, — а не через журнал, которым продукт не пользуется.
"""
from data.core import DBManager
from sync import sync_engine

G, S = "ИС-21", "Математика"


def _put_lesson(lid: str, number: int, deleted: int = 0,
                updated_at: str = "2026-01-01T00:00:00+00:00"):
    DBManager._init_sqlite_tables()
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO lessons "
        "(id,group_name,subject,type,number,topic,date,retake_date,hour,"
        " year,semester,updated_at,deleted) "
        "VALUES (?,?,?,'Практика',?,'Тема','01.09.2025','',0,'',0,?,?)",
        (lid, G, S, number, updated_at, deleted))
    conn.commit()
    conn.close()


def _lesson_row(lid: str):
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(deleted,0) FROM lessons WHERE id=?", (lid,))
    row = cur.fetchone()
    conn.close()
    return row


def test_deleted_lesson_propagates_as_tombstone(fresh_db):
    """Надгробие занятия УХОДИТ на сервер (collect_local), а не пропадает молча.

    Обратный ход: заставить `collect_local` пропускать строки с deleted=1 — тест
    краснеет, потому что удаление не доедет до других ПК и занятие там воскреснет."""
    _put_lesson("L1", 1)
    _put_lesson("L2", 2, deleted=1)
    snap = sync_engine.collect_local()
    rows = {l["id"]: l for l in snap["lessons"]}
    assert rows["L2"]["deleted"] is True, "надгробие занятия не уехало на сервер"
    assert rows["L1"]["deleted"] is False


def test_remote_lesson_tombstone_applies(fresh_db):
    """Надгробие занятия С СЕРВЕРА (более свежее) удаляет занятие локально."""
    _put_lesson("L2", 2)
    sync_engine.apply_remote({"lessons": [{
        "id": "L2", "group_name": G, "subject": S, "type": "Практика", "number": 2,
        "topic": "Тема", "date": "01.09.2025", "retake_date": "", "hour": 0,
        "updated_at": "2099-01-01T00:00:00+00:00", "deleted": True}]})
    assert _lesson_row("L2")[0] == 1, "надгробие с сервера не применилось"


def test_older_remote_tombstone_does_not_win(fresh_db):
    """LWW работает и в обратную сторону: УСТАРЕВШЕЕ надгробие не хоронит занятие,
    заведённое позже. Иначе один отставший ПК стирал бы свежее расписание группы."""
    _put_lesson("L3", 3, updated_at="2099-06-01T00:00:00+00:00")
    sync_engine.apply_remote({"lessons": [{
        "id": "L3", "group_name": G, "subject": S, "type": "Практика", "number": 3,
        "topic": "Тема", "date": "01.09.2025", "retake_date": "", "hour": 0,
        "updated_at": "2020-01-01T00:00:00+00:00", "deleted": True}]})
    assert _lesson_row("L3")[0] == 0, "устаревшее надгробие похоронило свежее занятие"
