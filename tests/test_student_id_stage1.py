"""
test_student_id_stage1.py — ДЕСКТОП: оценки несут неизменяемый student_id.

Этап 1 миграции с ФИО-ключей. Ключ оценки пока прежний (ФИО|lesson_id), но рядом едет
id строки users. Проверяем именно совместимость: колонка добавочная, пустое значение
законно, синк её возит в обе стороны. Переключение самого ключа — этап 3.
"""
import sqlite3

from data import local_db
from data.core import DBManager, resolve_student_id
from data.data_store import get_store, student_id_by_name


def _grade_rows():
    conn = DBManager.get_conn()
    #Фабрику берём у драйвера соединения: база зашифрована (SQLCipher), и
    #`sqlite3.Row` к её курсору не подходит — см. local_db.use_named_rows.
    local_db.use_named_rows(conn)
    cur = conn.cursor()
    cur.execute("SELECT student_f,student_n,lesson_id,grade,COALESCE(student_id,'') "
                "AS student_id FROM grades")
    out = [dict(r) for r in cur.fetchall()]
    conn.close()
    return out


def _seed_student(surname="Иванова", name="Мария", group="К-101") -> str:
    st = get_store()
    st.set_students([{"surname": surname, "name": name, "group": group}])
    return [s for s in st.get_students() if s["surname"] == surname][0]["id"]


def test_grade_gets_student_id_on_write(fresh_db):
    """Выставление оценки проставляет id автоматически — вызывающему думать не надо."""
    sid = _seed_student()
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, ("Иванова", "Мария", "L1", "5"))
    conn.commit()
    conn.close()

    rows = _grade_rows()
    assert rows[0]["student_id"] == sid, "оценка обязана нести id студента"


def test_unknown_student_leaves_id_empty(fresh_db):
    """Студента нет в справочнике (ростер препода ведётся отдельно) — это НЕ ошибка.
    Пустой id законен, привязка остаётся по ФИО."""
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, ("Неизвестный", "Студент", "L1", "4"))
    conn.commit()
    conn.close()
    assert _grade_rows()[0]["student_id"] == ""


def test_namesakes_in_different_groups_are_not_guessed(fresh_db):
    """Полные тёзки в разных группах — привязку НЕ угадываем. Лучше оставить связь по
    ФИО, чем уверенно приписать оценку не тому человеку."""
    st = get_store()
    st.set_students([{"surname": "Иванов", "name": "Иван", "group": "К-101"},
                     {"surname": "Иванов", "name": "Иван", "group": "К-102"}])
    assert student_id_by_name("Иванов", "Иван") == "", "без группы — отказ, а не догадка"
    #с указанием группы неоднозначности нет
    assert student_id_by_name("Иванов", "Иван", "К-102").startswith("stud:")


def test_id_survives_rename(fresh_db):
    """Ради чего всё затевалось: ФИО поменялось — id оценки остался прежним."""
    sid = _seed_student()
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, ("Иванова", "Мария", "L1", "5"))
    conn.commit()
    conn.close()

    from data.data_store import rekey_student_grades
    rekey_student_grades("Иванова", "Мария", "Петрова", "Мария")
    live = [r for r in _grade_rows() if r["student_f"] == "Петрова"]
    assert live and live[0]["student_id"] == sid, \
        "после переименования id обязан указывать на того же студента"


def test_resolve_student_id_never_raises(fresh_db):
    """Резолвер обязан быть безопасным: он вызывается на каждой записи оценки, и
    исключение из него уронило бы саму простановку балла."""
    assert resolve_student_id("", "") == ""
    assert resolve_student_id("Нет", "Такого") == ""
