"""
test_persistence.py — Персистентность по действию: выставленная оценка попадает на
диск СРАЗУ и переживает перезагрузку журнала (раньше жила только в памяти до «Сохранить»).
"""
from data.core import DBManager, GradeBook, Student

G, S = "ИС-21", "Математика"


def _persist_grade(student_f, student_n, key, val):
    """То же, что делает teacher_dashboard._persist_grade на каждое действие."""
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, (student_f, student_n, key, val))
    conn.commit()
    conn.close()


def test_grade_survives_journal_reload(fresh_db):
    gb = GradeBook(G, S)
    gb.add_student(Student("Иван", "Иванов", G))
    lesson = gb.add_lesson("Практика", "Тема", "01.09.2025")

    #имитируем ввод оценки в журнале (per-action save, без кнопки «Сохранить»)
    _persist_grade("Иванов", "Иван", lesson.id, "5")

    #перезагрузка журнала из БД (как при смене группы/предмета или перезапуске)
    reloaded = GradeBook(G, S)
    st = [s for s in reloaded.spisok_stud if s.f == "Иванов"][0]
    assert st.records.get(lesson.id) == "5", "оценка должна сохраниться сразу, а не потеряться"


def test_retake_key_persists_separately(fresh_db):
    """Пересдача хранится под отдельным ключом lesson_id+'_retake' и не затирает
    основную оценку — обе переживают перезагрузку."""
    gb = GradeBook(G, S)
    gb.add_student(Student("Пётр", "Петров", G))
    lesson = gb.add_lesson("Практика", "Тема", "01.09.2025")
    _persist_grade("Петров", "Пётр", lesson.id, "2 (Не зачтено)")
    _persist_grade("Петров", "Пётр", lesson.id + "_retake", "4 (Зачтено)")

    reloaded = GradeBook(G, S)
    st = [s for s in reloaded.spisok_stud if s.f == "Петров"][0]
    assert st.records.get(lesson.id) == "2 (Не зачтено)"
    assert st.records.get(lesson.id + "_retake") == "4 (Зачтено)"
