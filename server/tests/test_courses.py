"""
test_courses.py — учебные курсы (routers/web/courses.py).

Главное, что здесь держится, — СКОУП ПО РОЛЯМ: студент видит курсы только своей группы,
преподаватель — только свои (автор/назначение), чужой студент получает 403 и на список,
и на деталь. Это тот же класс инварианта, что у оценок/синка: «по умолчанию отдать всё»
здесь означало бы показать чужие учебные материалы.
"""
from conftest import make_admin, make_teacher, assign_teacher


def _make_student(client, admin_headers, login="stud1", password="studpass1", group="К74-1"):
    from app.security import hash_password
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password(password), "full_name": "Иван Иванов",
        "surname": "Иванов", "name": "Иван", "group_name": group,
    }]}}, headers=admin_headers)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _new_course(client, teacher_headers, title="Основы алгоритмизации",
                subject="Математика", group="К74-1"):
    r = client.post("/web/courses", json={"title": title, "subject": subject, "group_name": group},
                    headers=teacher_headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_teacher_creates_course_by_own_assignment(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "К74-1", "Математика")
    cid = _new_course(client, teacher)
    # автор виден, счётчики нулевые
    r = client.get("/web/courses", headers=teacher)
    assert r.status_code == 200
    course = next(c for c in r.json()["courses"] if c["id"] == cid)
    assert course["authors"] and "Преподаватель" in course["authors"][0]
    assert course["materials_count"] == 0 and course["assignments_count"] == 0


def test_teacher_cannot_create_for_unassigned_pair(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "К74-1", "Математика")
    # предмет назначен, а группа чужая → 403
    r = client.post("/web/courses", json={"title": "X", "subject": "Математика", "group_name": "К99-9"},
                    headers=teacher)
    assert r.status_code == 403


def test_student_sees_only_own_group_course(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "К74-1", "Математика")
    cid = _new_course(client, teacher, group="К74-1")

    mine = _make_student(client, admin, login="s_in", group="К74-1")
    other = _make_student(client, admin, login="s_out", group="К99-9")

    # свой студент видит курс и открывает деталь
    r = client.get("/web/courses", headers=mine)
    assert any(c["id"] == cid for c in r.json()["courses"])
    assert client.get(f"/web/courses/{cid}", headers=mine).status_code == 200

    # чужой студент — пустой список И 403 на деталь (главный инвариант)
    r = client.get("/web/courses", headers=other)
    assert r.json()["courses"] == []
    assert client.get(f"/web/courses/{cid}", headers=other).status_code == 403


def test_student_cannot_create_or_edit(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "К74-1", "Математика")
    cid = _new_course(client, teacher)
    stud = _make_student(client, admin, group="К74-1")
    assert client.post("/web/courses", json={"title": "Y", "group_name": "К74-1"},
                       headers=stud).status_code == 403
    assert client.post(f"/web/courses/{cid}/sections", json={"title": "Раздел"},
                       headers=stud).status_code == 403


def test_sections_materials_assignments_flow(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "К74-1", "Математика")
    cid = _new_course(client, teacher)

    sid = client.post(f"/web/courses/{cid}/sections",
                      json={"title": "Введение", "position": 1}, headers=teacher).json()["id"]
    client.post(f"/web/courses/{cid}/materials",
                json={"title": "Учебник", "url": "https://example.org/book", "section_id": sid},
                headers=teacher)
    client.post(f"/web/courses/{cid}/assignments",
                json={"title": "Лабораторная 1", "due_date": "01.10.2026"}, headers=teacher)

    d = client.get(f"/web/courses/{cid}", headers=teacher).json()
    assert d["can_edit"] is True
    assert len(d["sections"]) == 1 and d["sections"][0]["title"] == "Введение"
    assert len(d["sections"][0]["materials"]) == 1
    assert d["sections"][0]["materials"][0]["url"] == "https://example.org/book"
    assert len(d["assignments"]) == 1
    assert d["assignments"][0]["teacher_name"].startswith("Преподаватель")

    # счётчики в списке подхватились
    course = next(c for c in client.get("/web/courses", headers=teacher).json()["courses"]
                  if c["id"] == cid)
    assert course["materials_count"] == 1 and course["assignments_count"] == 1


def test_link_material_requires_url(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "К74-1", "Математика")
    cid = _new_course(client, teacher)
    r = client.post(f"/web/courses/{cid}/materials", json={"title": "Пусто", "kind": "link"},
                    headers=teacher)
    assert r.status_code == 400


def test_archive_hides_course_from_student(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "К74-1", "Математика")
    cid = _new_course(client, teacher)
    stud = _make_student(client, admin, group="К74-1")
    assert any(c["id"] == cid for c in client.get("/web/courses", headers=stud).json()["courses"])
    # автор архивирует
    assert client.delete(f"/web/courses/{cid}", headers=teacher).status_code == 200
    # у студента пропал из списка и деталь закрылась
    assert client.get("/web/courses", headers=stud).json()["courses"] == []
    assert client.get(f"/web/courses/{cid}", headers=stud).status_code == 403
    # админ видит с include_archived
    r = client.get("/web/courses", params={"include_archived": "true"}, headers=admin)
    assert any(c["id"] == cid for c in r.json()["courses"])


def test_groupless_student_does_not_see_groupless_course(client):
    # Находка Полковника: курс админа без группы не должен утечь студенту без группы ('' == '').
    admin = make_admin(client)
    cid = client.post("/web/courses", json={"title": "Без группы", "subject": "", "group_name": ""},
                      headers=admin).json()["id"]
    stud = _make_student(client, admin, login="nogrp", group="")
    assert client.get("/web/courses", headers=stud).json()["courses"] == []
    assert client.get(f"/web/courses/{cid}", headers=stud).status_code == 403


def test_admin_sees_all_courses(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "К74-1", "Математика")
    cid = _new_course(client, teacher)
    assert any(c["id"] == cid for c in client.get("/web/courses", headers=admin).json()["courses"])
    assert client.get(f"/web/courses/{cid}", headers=admin).status_code == 200
