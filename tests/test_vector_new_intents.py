"""
test_vector_new_intents.py — десктопный Вектор понимает НОВЫЕ интенты (единый словарь):
счёт оценок, оценки по предмету, распознавание предмета в склонениях.

Раньше это не умела НИ одна платформа; теперь лексикон общий (vector_nlu), и десктоп с
сервером отвечают одинаково. Числа — из реальной локальной БД (SQLite), не из модели.
"""
import os
import sqlite3
import tempfile

import pytest

from vector.intents import VectorScope
from vector.engine import VectorEngine
from vector import intents


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    c = sqlite3.connect(path)
    cur = c.cursor()
    cur.execute("CREATE TABLE students(f TEXT,n TEXT,group_name TEXT)")
    cur.execute("CREATE TABLE lessons(id TEXT,type TEXT,number INT,topic TEXT,date TEXT,"
                "hour INT,group_name TEXT,subject TEXT,deleted INT DEFAULT 0)")
    cur.execute("CREATE TABLE grades(student_f TEXT,student_n TEXT,lesson_id TEXT,"
                "grade TEXT,deleted INT DEFAULT 0)")
    cur.execute("INSERT INTO students VALUES('Иванов','Иван','ИС-21')")
    for lid, num, subj in [("M1", 1, "Математика"), ("M2", 2, "Математика"),
                           ("F1", 1, "Физика")]:
        cur.execute("INSERT INTO lessons VALUES(?,?,?,?,?,?,?,?,0)",
                    (lid, "Практика", num, "т", "01.09.2025", 1, "ИС-21", subj))
    for lid, g in [("M1", "5"), ("M2", "4"), ("F1", "3")]:
        cur.execute("INSERT INTO grades VALUES('Иванов','Иван',?,?,0)", (lid, g))
    c.commit()
    c.close()
    yield path
    os.remove(path)


def _scope(db):
    return VectorScope(role="student", group="ИС-21",
                       student_f="Иванов", student_n="Иван", db_path=db)


def test_classify_returns_subject_and_day(db_path):
    """classify теперь отдаёт (intent, surname, subject, day) из общего vector_nlu."""
    i, a, subj, day, _g = intents.classify("оценки по физике", ["Иванов"],
                                       ["Математика", "Физика"])
    assert i == "subject_grades" and subj == "Физика"     # склонение «физике» распознано
    i2, _, _, day2, _g2 = intents.classify("что завтра", ["Иванов"], [])
    assert i2 == "schedule" and day2 == "tomorrow"


def test_grade_count_total_and_by_subject(db_path):
    """Счёт оценок: всего и по конкретному предмету (scope.subject фильтрует)."""
    sc = _scope(db_path)
    f = intents.intent_grade_count(sc)
    assert f.data["total"] == 3 and f.data["5"] == 1 and f.data["3"] == 1
    sc.subject = "Математика"
    f2 = intents.intent_grade_count(sc)
    assert f2.data["total"] == 2 and f2.data["2"] == 0     # только математика: 5,4


def test_subject_grades_end_to_end(db_path):
    """engine.ask распознаёт предмет и отдаёт оценки по нему (средний 4.5 по математике)."""
    eng = VectorEngine(_scope(db_path))
    r = eng.ask("какие у меня оценки по математике")
    assert r.intent == "subject_grades"
    assert "4.5" in r.text                                 # (5+4)/2


def test_subject_does_not_stick_between_questions(db_path):
    """Предмет из одного вопроса не «залипает» на следующий без предмета."""
    eng = VectorEngine(_scope(db_path))
    eng.ask("оценки по математике")                        # ставит subject=Математика
    r = eng.ask("мой средний балл")                        # без предмета → по всем
    assert r.intent == "average"
    assert "4.0" in r.text or "4" in r.text                # средний по ВСЕМ: (5+4+3)/3=4.0


def test_schedule_graceful_without_cache(db_path):
    """Без кэша расписания — мягкая подсказка, не падаем."""
    r = VectorEngine(_scope(db_path)).ask("когда математика")
    assert r.intent == "schedule"
    assert "асписан" in r.text                             # «Расписание …» / «в расписании»
