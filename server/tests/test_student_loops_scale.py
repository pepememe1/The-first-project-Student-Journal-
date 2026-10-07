# -*- coding: utf-8 -*-
"""
test_student_loops_scale.py — цикл по студентам не перечитывает на каждого то, что
одинаково для всей группы (07.10.2026).

━━ ЧТО БЫЛО ━━
`webdata.lesson_scale_map` читает ВСЕ назначения семестра по всему колледжу (кто какой
предмет ведёт и какой шкалой ставит) — и звалась дважды на каждого студента: в цикле по
группе и ещё раз внутри расчёта риска отчисления. Рядом на каждого студента заново
читались id всех занятий группы и сам студент по ФИО. Цена росла как «студенты ×
назначения колледжа». Замер на выдуманном колледже (60 групп, 1500 студентов):

    главная преподавателя с 12 группами   1954 мс, 1699 запросов  →  216 мс, 414
    «сводка по группам» у администратора  17.6 с,  9311 запросов  →  2.8 с, 1873
    список риска группы у куратора         150 мс,  128 запросов  →   34 мс,  31

На бою этого не видно — там 29 человек; увидели бы в день переезда на колледж целиком.

━━ ПОЧЕМУ ТЕСТ СЧИТАЕТ ЗАПРОСЫ, А НЕ ВРЕМЯ ━━
Время зависит от машины и мигает; число запросов — нет. Свойство одно и общее для всех
пяти мест: ДОБАВИЛИ СТУДЕНТОВ — число чтений назначений семестра НЕ ВЫРОСЛО, а запросов
на каждого нового студента — не больше одного (его оценки). Новое место с тем же
дефектом сюда дописывают строкой в `PAGES`.
"""
import pytest
from sqlalchemy import event

from conftest import assign_teacher, make_admin, make_teacher

G = "К74/1"
SUBJECTS = ["Математика", "Физика"]


def _push(client, admin, changes):
    r = client.post("/sync/push", json={"changes": changes}, headers=admin)
    assert r.status_code == 200, r.text


def _students(first: int, count: int) -> tuple:
    users, grades = [], []
    for i in range(first, first + count):
        sid = f"stud:s{i}"
        users.append({"id": sid, "role": "student", "login": f"s{i}", "surname": f"Студентов{i}",
                      "name": "Пётр Петрович", "group_name": G})
        for lid, mark in (("m1", "4"), ("m2", "Н"), ("f1", "5")):
            grades.append({"id": f"{sid}|{lid}", "student_id": sid, "student_f": f"Студентов{i}",
                           "student_n": "Пётр Петрович", "lesson_id": lid, "grade": mark})
    return users, grades


@pytest.fixture()
def college(client):
    from app.db import default_term
    ty, ts = default_term()
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="semenova", subjects=SUBJECTS)
    users, grades = _students(0, 3)
    _push(client, admin, {
        "groups": [{"id": "grp:1", "name": G, "subjects": SUBJECTS}],
        "users": users + [{"id": "teach:semenova", "role": "teacher", "login": "semenova",
                           "full_name": "Семёнова Анна", "subjects": SUBJECTS,
                           "curated_groups": [G]}],
        "lessons": [{"id": lid, "group_name": G, "subject": s, "type": "Практика", "number": n,
                     "topic": "Тема", "date": "07.09.2026", "year": ty, "semester": ts}
                    for lid, s, n in (("m1", "Математика", 1), ("m2", "Математика", 2),
                                      ("f1", "Физика", 1))],
        "grades": grades})
    for subject in SUBJECTS:
        assign_teacher(client, admin, "teach:semenova", G, subject, year=ty, semester=ts)
    for name in SUBJECTS:
        assert client.post("/web/admin/subjects", json={"name": name},
                           headers=admin).status_code == 200
    return {"client": client, "admin": admin, "teacher": teacher}


#Подпись, сколько раз страница проходит по группе, запрос. Каждая строка — место, где
#идут циклом по студентам. У главной преподавателя проходов два: группа показана и как
#«веду», и как «курирую» — это два разных набора предметов, а не повтор.
PAGES = [
    ("главная преподавателя", 2,
     lambda c, w: c.get("/web/teacher/summary", headers=w["teacher"])),
    ("список студентов группы", 1,
     lambda c, w: c.get("/web/teacher/students", params={"group": G}, headers=w["teacher"])),
    ("риск группы у куратора", 1,
     lambda c, w: c.get("/web/curator/risk", params={"group": G}, headers=w["teacher"])),
    ("Вектор преподавателя", 1,
     lambda c, w: c.post("/web/vector/ask", headers=w["teacher"],
                         json={"message": "сводка по группам"})),
    ("Вектор администратора", 1,
     lambda c, w: c.post("/web/vector/ask", headers=w["admin"],
                         json={"message": "сводка по группам"})),
    ("Вектор администратора по предмету", 1,
     lambda c, w: c.post("/web/vector/ask", headers=w["admin"],
                         json={"message": "средний балл по математике"})),
]


