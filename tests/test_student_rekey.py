"""
test_student_rekey.py — ДЕСКТОП: смена ФИО студента не теряет оценки.

Зеркало серверного test_student_rename.py (правки делаем на обеих платформах). Оценки
ключуются по ФИО, поэтому переименование без перекючивания отвязывало всю историю.
"""
import sqlite3

from core import DBManager
from data_store import rekey_student_grades


def _seed():
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO grades (student_f,student_n,lesson_id,grade,"
                "updated_at,deleted) VALUES ('Иванова','Мария','L1','5','2026-01-01',0)")
    cur.execute("INSERT OR REPLACE INTO term_grades (id,student_f,student_n,subject,year,"
                "semester,grade,form,updated_at,deleted) VALUES "
                "('Иванова|Мария|Математика|2025/2026|1','Иванова','Мария','Математика',"
                "'2025/2026',1,'5','экзамен','2026-01-01',0)")
    conn.commit()
    conn.close()


def _rows(sql, args=()):
    conn = DBManager.get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, args)
    out = [dict(r) for r in cur.fetchall()]
    conn.close()
    return out


def test_rename_updates_in_place_without_tombstones(fresh_db):
    """ЭТАП 3: переименование правит ФИО НА МЕСТЕ и надгробий не создаёт.

    Раньше история физически переезжала на новый ключ, а старый хоронился. Так делать
    больше нельзя, и это не вкусовщина: у живой строки и её надгробия ОДИН student_id,
    значит при push обе дают один серверный ключ — сервер применил бы пришедшую
    последней и с вероятностью 50% похоронил бы живую оценку."""
    _seed()
    moved = rekey_student_grades("Иванова", "Мария", "Петрова", "Мария")
    assert moved == 2                      #обычная + итоговая

    live = _rows("SELECT student_f,grade FROM grades WHERE COALESCE(deleted,0)=0")
    assert live == [{"student_f": "Петрова", "grade": "5"}], "ФИО-копия обновилась"

    dead = _rows("SELECT student_f FROM grades WHERE COALESCE(deleted,0)=1")
    assert dead == [], "надгробий быть не должно — они утопили бы живую оценку"

    all_rows = _rows("SELECT student_f FROM grades")
    assert len(all_rows) == 1, "строка одна, дубля со старым ФИО не осталось"

    tg = _rows("SELECT student_f FROM term_grades WHERE COALESCE(deleted,0)=0")
    assert tg == [{"student_f": "Петрова"}], "итоговая тоже обновилась на месте"


def test_noop_when_name_unchanged(fresh_db):
    _seed()
    assert rekey_student_grades("Иванова", "Мария", "Иванова", "Мария") == 0
    live = _rows("SELECT student_f FROM grades WHERE COALESCE(deleted,0)=0")
    assert live == [{"student_f": "Иванова"}], "без смены ФИО ничего не трогаем"
