"""
test_student_without_login_admin.py — студента без логина администратор может изменить и
удалить (§4.10: такой студент живёт под id `stud:u:{uuid}`).

Раньше ключ правки собирался как `stud:{login}` из пустого логина: окно правки на сайте
открывалось как «Добавить студента», а сохранить и удалить такого студента было нельзя
(живой прогон 27.10.2026). Теперь клиент передаёт `sid`; принимается он только в виде
`stud:u:…`, чтобы через него нельзя было дотянуться до учётной записи с логином.
"""
from conftest import make_admin

SID = "stud:u:7f3c2a10-0000-4000-8000-000000000001"


def _seed_student_without_login(group="К64/2"):
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        db.add(User(id=SID, login="", role="student", surname="Егорова", name="Вера Викторовна",
                    group_name=group, updated_at="2026-10-27T00:00:00+00:00"))
        db.commit()
    finally:
        db.close()


def _row(sid=SID):
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        u = db.get(User, sid)
        return None if u is None else (u.surname, u.group_name, bool(u.deleted))
    finally:
        db.close()


def test_student_without_login_is_edited_by_sid(client):
    admin = make_admin(client)
    _seed_student_without_login()
    r = client.put("/web/admin/students/-", params={"sid": SID},
                   json={"surname": "Егорова-Ким", "group": "К74/1"}, headers=admin)
    assert r.status_code == 200, r.text
    assert _row() == ("Егорова-Ким", "К74/1", False)


def test_student_without_login_is_deleted_by_sid(client):
    admin = make_admin(client)
    _seed_student_without_login()
    r = client.delete("/web/admin/students/-", params={"sid": SID}, headers=admin)
    assert r.status_code == 200, r.text
    assert _row()[2] is True


def test_sid_cannot_reach_an_account_with_a_login(client):
    admin = make_admin(client)
    r = client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "К64/2",
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text
    for sid in ("stud:ivanova", "admin:admin", "teach:x"):
        r = client.put("/web/admin/students/-", params={"sid": sid},
                       json={"surname": "Взлом"}, headers=admin)
        assert r.status_code == 400, (sid, r.text)
    assert _row("stud:ivanova")[0] == "Иванова"
