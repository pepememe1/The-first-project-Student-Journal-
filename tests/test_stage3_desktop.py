"""
test_stage3_desktop.py — ДЕСКТОП, этап 3: ключи оценок по student_id.

Главный риск этапа — ДУБЛИ. У итоговых оценок `id` хранится в таблице И приходит с
сервера при pull, поэтому без локального перевода ключей рядом со старой строкой
`Иванова|Мария|Мат|…` легла бы серверная `stud:…|Мат|…` — две записи одной оценки
в ведомости. Здесь проверяется, что этого не происходит.
"""
import sqlite3

from data import student_link
from sync import sync_engine
from data import local_db
from data.core import DBManager, term_grade_id
from data.data_store import get_store


def _seed_student(surname="Иванова", name="Мария", group="К-101") -> str:
    st = get_store()
    st.set_students([{"surname": surname, "name": name, "group": group}])
    return st.get_students()[0]["id"]


def _rows(sql):
    conn = DBManager.get_conn()
    #Фабрику берём у драйвера соединения: база зашифрована (SQLCipher), и
    #`sqlite3.Row` к её курсору не подходит — см. local_db.use_named_rows.
    local_db.use_named_rows(conn)
    cur = conn.cursor()
    cur.execute(sql)
    out = [dict(r) for r in cur.fetchall()]
    conn.close()
    return out


def _add_legacy_term(f, n, subject, sid=""):
    """Итоговая со СТАРЫМ ключом — как её записала прошлая версия программы."""
    conn = DBManager.get_conn()
    conn.execute("INSERT OR REPLACE INTO term_grades (id,student_f,student_n,subject,"
                 "year,semester,grade,form,updated_at,deleted,student_id) VALUES "
                 "(?,?,?,?,'2025/2026',1,'5','экзамен','2026-01-01T00:00:00+00:00',0,?)",
                 (f"{f}|{n}|{subject}|2025/2026|1", f, n, subject, sid))
    conn.commit()
    conn.close()


def test_term_key_migrates_to_student_id(fresh_db):
    """Старый ФИО-ключ переводится на student_id."""
    sid = _seed_student()
    _add_legacy_term("Иванова", "Мария", "Математика", sid)

    conn = DBManager.get_conn()
    moved = student_link.migrate_local_term_keys(conn)
    conn.close()

    assert moved == 1
    ids = [r["id"] for r in _rows("SELECT id FROM term_grades")]
    assert ids == [term_grade_id(sid, "Математика", "2025/2026", 1)]


def test_no_duplicate_when_server_key_already_present(fresh_db):
    """Ключевой сценарий: серверная строка с НОВЫМ ключом уже приехала, а локальная со
    старым ещё лежит. Должна остаться ОДНА запись, а не две в ведомости."""
    sid = _seed_student()
    _add_legacy_term("Иванова", "Мария", "Математика", sid)
    #как будто pull принёс ту же оценку уже под новым ключом
    conn = DBManager.get_conn()
    conn.execute("INSERT OR REPLACE INTO term_grades (id,student_f,student_n,subject,"
                 "year,semester,grade,form,updated_at,deleted,student_id) VALUES "
                 "(?,'Иванова','Мария','Математика','2025/2026',1,'5','экзамен',"
                 "'2026-01-02T00:00:00+00:00',0,?)",
                 (term_grade_id(sid, "Математика", "2025/2026", 1), sid))
    conn.commit()
    moved = student_link.migrate_local_term_keys(conn)
    conn.close()

    assert moved == 1, "старая строка должна быть убрана"
    rows = _rows("SELECT id FROM term_grades")
    assert len(rows) == 1, "в ведомости не должно остаться дубля"
    assert rows[0]["id"].startswith("stud:")


def test_migration_is_idempotent(fresh_db):
    """Повторный прогон работы не находит."""
    sid = _seed_student()
    _add_legacy_term("Иванова", "Мария", "Математика", sid)
    conn = DBManager.get_conn()
    assert student_link.migrate_local_term_keys(conn) == 1
    assert student_link.migrate_local_term_keys(conn) == 0
    conn.close()


def test_rows_without_student_id_are_left_alone(fresh_db):
    """Студента нет в справочнике — ключ трогать нечем, строку не теряем."""
    _add_legacy_term("Нет", "Такого", "Математика", sid="")
    conn = DBManager.get_conn()
    assert student_link.migrate_local_term_keys(conn) == 0
    conn.close()
    ids = [r["id"] for r in _rows("SELECT id FROM term_grades")]
    assert ids == ["Нет|Такого|Математика|2025/2026|1"], "строка должна уцелеть"


def test_push_sends_new_style_grade_key(fresh_db):
    """Оценка за занятие уезжает на сервер уже с ключом по student_id."""
    sid = _seed_student()
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, ("Иванова", "Мария", "L1", "5"))
    conn.commit()
    conn.close()

    sent = sync_engine._collect_grades()
    assert sent[0]["id"] == f"{sid}|L1", "push обязан слать ключ по id студента"


def test_push_falls_back_to_name_key_when_student_unknown(fresh_db):
    """Студент не опознан — уезжает СТАРЫЙ ключ, а не пустой/битый. Сервер его
    нормализует сам; терять оценку из-за отсутствия в справочнике нельзя."""
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, ("Нет", "Такого", "L1", "4"))
    conn.commit()
    conn.close()

    sent = sync_engine._collect_grades()
    assert sent[0]["id"] == "Нет|Такого|L1"
