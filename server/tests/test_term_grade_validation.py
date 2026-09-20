"""
test_term_grade_validation.py — итоговая оценка проверяется по шкале (находка ревью
J09, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
`POST /web/teacher/term-grade` делал над присланным значением только `strip()` и
проверял непустоту. То есть прямой запрос записывал в зачётку ЛЮБУЮ строку — и она не
просто показывалась: наличие итоговой ЗАПИРАЕТ текущие оценки по предмету
(`_ensure_term_open`). Мусором закрывался семестр, а снять замок мог только тот, кто
догадается, что дело в итоговой.

⚠️ Выпадающий список на экране проверкой не является: тот же запрос уходит из десктопа,
из офлайн-очереди (`api/outbox.js`) и голосовой командой. Правило одно на продукт —
`grading.is_allowed_value`, то же, что у обычной оценки.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать вызов `is_allowed_value` в `termgrades.py` — краснеет
первый тест. Второй и третий остаются зелёными и стерегут от «починки», которая
запретила бы законные значения или снятие оценки.
"""
from conftest import make_admin, make_teacher
from app.security import hash_password

#⚠️ Термин БЕРЁМ ИЗ ПРОДУКТА, а не пишем числом (инвариант «тест, привязанный к
#календарю, протухает сам»): захардкоженный год краснеет ровно 1 сентября, вперемешку с
#настоящими падениями, а написанный «на будущее» — молча начинает проверять другой
#сценарий. Держит `tests/test_no_calendar_bound_tests.py`, он же это и поймал.
def _current_term():
    from app.db import SessionLocal
    from app.routers.web import _common as C
    db = SessionLocal()
    try:
        return C.W.current_term(C.W.load_config(db))
    finally:
        db.close()


YEAR, SEM = _current_term()
GROUP, SUBJ = "К-31", "Математика"


def _setup(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t_term", subjects=(SUBJ,))
    r = client.post("/sync/push", json={"changes": {
        "subject_hours": [{
            "id": f"hrs:{GROUP}|{SUBJ}|{YEAR}|{SEM}", "group_name": GROUP, "subject": SUBJ,
            "year": YEAR, "semester": SEM, "hours_total": 32, "teacher_id": "teach:t_term",
        }],
        "users": [{
            "id": "stud:term1", "role": "student", "login": "term1",
            "password_hash": hash_password("studpass1"),
            "surname": "Сидоров", "name": "Семён", "group_name": GROUP,
        }],
    }}, headers=admin)
    assert r.status_code == 200, r.text
    return admin, teacher


def _set(client, headers, grade):
    return client.post("/web/teacher/term-grade", json={
        "surname": "Сидоров", "name": "Семён", "subject": SUBJ, "group": GROUP,
        "grade": grade,
    }, headers=headers)


def test_arbitrary_text_is_refused_and_nothing_is_written(client):
    _, teacher = _setup(client)
    r = _set(client, teacher, "Ништяк")
    assert r.status_code == 400, f"мусор приняли как итоговую: {r.status_code} {r.text}"

    from app.db import SessionLocal
    from app.models import TermGrade
    db = SessionLocal()
    try:
        rows = db.query(TermGrade).filter(TermGrade.subject == SUBJ).all()
        assert not [x for x in rows if (x.grade or "") == "Ништяк"], \
            "отвергнутое значение всё равно записалось"
    finally:
        db.close()

    #И главное следствие: семестр не заперт — обычная оценка по-прежнему пишется.
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": "Практика", "number": 1,
        "date": "01.09.2026", "topic": "Тема",
    }, headers=teacher)
    assert r.status_code == 200, r.text
    lid = r.json()["id"]
    r = client.post("/web/teacher/grade", json={
        "lesson_id": lid, "surname": "Сидоров", "name": "Семён", "value": "4",
    }, headers=teacher)
    assert r.status_code == 200, f"мусорная итоговая заперла семестр: {r.text}"


def test_values_from_any_scale_are_accepted(client):
    """Пятибалльная и «Зачтено» — законные значения разных шкал, обе обязаны проходить."""
    _, teacher = _setup(client)
    assert _set(client, teacher, "5").status_code == 200
    assert _set(client, teacher, "Зачтено").status_code == 200


def test_empty_value_still_removes_the_term_grade(client):
    """Пустая строка — это СНЯТИЕ итоговой, единственная дверь наружу из замка."""
    _, teacher = _setup(client)
    assert _set(client, teacher, "5").status_code == 200
    r = _set(client, teacher, "")
    assert r.status_code == 200, f"снятие итоговой сломано: {r.text}"

    from app.db import SessionLocal
    from app.models import TermGrade
    db = SessionLocal()
    try:
        row = db.query(TermGrade).filter(TermGrade.subject == SUBJ).first()
        assert row is not None and row.deleted is True, "итоговая не снята"
    finally:
        db.close()
