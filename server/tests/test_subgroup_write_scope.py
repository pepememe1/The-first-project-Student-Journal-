"""
test_subgroup_write_scope.py — запись уважает подгруппу так же, как чтение
(находка ревью J07, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
При РАЗДЕЛЬНОМ обучении пара (группа, предмет) назначена обоим преподавателям сразу —
они ведут разные половины группы. `_teacher_check_assignment` отвечает на вопрос «твоя
ли пара» и обоим говорит «да». Чтение это учитывало (`teacher.py` фильтрует занятия по
`teacher_owned_subgroups`), а запись — нет: зная id занятия соседней подгруппы,
преподаватель ставил там оценки, менял тему и удалял колонку. Ограничение действовало
ровно до тех пор, пока человек пользовался интерфейсом.

━━ ГРАНИЦА, КОТОРУЮ ДЕРЖИТ ПОСЛЕДНИЙ ТЕСТ ━━
Занятие «Совместно» (subgroup = 0) не ограничивается: такие занятия есть и у тех, кто
ведёт одну подгруппу (заведены до разделения или администратором), и запрет отнял бы у
преподавателя его собственный журнал.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `_teacher_check_subgroup` из `write.py` — краснеют три
первых теста; оставить проверку, но снять условие `sub not in (1, 2)` (то есть начать
ограничивать и «Совместно») — краснеет четвёртый.
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


def _split_pair(client, admin, group="К-21", subject="Математика",
                t1="teach:sub_one", t2="teach:sub_two"):
    """Пара с РАЗДЕЛЬНЫМ обучением: подгруппу 1 ведёт t1, подгруппу 2 — t2."""
    r = client.post("/sync/push", json={"changes": {"subject_hours": [{
        "id": f"hrs:{group}|{subject}|{YEAR}|{SEM}", "group_name": group,
        "subject": subject, "year": YEAR, "semester": SEM, "hours_total": 32,
        "split": True, "teacher_id": t1, "teacher_id_2": t2,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text


def _lesson(client, headers, group="К-21", subject="Математика", subgroup=1, number=1):
    r = client.post("/web/teacher/lesson", json={
        "group": group, "subject": subject, "type": "Практика",
        "number": number, "date": "01.09.2026", "topic": "Было", "subgroup": subgroup,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _student(client, admin, login="stud_sub", surname="Петров", name="Пётр", group="К-21"):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("studpass1"),
        "surname": surname, "name": name, "group_name": group,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text


def _setup(client):
    admin = make_admin(client)
    one = make_teacher(client, admin, login="sub_one", subjects=("Математика",))
    two = make_teacher(client, admin, login="sub_two", subjects=("Математика",))
    _split_pair(client, admin)
    return admin, one, two


def test_teacher_cannot_grade_on_the_other_subgroups_lesson(client):
    admin, one, two = _setup(client)
    _student(client, admin)
    lid = _lesson(client, two, subgroup=2)          #занятие ЧУЖОЙ (второй) подгруппы

    r = client.post("/web/teacher/grade", json={
        "lesson_id": lid, "surname": "Петров", "name": "Пётр", "value": "5",
    }, headers=one)
    assert r.status_code == 403, f"оценка в чужую подгруппу прошла: {r.status_code} {r.text}"


def test_teacher_cannot_edit_the_other_subgroups_lesson(client):
    admin, one, two = _setup(client)
    lid = _lesson(client, two, subgroup=2)

    r = client.put(f"/web/teacher/lesson/{lid}", json={"topic": "Угон"}, headers=one)
    assert r.status_code == 403, r.text


def test_teacher_cannot_delete_the_other_subgroups_lesson(client):
    admin, one, two = _setup(client)
    lid = _lesson(client, two, subgroup=2)

    r = client.delete(f"/web/teacher/lesson/{lid}", headers=one)
    assert r.status_code == 403, r.text

    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        assert db.get(Lesson, lid).deleted is False, "чужое занятие удалили"
    finally:
        db.close()


def test_own_subgroup_and_joint_lesson_stay_editable(client):
    """Своя подгруппа и «Совместно» правятся как раньше — защита не должна запирать своё."""
    admin, one, two = _setup(client)
    mine = _lesson(client, one, subgroup=1, number=1)
    r = client.put(f"/web/teacher/lesson/{mine}", json={"topic": "Стало"}, headers=one)
    assert r.status_code == 200, f"своя подгруппа обязана правиться: {r.text}"

    #«Совместно» заводит администратор напрямую — так бывает у занятий, созданных
    #до разделения; преподаватель одной подгруппы обязан их сохранить.
    r = client.post("/sync/push", json={"changes": {"lessons": [{
        "id": "les-joint", "group_name": "К-21", "subject": "Математика",
        "type": "Лекция", "number": 9, "date": "02.09.2026", "topic": "Общая",
        "year": YEAR, "semester": SEM, "subgroup": 0,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.put("/web/teacher/lesson/les-joint", json={"topic": "Общая, правка"},
                   headers=one)
    assert r.status_code == 200, f"«Совместно» не должно запираться: {r.text}"
