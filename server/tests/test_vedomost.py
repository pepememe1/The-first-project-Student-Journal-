"""
test_vedomost.py — Итоговые оценки за семестр (TermGrade) + ведомость (xlsx).
"""
from conftest import make_admin, make_teacher
from app.security import hash_password


def _push(client, h, **ent):
    return client.post("/sync/push", json={"changes": ent}, headers=h)


def test_term_grade_and_vedomost(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    stud = {"id": "stud:s1", "role": "student", "login": "s1", "surname": "Пуп",
            "name": "Пётр", "group_name": "G1", "password_hash": hash_password("p")}
    assert _push(client, admin, users=[stud]).status_code == 200

    #итоговая за семестр по своему предмету
    r = client.post("/web/teacher/term-grade", json={
        "group": "G1", "subject": "Мат", "surname": "Пуп", "name": "Пётр",
        "grade": "5", "form": "экзамен"}, headers=th)
    assert r.status_code == 200, r.text
    tg = client.get("/web/teacher/term-grades",
                    params={"group": "G1", "subject": "Мат"}, headers=th).json()
    assert tg["grades"].get("Пуп|Пётр", {}).get("grade") == "5", tg

    #ведомость: xlsx-байты (zip -> начинается с PK)
    v = client.get("/web/teacher/vedomost.xlsx",
                   params={"group": "G1", "subject": "Мат", "form": "экзамен"}, headers=th)
    assert v.status_code == 200, v.text
    assert v.headers["content-type"].startswith(
        "application/vnd.openxmlformats"), v.headers
    assert v.content[:2] == b"PK" and len(v.content) > 2000

    #чужой предмет — 403
    assert client.post("/web/teacher/term-grade", json={
        "group": "G1", "subject": "Физ", "surname": "Пуп", "name": "Пётр",
        "grade": "4"}, headers=th).status_code == 403
