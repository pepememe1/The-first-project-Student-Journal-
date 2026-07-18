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


def test_rename_moves_grades_and_tombstones_old(fresh_db):
    _seed()
    moved = rekey_student_grades("Иванова", "Мария", "Петрова", "Мария")
    assert moved == 2                      #обычная + итоговая

    live = _rows("SELECT student_f,grade FROM grades WHERE COALESCE(deleted,0)=0")
    assert live == [{"student_f": "Петрова", "grade": "5"}], "оценка переехала на новый ключ"

    old = _rows("SELECT deleted FROM grades WHERE student_f='Иванова'")
    assert old and old[0]["deleted"] == 1, "старый ключ должен стать надгробием"

    tg = _rows("SELECT id FROM term_grades WHERE COALESCE(deleted,0)=0")
    assert tg == [{"id": "Петрова|Мария|Математика|2025/2026|1"}], "итоговая тоже переехала"


def test_noop_when_name_unchanged(fresh_db):
    _seed()
    assert rekey_student_grades("Иванова", "Мария", "Иванова", "Мария") == 0
    live = _rows("SELECT student_f FROM grades WHERE COALESCE(deleted,0)=0")
    assert live == [{"student_f": "Иванова"}], "без смены ФИО ничего не трогаем"
