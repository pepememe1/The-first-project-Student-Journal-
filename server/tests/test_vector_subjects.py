"""
test_vector_subjects.py — интент «какие у меня предметы» (3.5.6).

ЖИВОЙ БАГ, ради которого всё это заведено: интента `subjects` не существовало вовсе,
и вопрос НЕ проваливался в честное «не понял» — он набирал вес по поддерживающей основе
«какие у меня» в `grades` и уверенно отвечал списком предметов, ПО КОТОРЫМ УЖЕ ЕСТЬ
ОЦЕНКИ. Предмет, импортированный из учебного плана ВСГУТУ (лежит в Group.subjects, но
занятий по нему ещё нет), Вектор словно не видел — при этом ответ выглядел полным.

Второй слой того же бага — источник данных: `_known_subjects` брала предметы ТОЛЬКО из
Lesson. Тот же перекос уже чинили у куратора и в ЗЕТ; здесь он закрыт общей
`webdata.group_subject_list`.
"""
from conftest import make_admin, make_teacher, assign_teacher


def _group(client, admin, name="ИС-21", subjects=("Математика", "Физика")):
    r = client.post("/web/admin/groups", json={"name": name, "subjects": list(subjects)},
                    headers=admin)
    assert r.status_code == 200, r.text


def _student(client, admin, login="ivanova", surname="Иванова", name="Мария", group="ИС-21"):
    r = client.post("/web/admin/students", json={
        "login": login, "surname": surname, "name": name, "group": group,
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text
    tok = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert tok.status_code == 200, tok.text
    return {"Authorization": f"Bearer {tok.json()['access_token']}", "X-Client": "web"}


def _push_lesson(client, admin, lesson_id, group, subject, ltype="Практика", number=1):
    r = client.post("/sync/push", json={"changes": {"lessons": [{
        "id": lesson_id, "group_name": group, "subject": subject, "type": ltype,
        "number": number, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    assert r.status_code == 200, r.text


def _ask(client, headers, message):
    r = client.post("/web/vector/ask", json={"message": message}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_student_sees_subject_without_any_lesson(client):
    """ГЛАВНАЯ регрессия: предмет есть в учебном плане группы, занятий по нему нет.

    Раньше он не попадал в ответ вообще (перечислялись только предметы с оценками),
    и человек делал вывод, что Вектор «не видит» его расписание предметов."""
    admin = make_admin(client)
    _group(client, admin, subjects=("Математика", "Физика", "История"))
    stud = _student(client, admin)
    #Занятие только по ОДНОМУ предмету — «Физика» и «История» живут лишь в плане группы.
    _push_lesson(client, admin, "L1", "ИС-21", "Математика")

    r = _ask(client, stud, "какие у меня предметы")
    assert r["intent"] == "subjects", r
    for subject in ("Математика", "Физика", "История"):
        assert subject in r["text"], f"предмет «{subject}» потерян: {r['text']}"
    assert r["facts"]["subjects"] == 3, r


def test_student_subjects_marks_those_without_grades(client):
    """Предметы без единой оценки названы отдельно — «есть, но пока пусто», а не молча."""
    admin = make_admin(client)
    _group(client, admin, subjects=("Математика", "Физика"))
    stud = _student(client, admin)
    _push_lesson(client, admin, "L1", "ИС-21", "Математика")
    client.post("/sync/push", json={"changes": {"grades": [
        {"id": "Иванова|Мария|L1", "student_f": "Иванова", "student_n": "Мария",
         "lesson_id": "L1", "grade": "5"}]}}, headers=admin)

    r = _ask(client, stud, "мои предметы")
    assert r["intent"] == "subjects", r
    assert "Пока без оценок" in r["text"], r["text"]
    assert r["facts"]["without_grades"] == 1, r


def test_student_without_subjects_gets_honest_answer(client):
    """Пустая группа — честное «не закреплены», а не выдуманный список."""
    admin = make_admin(client)
    _group(client, admin, subjects=())
    stud = _student(client, admin)

    r = _ask(client, stud, "какие у меня предметы")
    assert r["intent"] == "subjects", r
    assert r["facts"]["subjects"] == 0, r


def test_subjects_answer_is_never_voiced_by_llm(client, monkeypatch):
    """Перечень НАЗВАНИЙ в LLM не отдаём (§5): «озвучивая данные», модель переставляет и
    выдумывает предметы — ровно то, чего продукт обещает не делать."""
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "voice",
                        lambda cfg, text, role, question, locale="ru": "LLM_ОЗВУЧИЛ")
    admin = make_admin(client)
    _group(client, admin)
    stud = _student(client, admin)

    r = _ask(client, stud, "какие у меня предметы")
    assert r["text"] != "LLM_ОЗВУЧИЛ", r


def test_teacher_sees_own_assigned_subjects_not_whole_group(client):
    """У преподавателя «мои предметы» — это НАЗНАЧЕНИЯ (препод↔предмет↔группа), а не весь
    каталог группы: чужие предметы той же группы к его нагрузке отношения не имеют."""
    admin = make_admin(client)
    _group(client, admin, subjects=("Математика", "Физика"))
    th = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")

    r = _ask(client, th, "какие у меня предметы")
    assert r["intent"] == "subjects", r
    assert "Математика" in r["text"], r["text"]
    assert "Физика" not in r["text"], f"чужой предмет группы попал в ответ: {r['text']}"


def test_admin_sees_subject_catalog(client):
    """Админу — справочник предметов целиком (как и «Группы» рядом)."""
    admin = make_admin(client)
    r = client.post("/web/admin/subjects", json={"name": "Химия"}, headers=admin)
    assert r.status_code == 200, r.text

    r = _ask(client, admin, "какие есть предметы")
    assert r["intent"] == "subjects", r
    assert "Химия" in r["text"], r["text"]


def test_group_subject_list_merges_plan_and_lessons(client):
    """Сам источник (webdata.group_subject_list) — объединение плана и занятий без дублей."""
    from app import webdata as W
    from app.db import SessionLocal

    admin = make_admin(client)
    _group(client, admin, subjects=("Математика", "Физика"))
    _push_lesson(client, admin, "L1", "ИС-21", "Математика")   #уже есть в плане — не дубль
    _push_lesson(client, admin, "L2", "ИС-21", "Информатика")  #только в занятиях

    db = SessionLocal()
    try:
        assert W.group_subject_list(db, "ИС-21") == ["Информатика", "Математика", "Физика"]
    finally:
        db.close()
