"""
test_vedomost.py — Итоговые оценки (TermGrade) + экспорт журнала и ведомости в
двух форматах (xlsx/docx), единый стиль TNR 14 ч/б.
"""
from conftest import make_admin, make_teacher, assign_teacher
from app.security import hash_password

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _push(client, h, **ent):
    return client.post("/sync/push", json={"changes": ent}, headers=h)


def test_term_grade_and_exports_both_formats(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    assign_teacher(client, admin, "teach:teacher1", "G1", "Мат")
    L = {"id": "L1", "group_name": "G1", "subject": "Мат", "type": "Практика", "number": 1}
    stud = {"id": "stud:s1", "role": "student", "login": "s1", "surname": "Пуп",
            "name": "Пётр", "group_name": "G1", "password_hash": hash_password("p")}
    assert _push(client, admin, lessons=[L], users=[stud]).status_code == 200

    r = client.post("/web/teacher/term-grade", json={
        "group": "G1", "subject": "Мат", "surname": "Пуп", "name": "Пётр",
        "grade": "5", "form": "экзамен"}, headers=th)
    assert r.status_code == 200, r.text
    tg = client.get("/web/teacher/term-grades",
                    params={"group": "G1", "subject": "Мат"}, headers=th).json()
    assert tg["grades"].get("Пуп|Пётр", {}).get("grade") == "5", tg

    # Ведомость — xlsx и docx
    vx = client.get("/web/teacher/vedomost", params={"group": "G1", "subject": "Мат", "form": "экзамен", "fmt": "xlsx"}, headers=th)
    assert vx.status_code == 200 and vx.headers["content-type"].startswith(_XLSX)
    assert vx.content[:2] == b"PK" and len(vx.content) > 2000
    vd = client.get("/web/teacher/vedomost", params={"group": "G1", "subject": "Мат", "form": "экзамен", "fmt": "docx"}, headers=th)
    assert vd.status_code == 200 and vd.headers["content-type"].startswith(_DOCX)
    assert vd.content[:2] == b"PK" and len(vd.content) > 2000

    # Журнал — xlsx и docx
    jx = client.get("/web/teacher/journal-export", params={"group": "G1", "subject": "Мат", "fmt": "xlsx"}, headers=th)
    assert jx.status_code == 200 and jx.headers["content-type"].startswith(_XLSX)
    assert jx.content[:2] == b"PK"
    jd = client.get("/web/teacher/journal-export", params={"group": "G1", "subject": "Мат", "fmt": "docx"}, headers=th)
    assert jd.status_code == 200 and jd.headers["content-type"].startswith(_DOCX)
    assert jd.content[:2] == b"PK"

    # чужой предмет — 403
    assert client.post("/web/teacher/term-grade", json={
        "group": "G1", "subject": "Физ", "surname": "Пуп", "name": "Пётр",
        "grade": "4"}, headers=th).status_code == 403
