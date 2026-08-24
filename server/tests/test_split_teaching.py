"""
test_split_teaching.py — Раздельное обучение (§ролей, 3.6.1): куратор ставит галочку
на предмете → админ занимает второго преподавателя → куратор расставляет студентов по
подгруппам → каждый преподаватель видит только свою подгруппу в журнале, с отдельной
нумерацией занятий и своим набором кнопок 1ПГ/2ПГ/Совместно.
"""
from conftest import make_admin, make_teacher, assign_teacher
from app.security import hash_password


def _students(client, admin, group, names):
    """[(surname, name), ...] -> заводит студентов группы, возвращает их id."""
    users = []
    ids = []
    for i, (surname, name) in enumerate(names):
        sid = f"stud:s{i}"
        ids.append(sid)
        users.append({"id": sid, "role": "student", "login": f"s{i}",
                     "password_hash": hash_password("p"), "surname": surname,
                     "name": name, "group_name": group})
    r = client.post("/sync/push", json={"changes": {"users": users}}, headers=admin)
    assert r.status_code == 200, r.text
    return ids


def _login(client, login, pw):
    r = client.post("/auth/login", json={"login": login, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _setup_split(client, admin, group="G1", subject="Английский язык"):
    """Группа + предмет + галочка split + два преподавателя, назначенные по слотам."""
    client.post("/web/admin/groups", json={"name": group, "subjects": [subject]}, headers=admin)
    r = client.post("/web/curator/subject-split",
                    json={"group": group, "subject": subject, "split": True}, headers=admin)
    assert r.status_code == 200, r.text
    th1 = make_teacher(client, admin, login="t1", password="pass1234", subjects=[subject])
    th2 = make_teacher(client, admin, login="t2", password="pass1234", subjects=[subject])
    r = client.post("/web/admin/group-hours", json={
        "group": group, "teachers": {subject: "teach:t1"},
        "teachers2": {subject: "teach:t2"}}, headers=admin)
    assert r.status_code == 200, r.text
    return th1, th2


def test_split_flag_creates_row_and_admin_can_assign_second_teacher(client):
    admin = make_admin(client)
    th1, th2 = _setup_split(client, admin)
    hb = client.get("/web/admin/group-hours?group=G1", headers=admin).json()
    row = next(s for s in hb["subjects"] if s["subject"] == "Английский язык")
    assert row["split"] is True
    assert row["teacher_id"] == "teach:t1" and row["teacher_id_2"] == "teach:t2"


def test_admin_cannot_assign_second_teacher_without_split(client):
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "G2", "subjects": ["Химия"]}, headers=admin)
    make_teacher(client, admin, login="t3", password="pass1234", subjects=["Химия"])
    r = client.post("/web/admin/group-hours",
                    json={"group": "G2", "teachers2": {"Химия": "teach:t3"}}, headers=admin)
    assert r.status_code == 400, r.text


def test_curator_or_admin_only_can_toggle_split(client):
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "G3", "subjects": ["Физика"]}, headers=admin)
    th = make_teacher(client, admin, login="t4", password="pass1234", subjects=["Физика"])
    r = client.post("/web/curator/subject-split",
                    json={"group": "G3", "subject": "Физика", "split": True}, headers=th)
    assert r.status_code == 403, r.text


def test_teacher_with_only_one_subgroup_sees_only_that_roster(client):
    admin = make_admin(client)
    th1, th2 = _setup_split(client, admin)
    ids = _students(client, admin, "G1", [("Иванов", "Иван"), ("Петров", "Пётр")])
    r = client.post("/web/curator/subgroups", json={
        "group": "G1", "subject": "Английский язык",
        "assignments": {ids[0]: 1, ids[1]: 2}}, headers=admin)
    assert r.status_code == 200, r.text

    jr1 = client.get("/web/teacher/journal",
                     params={"group": "G1", "subject": "Английский язык"}, headers=th1).json()
    assert jr1["split"]["owned_subgroups"] == [1]
    assert [s["surname"] for s in jr1["students"]] == ["Иванов"]

    jr2 = client.get("/web/teacher/journal",
                     params={"group": "G1", "subject": "Английский язык"}, headers=th2).json()
    assert jr2["split"]["owned_subgroups"] == [2]
    assert [s["surname"] for s in jr2["students"]] == ["Петров"]


