"""
test_sync_scope_of_existing_row.py — синк проверяет права по СУЩЕСТВУЮЩЕЙ записи,
а не только по присланной (находка ревью J05, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
`/sync/push` спрашивал `_teacher_may_write` про поля ВХОДЯЩЕГО элемента и делал это ДО
того, как доставал запись из базы. Пока строка создаётся, этого достаточно. Но у
существующей строки правило читалось наоборот: преподаватель, знающий id чужого
занятия, присылал этот id со СВОЕЙ разрешённой парой (группа, предмет) — проверка
смотрела на присланное, соглашалась, и дальше эти же поля записывались в чужую строку.
Чужое занятие «переезжало» к отправителю вместе с привязанными оценками.

━━ ПОЧЕМУ ПРОВЕРОК ДВЕ, А НЕ ОДНА ━━
Проверять только существующую мало: тогда своё занятие можно было бы перенести в чужую
группу. Поэтому спрашиваем про обе области — откуда берём и куда кладём.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: если убрать блок проверки существующей записи в
`routers/sync.py`, краснеют первые два теста (угон занятия и угон оценки). Третий
(законная правка своего) остаётся зелёным — он и стережёт от «починки», которая просто
запрещает всё подряд.
"""
from conftest import make_admin, make_teacher


#⚠️ Термин БЕРЁМ ИЗ ПРОДУКТА, а не пишем числом (инвариант «тест, привязанный к
#календарю, протухает сам»): захардкоженный год краснеет ровно 1 сентября, вперемешку с
#настоящими падениями. Держит `tests/test_no_calendar_bound_tests.py`.
def _current_term():
    from app.db import SessionLocal
    from app.routers.web import _common as C
    db = SessionLocal()
    try:
        return C.W.current_term(C.W.load_config(db))
    finally:
        db.close()


YEAR, SEM = _current_term()


def _lesson(lid, group, subject, topic="Тема"):
    return {"id": lid, "group_name": group, "subject": subject, "type": "Лекция",
            "number": 1, "date": "01.09.2026", "topic": topic,
            "year": YEAR, "semester": SEM}


def _assign(client, admin, group, subject, teacher_id):
    """Назначение преподавателя на пару (группа, предмет) — источник прав в синке."""
    r = client.post("/sync/push", json={"changes": {"subject_hours": [{
        "id": f"hrs:{group}|{subject}|{YEAR}|{SEM}", "group_name": group,
        "subject": subject, "year": YEAR, "semester": SEM,
        "hours_total": 32, "teacher_id": teacher_id,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text


def test_foreign_lesson_cannot_be_hijacked_by_sending_own_pair(client):
    """Чужое занятие не переезжает к тому, кто прислал его id со своей парой."""
    admin = make_admin(client)
    mine = make_teacher(client, admin, login="t_mine", subjects=("Математика",))
    _assign(client, admin, "К-11", "Математика", "teach:t_mine")

    #Чужое занятие заводит администратор: оно принадлежит другой группе и предмету.
    r = client.post("/sync/push", json={"changes": {"lessons": [
        _lesson("les-foreign", "К-99", "Физика", topic="Чужая тема")]}}, headers=admin)
    assert r.status_code == 200, r.text

    #Атака: тот же id, но поля — свои разрешённые.
    r = client.post("/sync/push", json={"changes": {"lessons": [
        _lesson("les-foreign", "К-11", "Математика", topic="Угон")]}}, headers=mine)
    assert r.status_code == 200, r.text
    assert (r.json().get("rejected") or {}).get("lessons"), \
        "подмена области чужого занятия обязана попасть в rejected"

    #Запись в базе не изменилась ни одним полем.
    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        row = db.get(Lesson, "les-foreign")
        assert row.group_name == "К-99" and row.subject == "Физика", "занятие угнали"
        assert row.topic == "Чужая тема", "тему чужого занятия переписали"
    finally:
        db.close()


def test_foreign_grade_cannot_be_rewritten_through_own_lesson_id(client):
    """Оценка, лежащая на чужом занятии, не меняется присылкой своего lesson_id.

    Тот же механизм, что у занятия, но по другой карте прав: у оценки область берётся
    из занятия, на которое она ссылается."""
    admin = make_admin(client)
    mine = make_teacher(client, admin, login="t_mine2", subjects=("Математика",))
    _assign(client, admin, "К-11", "Математика", "teach:t_mine2")

    r = client.post("/sync/push", json={"changes": {
        "lessons": [_lesson("les-foreign2", "К-99", "Физика"),
                    _lesson("les-own2", "К-11", "Математика")],
        "grades": [{"id": "gr-foreign", "lesson_id": "les-foreign2",
                    "student_f": "Иванов", "student_n": "Иван", "grade": "3"}],
    }}, headers=admin)
    assert r.status_code == 200, r.text

    #Атака: существующая оценка лежит на чужом занятии, но присылаем своё занятие.
    r = client.post("/sync/push", json={"changes": {"grades": [
        {"id": "gr-foreign", "lesson_id": "les-own2",
         "student_f": "Иванов", "student_n": "Иван", "grade": "5"}]}}, headers=mine)
    assert r.status_code == 200, r.text

    from app.db import SessionLocal
    from app.models import Grade
    db = SessionLocal()
    try:
        row = db.get(Grade, "gr-foreign")
        assert row is not None and row.grade == "3", "чужую оценку переписали"
        assert row.lesson_id == "les-foreign2", "чужую оценку перенесли на своё занятие"
    finally:
        db.close()


def test_teacher_still_edits_his_own_lesson(client):
    """Законная правка СВОЕГО занятия проходит — иначе «починка» просто всё запретила."""
    admin = make_admin(client)
    mine = make_teacher(client, admin, login="t_mine3", subjects=("Математика",))
    _assign(client, admin, "К-11", "Математика", "teach:t_mine3")

    r = client.post("/sync/push", json={"changes": {"lessons": [
        _lesson("les-own3", "К-11", "Математика", topic="Было")]}}, headers=mine)
    assert r.status_code == 200, r.text

    r = client.post("/sync/push", json={"changes": {"lessons": [
        _lesson("les-own3", "К-11", "Математика", topic="Стало")]}}, headers=mine)
    assert r.status_code == 200, r.text
    assert not (r.json().get("rejected") or {}).get("lessons"), \
        "правка собственного занятия не должна отвергаться"

    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        assert db.get(Lesson, "les-own3").topic == "Стало"
    finally:
        db.close()
