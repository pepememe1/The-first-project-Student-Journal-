"""
test_teacher_subjects_overview.py — диаграммы вкладки «ИИ Помощник» у преподавателя (3.6.1).

GET /web/teacher/subjects-overview — общая категоризация студентов (отличники/хорошисты/
успевающие/неуспевающие, curator_report.categorize) по ВСЕЙ нагрузке преподавателя +
та же категоризация ПО КАЖДОМУ ПРЕДМЕТУ (агрегат по всем его группам).
GET /web/teacher/subjects-overview/groups?subject=... — второй уровень: та же
категоризация, но по каждой ГРУППЕ внутри одного предмета (drill-down).
"""
from conftest import make_admin, make_teacher, assign_teacher


def _group(client, admin, name, subjects):
    r = client.post("/web/admin/groups", json={"name": name, "subjects": list(subjects)},
                    headers=admin)
    assert r.status_code == 200, r.text


def _student(client, admin, login, surname, name, group):
    r = client.post("/web/admin/students", json={
        "login": login, "surname": surname, "name": name, "group": group,
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text


def _lesson(client, admin, lesson_id, subject, group, ltype="Практика", number=1):
    r = client.post("/sync/push", json={"changes": {"lessons": [{
        "id": lesson_id, "group_name": group, "subject": subject, "type": ltype,
        "number": number, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    assert r.status_code == 200, r.text


def _grade(client, admin, lesson_id, grade, surname, name):
    r = client.post("/sync/push", json={"changes": {"grades": [{
        "id": f"{surname}|{name}|{lesson_id}", "student_f": surname, "student_n": name,
        "lesson_id": lesson_id, "grade": grade}]}}, headers=admin)
    assert r.status_code == 200, r.text


def test_overview_categorizes_by_subject_average_not_overall(client):
    """Категория студента по предмету считается по ЕГО СРЕДНЕМУ ИМЕННО ПО ЭТОМУ предмету —
    не по общему среднему за все дисциплины (у студента может быть другой преподаватель
    по другому предмету с совсем другими оценками, это не должно красить чужую категорию)."""
    admin = make_admin(client)
    _group(client, admin, "К-1", ["Математика"])
    teacher = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "К-1", "Математика")
    _student(client, admin, "ivanova", "Иванова", "Мария", "К-1")
    _lesson(client, admin, "P1", "Математика", "К-1")
    _grade(client, admin, "P1", "5", "Иванова", "Мария")

    body = client.get("/web/teacher/subjects-overview", headers=teacher).json()
    assert body["overall"]["students"] == 1
    assert body["overall"]["categories"]["counts"]["excellent"] == 1
    subj = next(s for s in body["subjects"] if s["subject"] == "Математика")
    assert subj["avg"] == 5.0
    assert subj["categories"]["counts"]["excellent"] == 1


def test_overview_aggregates_subject_across_multiple_groups(client):
    """Один и тот же предмет у ДВУХ групп — на верхнем уровне суммируются в ОДНУ строку."""
    admin = make_admin(client)
    _group(client, admin, "К-1", ["Математика"])
    _group(client, admin, "К-2", ["Математика"])
    teacher = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "К-1", "Математика")
    assign_teacher(client, admin, "teach:teacher1", "К-2", "Математика")
    _student(client, admin, "s1", "Иванова", "Мария", "К-1")
    _student(client, admin, "s2", "Петров", "Иван", "К-2")
    _lesson(client, admin, "P1", "Математика", "К-1")
    _grade(client, admin, "P1", "5", "Иванова", "Мария")
    _lesson(client, admin, "P2", "Математика", "К-2")
    _grade(client, admin, "P2", "2", "Петров", "Иван")

    body = client.get("/web/teacher/subjects-overview", headers=teacher).json()
    assert len(body["subjects"]) == 1
    subj = body["subjects"][0]
    assert subj["students"] == 2
    assert subj["categories"]["counts"]["excellent"] == 1
    assert subj["categories"]["counts"]["failing"] == 1
    assert body["overall"]["students"] == 2


def test_overview_ignores_subjects_teacher_is_not_assigned_to(client):
    """Предмет/группа БЕЗ явного назначения этому преподавателю — не попадают в сводку
    (тот же источник прав, что и у остального кабинета — teacher_assignments)."""
    admin = make_admin(client)
    _group(client, admin, "К-1", ["Математика", "Физика"])
    teacher = make_teacher(client, admin, subjects=["Математика"])
    physics = make_teacher(client, admin, login="phys", subjects=["Физика"])
    assign_teacher(client, admin, "teach:teacher1", "К-1", "Математика")
    assign_teacher(client, admin, "teach:phys", "К-1", "Физика")
    _student(client, admin, "s1", "Иванова", "Мария", "К-1")
    _lesson(client, admin, "P1", "Математика", "К-1")
    _grade(client, admin, "P1", "5", "Иванова", "Мария")
    _lesson(client, admin, "PH1", "Физика", "К-1")
    _grade(client, admin, "PH1", "2", "Иванова", "Мария")

    body = client.get("/web/teacher/subjects-overview", headers=teacher).json()
    assert [s["subject"] for s in body["subjects"]] == ["Математика"]


def test_groups_drilldown_one_row_per_group(client):
    admin = make_admin(client)
    _group(client, admin, "К-1", ["Математика"])
    _group(client, admin, "К-2", ["Математика"])
    teacher = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "К-1", "Математика")
    assign_teacher(client, admin, "teach:teacher1", "К-2", "Математика")
    _student(client, admin, "s1", "Иванова", "Мария", "К-1")
    _student(client, admin, "s2", "Петров", "Иван", "К-2")
    _lesson(client, admin, "P1", "Математика", "К-1")
    _grade(client, admin, "P1", "5", "Иванова", "Мария")
    _lesson(client, admin, "P2", "Математика", "К-2")
    _grade(client, admin, "P2", "2", "Петров", "Иван")

    body = client.get("/web/teacher/subjects-overview/groups",
                      params={"subject": "Математика"}, headers=teacher).json()
    by_group = {g["group"]: g for g in body["groups"]}
    assert by_group["К-1"]["avg"] == 5.0
    assert by_group["К-2"]["avg"] == 2.0


def test_groups_drilldown_requires_teacher_role(client):
    admin = make_admin(client)
    r = client.get("/web/teacher/subjects-overview/groups",
                   params={"subject": "Математика"}, headers=admin)
    assert r.status_code == 403


def test_overview_requires_teacher_role(client):
    admin = make_admin(client)
    assert client.get("/web/teacher/subjects-overview", headers=admin).status_code == 403