def test_unassigned_student_invisible_to_either_teacher_until_curator_sorts_them(client):
    """Преподаватель ОДНОЙ подгруппы чужого студента в своём ростере не видит — показать
    его значило бы предложить поставить оценку не своему.

    ⚠️ Но и молчать нельзя: раньше такой студент пропадал БЕССЛЕДНО, и преподаватель не
    мог узнать, что человек в группе вообще есть. Теперь число нераспределённых приходит
    отдельным полем, и журнал показывает предупреждение."""
    admin = make_admin(client)
    th1, th2 = _setup_split(client, admin)
    _students(client, admin, "G1", [("Сидоров", "Семён")])   # не распределён

    jr1 = client.get("/web/teacher/journal",
                     params={"group": "G1", "subject": "Английский язык"}, headers=th1).json()
    jr2 = client.get("/web/teacher/journal",
                     params={"group": "G1", "subject": "Английский язык"}, headers=th2).json()
    assert jr1["students"] == [] and jr2["students"] == []
    assert jr1["split"]["unassigned"] == 1, jr1["split"]
    assert jr2["split"]["unassigned"] == 1, jr2["split"]


def test_teacher_of_both_subgroups_sees_the_student_the_curator_has_not_sorted(client):
    """🔥 Живой отчёт: «добавил студента в группу с раздельным обучением — он не
    отображается».

    Так и было: студент без строки StudentSubgroup выпадал из ростера ВООБЩЕ, включая
    режим «Совместно». Ни строки, ни следа, ни причины — тихая пропажа человека из
    журнала. Преподаватель, ведущий ОБЕ подгруппы, обязан его видеть: чужих у него нет
    по определению, а поставить оценку иначе негде."""
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "G9", "subjects": ["Информатика"]}, headers=admin)
    client.post("/web/curator/subject-split",
                json={"group": "G9", "subject": "Информатика", "split": True}, headers=admin)
    th = make_teacher(client, admin, login="t9", password="pass1234", subjects=["Информатика"])
    r = client.post("/web/admin/group-hours",
                    json={"group": "G9", "teachers": {"Информатика": "teach:t9"}}, headers=admin)
    assert r.status_code == 200, r.text          # teachers2 не задан — ведёт обе

    ids = _students(client, admin, "G9", [("Иванов", "Иван"), ("Новичок", "Пётр")])
    r = client.post("/web/curator/subgroups", json={
        "group": "G9", "subject": "Информатика",
        "assignments": {ids[0]: 1}}, headers=admin)      # второго НЕ расписали
    assert r.status_code == 200, r.text

    jr = client.get("/web/teacher/journal",
                    params={"group": "G9", "subject": "Информатика"}, headers=th).json()
    assert jr["split"]["owned_subgroups"] == [1, 2], jr["split"]
    names = sorted(s["surname"] for s in jr["students"])
    assert names == ["Иванов", "Новичок"], jr["students"]
    #Подгруппа нераспределённого приходит пустой — клиент по ней и рисует пометку.
    nov = next(s for s in jr["students"] if s["surname"] == "Новичок")
    assert nov["subgroup"] is None, nov
    assert jr["split"]["unassigned"] == 1, jr["split"]


def test_teacher_can_only_create_lesson_for_own_subgroup(client):
    admin = make_admin(client)
    th1, th2 = _setup_split(client, admin)

    ok = client.post("/web/teacher/lesson", json={
        "group": "G1", "subject": "Английский язык", "type": "Практика", "subgroup": 1,
    }, headers=th1)
    assert ok.status_code == 200, ok.text
    assert ok.json()["subgroup"] == 1

    foreign = client.post("/web/teacher/lesson", json={
        "group": "G1", "subject": "Английский язык", "type": "Практика", "subgroup": 2,
    }, headers=th1)
    assert foreign.status_code == 403, foreign.text

    combined = client.post("/web/teacher/lesson", json={
        "group": "G1", "subject": "Английский язык", "type": "Лекция", "subgroup": 0,
    }, headers=th1)
    assert combined.status_code == 403, "«Совместно» доступно только тому, кто ведёт ОБЕ подгруппы"


