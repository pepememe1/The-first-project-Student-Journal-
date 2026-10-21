"""
test_scope_properties.py — права доступа как СВОЙСТВО, а не как список случаев (21.10.2026).

Этап I разбора Ярослава: «матрица прав доступа… Permissions(u) ⊆ AllowedScope(u); если
преподавателя убрали из группы, количество доступных ему данных не должно увеличиться».
Соседние тесты проверяют придуманные миры («т1 на ИС-21, т2 на ИС-22»). Здесь мир
случайный — какие пары «группа × предмет» назначены, решает seed, — и проверяются два
свойства области видимости синка (`routers/sync.py::_scope_for_teacher`):

1. ТОЧНОСТЬ: преподаватель получает оценки ровно назначенных ему пар — не меньше (иначе
   журнал в программе неполон) и не больше (иначе это чужие ПДн);
2. МОНОТОННОСТЬ: снятое назначение не расширяет видимое ни на одну строку, а оценки
   снятой пары уходят из выдачи.
Студент при этом видит только свои оценки — в любом мире.
"""
import random

import pytest

from conftest import assign_teacher, make_admin, make_teacher

GROUPS = ("ИС-31", "ИС-32", "ИС-33")
SUBJECTS = ("Математика", "Физика")


def _push(client, headers, **entities):
    r = client.post("/sync/push", json={"changes": entities}, headers=headers)
    assert r.status_code == 200, r.text


def _term():
    from app import webdata as W
    from app.db import SessionLocal
    with SessionLocal() as db:
        return W.current_term(W.load_config(db))


def _visible_grades(client, headers) -> set:
    """Полный проход синка с нуля — какие оценки этот человек получает."""
    cursor, scope, epoch, seen = 0, "", "", set()
    for _ in range(100):
        params = {"cursor": cursor, "scope": scope, "epoch": epoch}
        r = client.get("/sync/pull", params=params, headers=headers)
        assert r.status_code == 200, r.text
        page = r.json()
        assert not page.get("reset"), page
        if cursor == 0:
            scope, epoch = page["scope"], page["epoch"]
        seen.update(g["id"] for g in page["changes"].get("grades", []))
        cursor = page["cursor"]
        if not page["more"]:
            return seen
    raise AssertionError("страницы не кончились")


def _world(client, rnd):
    from app.security import hash_password
    ty, ts = _term()
    admin = make_admin(client)
    teacher = make_teacher(client, admin, "t1", subjects=SUBJECTS)
    pairs = {(g, s) for g in GROUPS for s in SUBJECTS if rnd.random() < 0.5}
    pairs = pairs or {(GROUPS[0], SUBJECTS[0])}
    for g, s in sorted(pairs):
        assign_teacher(client, admin, "teach:t1", g, s)
    where, lessons, users = {}, [], []
    for i, g in enumerate(GROUPS):
        users.append({"id": f"stud:s{i}", "role": "student", "login": f"s{i}",
                      "password_hash": hash_password("studpass1"), "surname": f"Студент{i}",
                      "name": "Имя", "group_name": g})
        for j, s in enumerate(SUBJECTS):
            lessons.append({"id": f"L{i}{j}", "group_name": g, "subject": s,
                            "type": "Практика", "number": 1, "year": ty, "semester": ts})
            where[f"stud:s{i}|L{i}{j}"] = (g, s)
    _push(client, admin, users=users, lessons=lessons)
    _push(client, admin, grades=[{"id": gid, "student_id": gid.split("|")[0],
                                  "lesson_id": gid.split("|")[1], "grade": "4"}
                                 for gid in where])
    return admin, teacher, pairs, where


@pytest.mark.parametrize("seed", range(5))
def test_teacher_sees_exactly_assigned_pairs_and_unassigning_never_widens(client, seed):
    rnd = random.Random(seed)
    admin, teacher, pairs, where = _world(client, rnd)
    seen = _visible_grades(client, teacher)
    assert seen == {gid for gid, p in where.items() if p in pairs}, (seed, sorted(pairs))
    g, s = rnd.choice(sorted(pairs))
    r = client.post("/web/admin/group-hours", json={"group": g, "teachers": {s: ""}},
                    headers=admin)
    assert r.status_code == 200, r.text
    after = _visible_grades(client, teacher)
    assert after <= seen, f"seed={seed}: снятое назначение расширило видимое: {after - seen}"
    assert not {gid for gid in after if where[gid] == (g, s)}, \
        f"seed={seed}: оценки снятой пары {g} × {s} остались в выдаче"


def test_student_sees_only_own_grades_in_a_random_world(client):
    admin, _teacher, _pairs, where = _world(client, random.Random(7))
    r = client.post("/auth/login", json={"login": "s1", "password": "studpass1"})
    assert r.status_code == 200, r.text
    student = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert _visible_grades(client, student) == {gid for gid in where if gid.startswith("stud:s1|")}
