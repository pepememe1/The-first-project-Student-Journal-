"""test_admin_foolproof.py — «защита от дурака» в разделах администратора (13.10.2026).

Живой обход стенда глазами новичка нашёл три вещи, и каждая здесь под сторожем:

1. Студент создавался с фамилией из трёхсот букв: таблица уезжала вправо вместе с
   кнопками «изменить» и «удалить», то есть исправить запись становилось нечем.
2. Логин был уникален в пределах РОЛИ, а не журнала: студент «ivanov» заводился при живом
   преподавателе «ivanov», и один из них переставал входить — вход берёт первого найденного.
3. Окна удаления группы, предмета, студента и преподавателя не называли последствий.
   Числа для них считает сервер (`app/delete_impact.py`).

Обратный ход: проверка занятого логина снята руками (`_refuse_taken_login` → `pass`) —
`test_login_is_unique_across_roles` краснеет; предел длины снят — краснеет первый тест.
"""
from conftest import assign_teacher, make_admin, make_teacher


def _student(client, admin, login, surname="Иванов", name="Иван", group="К74/1", **extra):
    return client.post("/web/admin/students", json={
        "surname": surname, "name": name, "login": login, "group": group, **extra}, headers=admin)


def test_absurdly_long_name_is_refused_with_a_plain_reason(client):
    admin = make_admin(client)
    r = _student(client, admin, "long1", surname="А" * 300)
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "Фамилия" in detail and "не больше 60" in detail
    #Обычная длинная фамилия проходит: правило режет бессмыслицу, а не людей.
    assert _student(client, admin, "long2", surname="Римский-Корсаков-Задунайский").status_code == 200


def test_login_that_would_break_the_address_is_refused(client):
    admin = make_admin(client)
    for bad in ("iva nov", "ivanov/1", "a", "x" * 65, "ivan?ov", "ivan#ov"):
        r = _student(client, admin, bad)
        assert r.status_code == 400, f"приняли логин «{bad}»"
        assert "огин" in r.json()["detail"]
    #Почта и точка в логине — обычное дело.
    assert _student(client, admin, "ivanov.ii@example.com").status_code == 200


def test_login_is_unique_across_roles(client):
    admin = make_admin(client)
    make_teacher(client, admin, login="shared1")
    r = _student(client, admin, "shared1")
    assert r.status_code == 409, "студент занял логин преподавателя — один из них не войдёт"
    assert "занят" in r.json()["detail"] and "преподавателя" in r.json()["detail"]

    assert _student(client, admin, "shared2").status_code == 200
    r = client.post("/web/admin/teachers", json={"full_name": "Орлов Игорь", "login": "shared2"},
                    headers=admin)
    assert r.status_code == 409
    assert "студента" in r.json()["detail"]


def test_the_same_person_can_still_be_edited(client):
    """Правка своей же строки не считается «логин занят»."""
    admin = make_admin(client)
    assert _student(client, admin, "edit1").status_code == 200
    r = client.put("/web/admin/students/edit1", json={"surname": "Петров"}, headers=admin)
    assert r.status_code == 200
    #Пустая фамилия — отказ: человек без фамилии не находится поиском.
    assert client.put("/web/admin/students/edit1", json={"surname": "  "}, headers=admin).status_code == 400
    #И длина проверяется при правке так же, как при создании.
    assert client.put("/web/admin/students/edit1", json={"surname": "Б" * 61},
                      headers=admin).status_code == 400


def test_subject_and_group_names_have_a_limit(client):
    admin = make_admin(client)
    assert client.post("/web/admin/subjects", json={"name": "П" * 201}, headers=admin).status_code == 400
    assert client.post("/web/admin/groups", json={"name": "Г" * 41, "course": 1},
                       headers=admin).status_code == 400


def test_delete_impact_counts_what_stands_behind_a_group(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="imp_t")
    assign_teacher(client, admin, "teach:imp_t", "К74/1", "Математика")
    assert _student(client, admin, "imp_s1", surname="Первый").status_code == 200
    assert _student(client, admin, "imp_s2", surname="Второй").status_code == 200
    lesson = client.post("/web/teacher/lesson", json={
        "group": "К74/1", "subject": "Математика", "type": "Практика", "topic": "т"}, headers=teacher)
    assert lesson.status_code == 200, lesson.text
    lid = lesson.json()["id"]
    for surname in ("Первый", "Второй"):
        r = client.post("/web/teacher/grade", json={
            "surname": surname, "name": "Иван", "lesson_id": lid, "grade": "5"}, headers=teacher)
        assert r.status_code == 200, r.text

    def impact(kind, key):
        r = client.get("/web/admin/delete-impact", params={"kind": kind, "key": key}, headers=admin)
        assert r.status_code == 200, r.text
        return r.json()["counts"]

    group = impact("group", "К74/1")           #название со слэшем — в запросе, не в пути
    assert group == {"students": 2, "lessons": 1, "marks": 2, "teachers": 1}
    assert impact("subject", "Математика")["lessons"] == 1
    assert impact("subject", "Математика")["marks"] == 2
    assert impact("student", "imp_s1")["marks"] == 1
    assert impact("teacher", "imp_t")["journals"] == 1
    #Того, чего нет, — ноль, а не ошибка: окно просто скажет, что удалять почти нечего.
    assert impact("group", "НЕТ-ТАКОЙ") == {"students": 0, "lessons": 0, "marks": 0, "teachers": 0}


def test_delete_impact_is_for_the_administrator_only(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="imp_t2")
    r = client.get("/web/admin/delete-impact", params={"kind": "group", "key": "К74/1"}, headers=teacher)
    assert r.status_code in (401, 403)
    assert client.get("/web/admin/delete-impact", params={"kind": "group", "key": "К74/1"}).status_code == 401
    bad = client.get("/web/admin/delete-impact", params={"kind": "planet", "key": "x"}, headers=admin)
    assert bad.status_code == 400


def test_threshold_error_speaks_russian_not_field_names(client):
    admin = make_admin(client)
    for bad in (-5, "много"):
        r = client.post("/web/admin/zet-thresholds", json={"group": "К74/1", "min_zet": bad},
                        headers=admin)
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "min_zet" not in detail and "Порог" in detail, detail


def test_lesson_with_a_nonsense_number_is_refused_not_crashed(client):
    """Номер «abc» доходил до `int()` и ронял ручку: человек видел «Внутренняя ошибка сервера»."""
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="shape_t")
    assign_teacher(client, admin, "teach:shape_t", "К74/1", "Математика")
    base = {"group": "К74/1", "subject": "Математика", "type": "Практика"}
    for extra, word in (({"number": "abc"}, "числом"), ({"number": -3}, "от 1 до 999"),
                        ({"number": 1000}, "от 1 до 999"), ({"hour": "много"}, "числом"),
                        ({"hour": 99}, "от 0 до 24"), ({"topic": "т" * 4001}, "длинная")):
        r = client.post("/web/teacher/lesson", json={**base, **extra}, headers=teacher)
        assert r.status_code == 400, f"{extra}: {r.status_code} {r.text[:120]}"
        assert word in r.json()["detail"], r.json()["detail"]
    ok = client.post("/web/teacher/lesson", json={**base, "number": 3, "topic": "т"}, headers=teacher)
    assert ok.status_code == 200, ok.text
    upd = client.put(f"/web/teacher/lesson/{ok.json()['id']}", json={"number": "abc"}, headers=teacher)
    assert upd.status_code == 400 and "числом" in upd.json()["detail"]