def test_sole_teacher_of_both_subgroups_can_create_combined(client):
    """Маленький класс: один препод в ОБОИХ слотах (или teacher_id_2 пуст) — «Совместно» доступно."""
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "G4", "subjects": ["Информатика"]}, headers=admin)
    client.post("/web/curator/subject-split",
               json={"group": "G4", "subject": "Информатика", "split": True}, headers=admin)
    th = make_teacher(client, admin, login="t5", password="pass1234", subjects=["Информатика"])
    r = client.post("/web/admin/group-hours",
                    json={"group": "G4", "teachers": {"Информатика": "teach:t5"}}, headers=admin)
    assert r.status_code == 200, r.text   # teachers2 не задан — тот же препод ведёт обе

    for sg in (0, 1, 2):
        r = client.post("/web/teacher/lesson", json={
            "group": "G4", "subject": "Информатика", "type": "Практика", "subgroup": sg,
        }, headers=th)
        assert r.status_code == 200, (sg, r.text)

    jr = client.get("/web/teacher/journal",
                    params={"group": "G4", "subject": "Информатика"}, headers=th).json()
    assert jr["split"]["owned_subgroups"] == [1, 2]


def test_numbering_is_independent_per_subgroup(client):
    """Живой запрос: «чтобы разные преподы могли не сбиться со счёта» — две независимые
    последовательности «Практика №1, №2…», не общая на двоих."""
    admin = make_admin(client)
    th1, th2 = _setup_split(client, admin)

    for _ in range(3):
        r = client.post("/web/teacher/lesson", json={
            "group": "G1", "subject": "Английский язык", "type": "Практика", "subgroup": 1,
        }, headers=th1)
        assert r.status_code == 200, r.text
    r2 = client.post("/web/teacher/lesson", json={
        "group": "G1", "subject": "Английский язык", "type": "Практика", "subgroup": 2,
    }, headers=th2)
    assert r2.status_code == 200, r2.text
    #Подгруппа 2 у своего первого занятия получает №1, а не №4 — счётчики раздельные.
    assert r2.json()["number"] == 1


def test_non_split_subject_ignores_subgroup_payload(client):
    """На обычном (не раздельном) предмете subgroup всегда 0, что бы ни прислали."""
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "G5", "subjects": ["Химия"]}, headers=admin)
    th = make_teacher(client, admin, login="t6", password="pass1234", subjects=["Химия"])
    assign_teacher(client, admin, "teach:t6", "G5", "Химия")
    r = client.post("/web/teacher/lesson", json={
        "group": "G5", "subject": "Химия", "type": "Практика", "subgroup": 1,
    }, headers=th)
    assert r.status_code == 200, r.text
    assert r.json()["subgroup"] == 0


def test_student_does_not_see_other_subgroups_lessons(client):
    admin = make_admin(client)
    th1, th2 = _setup_split(client, admin)
    ids = _students(client, admin, "G1", [("Иванов", "Иван"), ("Петров", "Пётр")])
    client.post("/web/curator/subgroups", json={
        "group": "G1", "subject": "Английский язык",
        "assignments": {ids[0]: 1, ids[1]: 2}}, headers=admin)

    client.post("/web/teacher/lesson", json={
        "group": "G1", "subject": "Английский язык", "type": "Практика", "subgroup": 1,
        "topic": "своя",
    }, headers=th1)
    client.post("/web/teacher/lesson", json={
        "group": "G1", "subject": "Английский язык", "type": "Практика", "subgroup": 2,
        "topic": "чужая",
    }, headers=th2)

    hs = _login(client, "s0", "p")   # Иванов, подгруппа 1
    jr = client.get("/web/student/journal", headers=hs).json()
    subj = next(s for s in jr["subjects"] if s["subject"] == "Английский язык")
    topics = {l["topic"] for l in subj["lessons"]}
    assert topics == {"своя"}


def test_curator_subgroups_roster_shows_everyone_with_assignment_state(client):
    admin = make_admin(client)
    th1, th2 = _setup_split(client, admin)
    ids = _students(client, admin, "G1", [("Иванов", "Иван"), ("Петров", "Пётр")])
    client.post("/web/curator/subgroups", json={
        "group": "G1", "subject": "Английский язык",
        "assignments": {ids[0]: 1}}, headers=admin)

    r = client.get("/web/curator/subgroups",
                   params={"group": "G1", "subject": "Английский язык"}, headers=admin).json()
    assert r["split"] is True
    by_id = {s["student_id"]: s["subgroup"] for s in r["students"]}
    assert by_id[ids[0]] == 1
    assert by_id[ids[1]] is None
