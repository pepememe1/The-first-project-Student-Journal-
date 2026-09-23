# -*- coding: utf-8 -*-
"""test_notify_categories_by_role.py — категории уведомлений по ролям (4.0).

Что здесь защищается:
  • ОДИН ИСТОЧНИК ПРАВДЫ. Список категорий роли отдаёт сервер (`GET /me/prefs`), и по
    нему же `notify_login` решает, слать ли пуш. Страница, державшая бы свой список,
    однажды показала бы переключатель, который ничего не решает.
  • «ПРЕДУПРЕЖДЕНИЯ ОБ УСПЕВАЕМОСТИ» — ТОЛЬКО КУРАТОРУ, а не любому преподавателю.
  • ОТСУТСТВИЕ КЛЮЧА В prefs ПО-ПРЕЖНЕМУ «ВКЛЮЧЕНО».
  • РОДИТЕЛЬ ПОЛУЧАЕТ ОЦЕНКИ РЕБЁНКА — только по активной связи (согласие студента).
"""
import pytest

from conftest import make_admin, make_teacher, assign_teacher


@pytest.fixture
def pushes(monkeypatch):
    from app import config, rustore_push
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "p")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "t")
    sent = []
    monkeypatch.setattr(rustore_push, "_post", lambda payload: (sent.append(payload)
                                                                or (True, 200, "{}")))
    return sent


class _U:
    def __init__(self, role, curated=()):
        self.role, self.curated_groups = role, list(curated)


def test_categories_follow_the_role():
    from app.rustore_push import categories_for, ALL_CATEGORIES
    student = set(categories_for(_U("student")))
    assert {"grades", "homework", "schedule", "messages", "events", "reminders",
            "system"} <= student and "risk" not in student
    teacher = set(categories_for(_U("teacher")))
    assert "risk" not in teacher and "grades" not in teacher and "homework" not in teacher
    assert "risk" in categories_for(_U("teacher", ["К-1"])), "куратору — предупреждения"
    assert set(categories_for(_U("admin"))) == {"messages", "events", "reminders", "system"}
    assert {"grades", "homework"} <= set(categories_for(_U("parent")))
    #Незнакомая роль — всё: ошибка в пользу тишины опаснее.
    assert set(categories_for(_U("опечатка"))) == set(ALL_CATEGORIES)
    #Все выдаваемые категории — известные странице настроек.
    for role in ("student", "teacher", "parent", "admin", "moderator"):
        assert set(categories_for(_U(role, ["x"]))) <= set(ALL_CATEGORIES)


def test_prefs_carry_the_role_list(client):
    admin = make_admin(client)
    teach = make_teacher(client, admin)
    got = client.get("/me/prefs", headers=teach).json()["notify_categories"]
    assert "risk" not in got and "grades" not in got and "messages" in got


def test_push_outside_the_role_list_is_not_sent(client, pushes):
    """Роль решает не только видимость переключателя, но и доставку: пуш категории,
    которой у роли нет, не уходит, даже если переключатель в prefs не трогали."""
    admin = make_admin(client)
    teach = make_teacher(client, admin)
    client.post("/me/push-token", json={"token": "dev-t"}, headers=teach)
    from app import rustore_push
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        assert rustore_push.notify_login(db, "teacher1", "t", "b",
                                         data={"type": "grade"}) == 0
        assert rustore_push.notify_login(db, "teacher1", "t", "b",
                                         data={"type": "message"}) == 1
    finally:
        db.close()
    assert len(pushes) == 1


def _parent_setup(client, admin):
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    sh = {"Authorization": "Bearer " + client.post("/auth/login", json={
        "login": "ivanova", "password": "studpass1"}).json()["access_token"],
        "X-Client": "web"}
    r = client.post("/web/admin/parents", json={"login": "mama", "surname": "Иванова",
                                                "name": "Анна", "password": "parentpass1"},
                    headers=admin)
    pid = r.json()["id"]
    r = client.post("/web/staff/parent-links", json={"parent_id": pid,
                                                     "student_id": "stud:ivanova"},
                    headers=admin)
    assert r.status_code == 200, r.text
    return sh, r.json()["id"]


def test_parent_gets_child_grade_only_with_consent(client, pushes):
    admin = make_admin(client)
    sh, link_id = _parent_setup(client, admin)
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L1", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    teach = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    ph = {"Authorization": "Bearer " + client.post("/auth/login", json={
        "login": "mama", "password": "parentpass1"}).json()["access_token"]}

    def grade(v):
        return client.post("/web/teacher/grade", json={
            "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": v},
            headers=teach)

    def parent_letters():
        return [e for e in client.get("/me/events", params={"filter": "all"},
                                      headers=ph).json()["items"] if e["kind"] == "grade"]

    assert grade("5").status_code == 200
    assert parent_letters() == [], "без согласия студента родитель не узнаёт об оценке"
    assert client.post(f"/web/student/parent-links/{link_id}/decide",
                       json={"approve": True}, headers=sh).status_code == 200
    assert grade("").status_code == 200       #сняли, чтобы следующая была «новой»
    assert grade("4").status_code == 200
    letters = parent_letters()
    assert len(letters) == 1 and "Иванова" in letters[0]["title"], letters