def _count(world, call) -> tuple:
    """(всего запросов, из них чтений назначений семестра) за один вызов страницы."""
    from app.db import engine
    seen = []

    def spy(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        r = call(world["client"], world)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert r.status_code == 200, r.text
    terms = [s for s in seen if "FROM subject_hours" in s and "subject_hours.teacher_id_2" in s]
    return len(seen), len(terms), r.json()


def test_adding_students_does_not_add_reads_of_the_whole_term(college):
    client, admin = college["client"], college["admin"]
    small = {name: _count(college, call) for name, _passes, call in PAGES}
    users, grades = _students(3, 12)                    #было 3 студента, стало 15
    _push(client, admin, {"users": users, "grades": grades})
    big = {name: _count(college, call) for name, _passes, call in PAGES}
    for name, passes, _call in PAGES:
        total_s, terms_s, _ = small[name]
        total_b, terms_b, _ = big[name]
        assert terms_s >= 1, f"{name}: назначения семестра не читались вовсе — тест ослеп"
        assert terms_b == terms_s, (
            f"{name}: чтений назначений семестра было {terms_s}, с двенадцатью новыми "
            f"студентами стало {terms_b} — что-то читается на каждого студента")
        #Один запрос на студента — его оценки. Второй (id занятий группы для отсева
        #тёзок, поиск самого студента по ФИО) — уже то, что читается раз на группу.
        assert total_b - total_s <= 12 * passes, (
            f"{name}: на 12 новых студентов прибавилось {total_b - total_s} запросов "
            f"(ждали не больше {12 * passes}: один на студента за проход — его оценки)")


def test_the_numbers_did_not_change(college):
    """Память прохода — про число запросов, а не про ответ: цифры те же, что считаются
    без неё (тем же расчётом, по одному студенту)."""
    from app import webdata as W
    from app.db import SessionLocal
    client = college["client"]
    summary = client.get("/web/teacher/summary", headers=college["teacher"]).json()
    risk = client.get("/web/curator/risk", params={"group": G}, headers=college["teacher"]).json()
    db = SessionLocal()
    try:
        cfg = W.load_config(db)
        lessons = W.current_term_lessons(db, G, W.group_lessons(db, G), cfg)
        plain = {}
        for s in W.students_in_group(db, G):
            recs = W.student_records(db, s.surname, s.name, G, student_id=s.id)
            plain[s.id] = (W.average(lessons, recs, cfg, scale=W.lesson_scale_map(db, lessons)),
                           W.dropout_risk_for_student(db, s.surname, s.name, G, cfg=cfg,
                                                      lessons=lessons, records=recs))
        report = {r["student_id"]: r["risk"] for r in W.group_risk_report(db, G)}
    finally:
        db.close()
    assert len(plain) == 3
    for sid, (average, risk_plain) in plain.items():
        assert average == 3.67                       #4, «Н» как 2.0 и 5 — на троих одинаково
        assert report[sid] == risk_plain, sid
    group = summary["groups"][0]
    assert (group["students"], group["average"]) == (3, 3.67)
    assert isinstance(risk, dict)


def test_the_pass_memory_is_never_shared_behind_the_callers_back(college):
    """Память — ЯВНЫЙ словарь вызывающего, а не сессии или модуля. Ручка, сменившая
    шкалу, обязана тут же увидеть новую (инвариант §4.29) — и без словаря видит."""
    from app import webdata as W
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        lessons = W.group_lessons(db, G)
        cache = {}
        before = W.lesson_scale_map(db, lessons, cache=cache)
        assert set(before.values()) == {"5"} and len(cache) == 1
        teacher = db.get(User, "teach:semenova")
        teacher.prefs = dict(teacher.prefs or {}, grading_scale="100")
        db.commit()
        #Тот же словарь — тот же проход: значения прежние, это и есть его смысл…
        assert W.lesson_scale_map(db, lessons, cache=cache) == before
        #…а без словаря и с новым словарём шкала уже новая.
        assert set(W.lesson_scale_map(db, lessons).values()) == {"100"}
        assert set(W.lesson_scale_map(db, lessons, cache={}).values()) == {"100"}
    finally:
        db.close()
