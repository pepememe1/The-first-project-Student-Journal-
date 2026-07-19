"""
test_backfill_student_id.py — ДЕСКТОП: бэкофилл student_id (этап 2 миграции).

Зеркало серверного скрипта. Проверяем не «сколько сматчилось», а поведение на границах:
однофамильцы, отсутствующий студент, идемпотентность и — главное — что скрипт НЕ трогает
updated_at. Последнее не косметика: бамп метки объявил бы каждую оценку изменённой, весь
парк выкачал бы базу заново, а серверная метка могла бы перебить более свежую офлайн-правку.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools"))

import backfill_student_id_desktop as bf  # noqa: E402
from core import DBManager  # noqa: E402
from data_store import get_store  # noqa: E402


def _seed_students(rows):
    get_store().set_students(rows)
    return {(s["surname"], s["name"], s.get("group", "")): s["id"]
            for s in get_store().get_students()}


def _add_lesson(lid, group):
    conn = DBManager.get_conn()
    conn.execute("INSERT OR REPLACE INTO lessons (id,group_name,subject,type,number,topic,"
                 "date,updated_at,deleted) VALUES (?,?,'Мат','Лекция',1,'','01.09.2025',"
                 "'2026-01-01T00:00:00+00:00',0)", (lid, group))
    conn.commit()
    conn.close()


def _add_grade(f, n, lid, ts="2026-01-01T00:00:00+00:00", deleted=0):
    """Оценка БЕЗ student_id — как её записал бы клиент до этапа 1."""
    conn = DBManager.get_conn()
    conn.execute("INSERT OR REPLACE INTO grades (student_f,student_n,lesson_id,grade,"
                 "updated_at,deleted,student_id) VALUES (?,?,?,'5',?,?,'')",
                 (f, n, lid, ts, deleted))
    conn.commit()
    conn.close()


def _grade(f, n, lid):
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(student_id,''), COALESCE(updated_at,'') FROM grades "
                "WHERE student_f=? AND student_n=? AND lesson_id=?", (f, n, lid))
    row = cur.fetchone()
    conn.close()
    return row


def test_dry_run_changes_nothing(fresh_db):
    """Без --apply база не меняется: это боевые данные преподавателя, и порядок
    «отчёт → решение → запись» здесь единственный разумный."""
    _seed_students([{"surname": "Иванова", "name": "Мария", "group": "К-101"}])
    _add_lesson("L1", "К-101")
    _add_grade("Иванова", "Мария", "L1")

    text, written = bf.run(apply=False)
    assert written == 0
    assert "ХОЛОСТОЙ ПРОГОН" in text
    assert _grade("Иванова", "Мария", "L1")[0] == "", "БД не должна измениться"


def test_apply_fills_id_and_keeps_updated_at(fresh_db):
    """Проставляет id и НЕ трогает метку времени."""
    ids = _seed_students([{"surname": "Иванова", "name": "Мария", "group": "К-101"}])
    _add_lesson("L1", "К-101")
    _add_grade("Иванова", "Мария", "L1", ts="2026-01-01T00:00:00+00:00")

    _text, written = bf.run(apply=True)
    assert written == 1
    sid, updated = _grade("Иванова", "Мария", "L1")
    assert sid == ids[("Иванова", "Мария", "К-101")]
    assert updated == "2026-01-01T00:00:00+00:00", \
        "метку трогать нельзя — иначе вся база уедет в push и может перебить чужую правку"


def test_namesakes_split_by_lesson_group(fresh_db):
    """Полных тёзок различаем по группе ЗАНЯТИЯ — двух Ивановых Иванов в одну группу
    не заводят, поэтому занятие однозначно указывает на нужного."""
    ids = _seed_students([{"surname": "Иванов", "name": "Иван", "group": "К-101"},
                          {"surname": "Иванов", "name": "Иван", "group": "К-102"}])
    _add_lesson("L1", "К-101")
    _add_lesson("L2", "К-102")
    _add_grade("Иванов", "Иван", "L1")
    _add_grade("Иванов", "Иван", "L2")

    _text, written = bf.run(apply=True)
    assert written == 2
    assert _grade("Иванов", "Иван", "L1")[0] == ids[("Иванов", "Иван", "К-101")]
    assert _grade("Иванов", "Иван", "L2")[0] == ids[("Иванов", "Иван", "К-102")]


def test_ambiguous_namesake_is_refused_not_guessed(fresh_db):
    """Занятия нет → различить тёзок нечем. НЕ угадываем: приписать оценку не тому
    студенту хуже, чем оставить строку на ФИО. И это попадает в отчёт как стоп-сигнал."""
    _seed_students([{"surname": "Иванов", "name": "Иван", "group": "К-101"},
                    {"surname": "Иванов", "name": "Иван", "group": "К-102"}])
    _add_grade("Иванов", "Иван", "LX")        #занятия LX не существует

    text, written = bf.run(apply=True)
    assert written == 0
    assert _grade("Иванов", "Иван", "LX")[0] == ""
    assert "ЖИВЫХ оценок без владельца: 1" in text
    assert "ЭТАП 3" in text and "НЕЛЬЗЯ" in text


def test_unknown_student_reported_with_reason(fresh_db):
    """Студента нет в справочнике — в отчёте видно ФИО и причину, чтобы разобрать руками."""
    _seed_students([{"surname": "Иванова", "name": "Мария", "group": "К-101"}])
    _add_lesson("L1", "К-101")
    _add_grade("Нет", "Такого", "L1")

    text, _written = bf.run(apply=True)
    assert "Нет Такого" in text
    assert bf.REASON_NOT_FOUND in text


def test_tombstones_do_not_block_stage3(fresh_db):
    """Несклеенное надгробие — не препятствие: у удалённой оценки владелец уже не нужен.
    Отчёт обязан отличать это от живой потерянной оценки, иначе миграция встанет зря."""
    _seed_students([{"surname": "Иванова", "name": "Мария", "group": "К-101"}])
    _add_lesson("L1", "К-101")
    _add_grade("Ушедший", "Студент", "L1", deleted=1)

    text, _written = bf.run(apply=True)
    assert "ЖИВЫХ оценок без владельца" not in text
    assert "только надгробия" in text


def test_idempotent(fresh_db):
    """Повторный запуск ничего не переписывает — заполненные строки не выбираются."""
    _seed_students([{"surname": "Иванова", "name": "Мария", "group": "К-101"}])
    _add_lesson("L1", "К-101")
    _add_grade("Иванова", "Мария", "L1")

    assert bf.run(apply=True)[1] == 1
    assert bf.run(apply=True)[1] == 0, "второй проход не должен находить работу"


def test_term_grades_get_id_too(fresh_db):
    """Итоговые оценки тоже переводим — иначе ведомости остались бы на ФИО-ключах."""
    ids = _seed_students([{"surname": "Иванова", "name": "Мария", "group": "К-101"}])
    conn = DBManager.get_conn()
    conn.execute("INSERT OR REPLACE INTO term_grades (id,student_f,student_n,subject,year,"
                 "semester,grade,form,updated_at,deleted,student_id) VALUES "
                 "('Иванова|Мария|Мат|2025/2026|1','Иванова','Мария','Мат','2025/2026',1,"
                 "'5','экзамен','2026-01-01T00:00:00+00:00',0,'')")
    conn.commit()
    conn.close()

    _text, written = bf.run(apply=True)
    assert written == 1
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT student_id FROM term_grades WHERE id='Иванова|Мария|Мат|2025/2026|1'")
    got = cur.fetchone()[0]
    conn.close()
    assert got == ids[("Иванова", "Мария", "К-101")]
