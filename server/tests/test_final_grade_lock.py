"""
test_final_grade_lock.py — итоговая оценка закрывает семестр по предмету.

Требование Ярослава (28.08.2026): «если добавляем экзамен и выставляем оценку, появится
поле „итоговая оценка“, которая идёт в зачётку. Если это поле есть, то препод не сможет
новые ставить».

🔒 ПОЧЕМУ ЗАМОК НА СЕРВЕРЕ, А НЕ В ИНТЕРФЕЙСЕ. Итоговая уходит в зачётку, и балл,
дописанный ПОСЛЕ неё, меняет средний, по которому её и выводили: документ перестаёт
соответствовать журналу, и заметить это можно только сверив их вручную. Спрятать поле —
не защита: тот же запрос уходит из десктопа, из офлайн-очереди (`web/src/api/outbox.js`)
и голосовой командой. Проверка обязана стоять там, где пишут.

⚠️ Дверь наружу одна и она обязана быть: снять итоговую — семестр снова открыт. Замок
без выхода означал бы, что опечатка в оценке неисправима навсегда, и преподаватель
пошёл бы просить админа править базу руками.

⚠️ Обратный ход проверен откатом: убираю вызов `_ensure_term_open` из `teacher_set_grade`
— краснеют пять тестов этого файла.
"""
import pytest

from conftest import make_admin, make_teacher, assign_teacher
from app.security import hash_password

GROUP = "К-24"
SUBJ = "Математика"


def _student(client, admin, login="ivanov", surname="Иванов", name="Иван"):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("studpass1"),
        "full_name": f"{surname} {name}", "surname": surname, "name": name,
        "group_name": GROUP,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    return f"stud:{login}"


def _lesson(client, teacher, ltype="Практика", number=1, topic="Тема"):
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": ltype, "number": number,
        "topic": topic, "date": "01.09.2026",
    }, headers=teacher)
    assert r.status_code == 200, r.text
    return r.json().get("id") or r.json().get("lesson_id")


@pytest.fixture()
def cast(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="tprep", subjects=(SUBJ,))
    assign_teacher(client, admin, "teach:tprep", GROUP, SUBJ)
    sid = _student(client, admin)
    return {"admin": admin, "teacher": teacher, "student_id": sid}


def _set_grade(client, cast, lesson_id, value):
    return client.post("/web/teacher/grade", json={
        "surname": "Иванов", "name": "Иван", "lesson_id": lesson_id, "grade": value,
    }, headers=cast["teacher"])


def _set_final(client, cast, value, form="экзамен"):
    return client.post("/web/teacher/term-grade", json={
        "group": GROUP, "subject": SUBJ, "surname": "Иванов", "name": "Иван",
        "grade": value, "form": form,
    }, headers=cast["teacher"])


# ── замок ───────────────────────────────────────────────────────────────────────────

def test_grades_are_writable_while_the_term_is_open(client, cast):
    """Опорная точка: без итоговой всё работает как раньше."""
    lid = _lesson(client, cast["teacher"])
    assert _set_grade(client, cast, lid, "4").status_code == 200


def test_final_grade_closes_the_subject_for_new_marks(client, cast):
    lid = _lesson(client, cast["teacher"])
    assert _set_grade(client, cast, lid, "4").status_code == 200
    assert _set_final(client, cast, "5").status_code == 200

    lid2 = _lesson(client, cast["teacher"], number=2)
    r = _set_grade(client, cast, lid2, "3")
    assert r.status_code == 409, r.text
    # Отказ обязан ОБЪЯСНЯТЬ и называть выход: иначе преподаватель решит, что сломалось.
    assert "итогова" in r.json()["detail"].lower()
    assert "снимите" in r.json()["detail"].lower()


def test_existing_marks_are_locked_too(client, cast):
    """Не только новые: исправление уже стоящей оценки тоже меняет средний."""
    lid = _lesson(client, cast["teacher"])
    _set_grade(client, cast, lid, "4")
    _set_final(client, cast, "5")
    assert _set_grade(client, cast, lid, "2").status_code == 409


def test_attendance_is_locked_as_well(client, cast):
    """⚠️ Осознанно: «Н»/«Б» входят в тот же расчёт (пропуски, допуск).

    Полузакрытый семестр — оценки заперты, а пропуски дописываются — худший вариант:
    зачётка расходится с журналом молча и по другой причине."""
    lid = _lesson(client, cast["teacher"])
    _set_final(client, cast, "5")
    assert _set_grade(client, cast, lid, "Н").status_code == 409


def test_clearing_the_final_grade_reopens_the_term(client, cast):
    """Единственная дверь наружу. Без неё опечатка неисправима навсегда."""
    lid = _lesson(client, cast["teacher"])
    _set_final(client, cast, "5")
    assert _set_grade(client, cast, lid, "4").status_code == 409

    assert _set_final(client, cast, "").status_code == 200      # снять итоговую
    assert _set_grade(client, cast, lid, "4").status_code == 200


def test_the_lock_is_personal_not_group_wide(client, cast):
    """У соседа по группе итоговой ещё нет — его журнал закрывать не за что."""
    _student(client, cast["admin"], login="petrov", surname="Петров", name="Пётр")
    lid = _lesson(client, cast["teacher"])
    _set_final(client, cast, "5")                                # закрыли Иванова
    r = client.post("/web/teacher/grade", json={
        "surname": "Петров", "name": "Пётр", "lesson_id": lid, "grade": "4",
    }, headers=cast["teacher"])
    assert r.status_code == 200, r.text


def test_the_lock_belongs_to_one_subject(client, cast):
    """Закрытая математика не запирает физику: аттестация идёт предмет за предметом."""
    other = "Физика"
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "teach:tprep", "role": "teacher", "login": "tprep",
        "subjects": [SUBJ, other],
    }]}}, headers=cast["admin"])
    assert r.status_code == 200, r.text
    assign_teacher(client, cast["admin"], "teach:tprep", GROUP, other)

    lid_math = _lesson(client, cast["teacher"])
    _set_final(client, cast, "5")
    assert _set_grade(client, cast, lid_math, "4").status_code == 409

    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": other, "type": "Практика", "number": 1,
        "topic": "Тема", "date": "01.09.2026"}, headers=cast["teacher"])
    assert r.status_code == 200, r.text
    lid_phys = r.json().get("id") or r.json().get("lesson_id")
    assert _set_grade(client, cast, lid_phys, "4").status_code == 200


def test_a_removed_final_grade_is_not_a_lock(client, cast):
    """Надгробие (снятая итоговая) семестр не закрывает — иначе выход не работал бы."""
    lid = _lesson(client, cast["teacher"])
    _set_final(client, cast, "5")
    _set_final(client, cast, "")
    # Повторное снятие ничего не ломает, и запись по-прежнему открыта.
    assert _set_final(client, cast, "").status_code == 200
    assert _set_grade(client, cast, lid, "5").status_code == 200
