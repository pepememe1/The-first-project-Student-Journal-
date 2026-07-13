"""
test_curator.py — Роль «Куратор» (teacher с непустым curated_groups).

Ключевой инвариант: куратор видит ВСЕ предметы своей курируемой группы (в т.ч. которые
сам НЕ ведёт), но ТОЛЬКО НА ЧТЕНИЕ, и строго по row-level (group ∈ curated_groups).
"""
from conftest import make_admin, make_teacher
from app.security import hash_password


def _push(client, h, **ent):
    return client.post("/sync/push", json={"changes": ent}, headers=h)


def _login(client, login, pw):
    r = client.post("/auth/login", json={"login": login, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_curator_sees_all_group_subjects_readonly(client):
    admin = make_admin(client)
    L_mat = {"id": "Lm", "group_name": "G1", "subject": "Мат", "type": "Практика", "number": 1}
    L_fiz = {"id": "Lf", "group_name": "G1", "subject": "Физ", "type": "Практика", "number": 1}
    stud = {"id": "stud:s1", "role": "student", "login": "s1", "surname": "Пуп",
            "name": "Пётр", "group_name": "G1", "password_hash": hash_password("p")}
    g_fiz = {"id": "Пуп|Пётр|Lf", "student_f": "Пуп", "student_n": "Пётр",
             "lesson_id": "Lf", "grade": "4"}
    assert _push(client, admin, lessons=[L_mat, L_fiz], users=[stud], grades=[g_fiz]).status_code == 200

    #Куратор ведёт только «Мат», но курирует всю группу G1
    r = client.post("/web/admin/teachers", json={
        "full_name": "Кур Атор", "login": "t1", "password": "pass1234",
        "subjects": ["Мат"], "curated_groups": ["G1"]}, headers=admin)
    assert r.status_code == 200, r.text
    th = _login(client, "t1", "pass1234")

    assert client.get("/web/curator/groups", headers=th).json()["groups"] == ["G1"]
    #видит и «Физ» — чужой для него предмет
    subs = client.get("/web/curator/group/G1/subjects", headers=th).json()["subjects"]
    assert "Мат" in subs and "Физ" in subs, subs
    #видит оценки по «Физ» (не свой предмет!) — чтение
    view = client.get("/web/curator/group/G1/subject/Физ", headers=th).json()
    assert any(st["grades"].get("Lf") == "4" for st in view["students"]), view
    #некурируемая группа → 403
    assert client.get("/web/curator/group/G2/subjects", headers=th).status_code == 403


def test_non_curator_teacher_has_no_curator_access(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    assert client.get("/web/curator/groups", headers=th).json()["groups"] == []
    #даже зная имя группы — 403 (не курирует)
    assert client.get("/web/curator/group/G1/subjects", headers=th).status_code == 403
