"""
test_homonym.py — Изоляция ТЁЗОК (однофамильцев с одинаковым именем).

Оценки хранятся по ключу surname|name|lesson_id без группы. У двух студентов-тёзок
из РАЗНЫХ групп ключи всё равно разные (lesson_id уникален и принадлежит одной группе),
но общая выборка по (surname, name) затягивала чужие строки — из-за чего, в частности,
счётчик «оценок за месяц» раздувался оценками тёзки. Фикс: чтения оценок скоупятся по
занятиям группы (webdata.student_records(..., group)). Здесь это проверяем.
"""
from conftest import make_admin
from app.security import hash_password


def _push(client, h, **ent):
    return client.post("/sync/push", json={"changes": ent}, headers=h)


def test_homonyms_in_different_groups_are_isolated(client):
    h = make_admin(client)
    L1 = {"id": "L1", "group_name": "G1", "subject": "Мат", "type": "Практика", "number": 1}
    L2 = {"id": "L2", "group_name": "G2", "subject": "Мат", "type": "Практика", "number": 1}
    s1 = {"id": "stud:s1", "role": "student", "login": "s1", "surname": "Иванов",
          "name": "Иван", "group_name": "G1", "password_hash": hash_password("pass1")}
    s2 = {"id": "stud:s2", "role": "student", "login": "s2", "surname": "Иванов",
          "name": "Иван", "group_name": "G2", "password_hash": hash_password("pass2")}
    # Одинаковый ключ surname|name у обоих, но занятия — в РАЗНЫХ группах.
    g1 = {"id": "Иванов|Иван|L1", "student_f": "Иванов", "student_n": "Иван",
          "lesson_id": "L1", "grade": "5"}
    g2 = {"id": "Иванов|Иван|L2", "student_f": "Иванов", "student_n": "Иван",
          "lesson_id": "L2", "grade": "3"}
    assert _push(client, h, lessons=[L1, L2], users=[s1, s2], grades=[g1, g2]).status_code == 200

    r = client.post("/auth/login", json={"login": "s1", "password": "pass1"})
    assert r.status_code == 200, r.text
    hs1 = {"Authorization": f"Bearer {r.json()['access_token']}"}

    ov = client.get("/web/student/overview", headers=hs1).json()
    #Счётчик за месяц НЕ раздут оценкой тёзки из G2 (1, а не 2).
    assert ov["grades_month"] == 1, ov
    #Свежие оценки — только своя (5), без чужой (3).
    assert [x["grade"] for x in ov["recent"]] == ["5"], ov["recent"]

    jr = client.get("/web/student/journal", headers=hs1).json()
    all_grades = [it["grade"] for subj in jr["subjects"] for it in subj["lessons"]]
    assert "3" not in all_grades and "5" in all_grades, all_grades
