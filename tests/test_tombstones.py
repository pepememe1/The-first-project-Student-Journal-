"""
test_tombstones.py — Удаление занятий/оценок: надгробия, неисчезновение данных,
распространение удаления через синхронизацию (главное про «данные не путаются»).
"""
from core import GradeBook, Student
import sync_engine

G, S = "ИС-21", "Математика"


def _book_with_lessons():
    gb = GradeBook(G, S)
    gb.add_student(Student("Иван", "Иванов", G))
    l1 = gb.add_lesson("Практика", "Тема1", "01.09.2025")
    l2 = gb.add_lesson("Практика", "Тема2", "02.09.2025")
    st = gb.spisok_stud[0]
    st.records[l1.id] = "5"
    st.records[l2.id] = "3"
    gb.save_to_db()
    return gb, l1, l2


def test_deleted_lesson_stays_deleted_after_reload(fresh_db):
    """Старый баг: удалённое занятие возвращалось после перезагрузки журнала
    (delete лишь убирал из списка в памяти, строка в БД оставалась). Теперь —
    надгробие в БД, занятие не воскресает."""
    gb, l1, l2 = _book_with_lessons()
    gb.delete_lesson(l1.id)
    reloaded = GradeBook(G, S)
    ids = [l.id for l in reloaded.lessons]
    assert l1.id not in ids
    assert l2.id in ids


def test_deleted_lesson_propagates_as_tombstone(fresh_db):
    """Надгробие занятия уходит на сервер (collect), а не «пропадает молча»."""
    gb, l1, _ = _book_with_lessons()
    gb.delete_lesson(l1.id)
    snap = sync_engine.collect_local()
    row = [l for l in snap["lessons"] if l["id"] == l1.id]
    assert row and row[0]["deleted"] is True


def test_remote_lesson_tombstone_applies(fresh_db):
    """Надгробие занятия с сервера (более свежее) удаляет занятие локально."""
    gb, l1, l2 = _book_with_lessons()
    sync_engine.apply_remote({"lessons": [{
        "id": l2.id, "group_name": G, "subject": S, "type": "Практика", "number": 2,
        "topic": "Тема2", "date": "02.09.2025", "retake_date": "", "hour": 0,
        "updated_at": "2099-01-01T00:00:00+00:00", "deleted": True}]})
    assert l2.id not in [l.id for l in GradeBook(G, S).lessons]


def test_deleting_student_tombstones_grades(fresh_db):
    """Удаление студента надгробит его оценки: они не грузятся и уходят надгробием
    на сервер (иначе на других ПК оценки удалённого студента воскресали бы)."""
    gb = GradeBook(G, S)
    gb.add_student(Student("Пётр", "Петров", G))
    l = gb.add_lesson("Практика", "Тема", "03.09.2025")
    st = [s for s in gb.spisok_stud if s.f == "Петров"][0]
    st.records[l.id] = "4"
    gb.save_to_db()

    gb.delete_student("Петров", "Пётр")
    reloaded = GradeBook(G, S)
    petrov = [s for s in reloaded.spisok_stud if s.f == "Петров"]
    assert not petrov or not petrov[0].records.get(l.id)

    tomb = [g for g in sync_engine.collect_local()["grades"]
            if g["student_f"] == "Петров" and g["deleted"] is True]
    assert tomb, "надгробие оценки должно уйти на сервер"


def test_remote_grade_tombstone_applies(fresh_db):
    """Надгробие оценки с сервера (свежее) удаляет активную оценку локально."""
    gb = GradeBook(G, S)
    gb.add_student(Student("Сидор", "Сидоров", G))
    l = gb.add_lesson("Практика", "Тема", "04.09.2025")
    st = [s for s in gb.spisok_stud if s.f == "Сидоров"][0]
    st.records[l.id] = "5"
    gb.save_to_db()

    sync_engine.apply_remote({"grades": [{
        "student_f": "Сидоров", "student_n": "Сидор", "lesson_id": l.id, "grade": "5",
        "device": "other", "updated_at": "2099-01-01T00:00:00+00:00", "deleted": True}]})

    reloaded = GradeBook(G, S)
    sidorov = [s for s in reloaded.spisok_stud if s.f == "Сидоров"][0]
    assert not sidorov.records.get(l.id)
