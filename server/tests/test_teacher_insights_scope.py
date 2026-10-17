"""
test_teacher_insights_scope.py — сводка преподавателя по группе (`/web/teacher/insights`).

Карточки «средний балл группы / должники / зона риска / пропуски» строятся по предметам,
НАЗНАЧЕННЫМ преподавателю в ЭТОЙ группе, — тем же правилом, что соседняя статистика
(`teacher_stats` → `_teacher_check_assignment`). До 16.10.2026 бралось «все мои предметы
вообще» (`user.subjects`), и следствий было два:
• сводка открывалась по ЧУЖОЙ группе, где есть предмет с тем же названием;
• к своей группе подмешивался предмет, который в ней ведёт коллега.
"""
from conftest import make_admin, make_teacher, assign_teacher
from test_dropout_risk_web import GROUP, _group, _lesson, _make_failing_student

OTHER = "ИС-22"


def _setup(client):
    """teacher1 ведёт в ИС-21 только Физику; Математику там ведёт teacher2 (у студента по
    ней провал). В ИС-22 Математику ведёт teacher2, teacher1 там не назначен вовсе."""
    admin = make_admin(client)
    _group(client, admin)
    _group(client, admin, OTHER)
    t1 = make_teacher(client, admin, "teacher1", subjects=("Математика", "Физика"))
    make_teacher(client, admin, "teacher2", subjects=("Математика",))
    assign_teacher(client, admin, "teach:teacher1", GROUP, "Физика")
    assign_teacher(client, admin, "teach:teacher2", GROUP, "Математика")
    assign_teacher(client, admin, "teach:teacher2", OTHER, "Математика")
    _make_failing_student(client, admin)        #провал по Математике в ИС-21
    _lesson(client, admin, "F1", "Физика", "Практика")
    return admin, t1


def _titles(r):
    assert r.status_code == 200, r.text
    return [c["title"] for c in r.json()["cards"]]


def test_insights_count_only_subjects_assigned_in_this_group(client):
    """Провал по Математике, которую в группе ведёт коллега, в сводку teacher1 не идёт."""
    _admin, t1 = _setup(client)
    titles = _titles(client.get("/web/teacher/insights", params={"group": GROUP}, headers=t1))
    assert "Студенты в зоне риска" not in titles, titles
    assert "Незакрытые задолженности" not in titles, titles


def test_insights_of_a_foreign_group_are_refused(client):
    _admin, t1 = _setup(client)
    r = client.get("/web/teacher/insights", params={"group": OTHER}, headers=t1)
    assert r.status_code == 403, r.text


def test_the_teacher_of_the_subject_still_sees_the_risk(client):
    """Контроль: правка не гасит сводку тому, кто предмет действительно ведёт."""
    admin, _t1 = _setup(client)
    tok = client.post("/auth/login", json={"login": "teacher2", "password": "teacherpass1"})
    t2 = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    titles = _titles(client.get("/web/teacher/insights", params={"group": GROUP}, headers=t2))
    assert "Студенты в зоне риска" in titles, titles
