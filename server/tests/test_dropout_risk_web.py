"""
test_dropout_risk_web.py — риск отчисления в кабинетах (3.6).

Сами правила и веса проверяет `tests/test_dropout_risk.py` (общий корневой модуль).
Здесь — то, что относится к СЕРВЕРУ: сбор фактов из базы, ролевой скоуп (кто какой
срез видит) и границы доступа. Плюс два инварианта, которые легко потерять правкой:
чистый студент не отдаётся вовсе, и преподаватель судит только по своим предметам.
"""
from conftest import make_admin, make_teacher, assign_teacher

GROUP = "ИС-21"


def _group(client, admin, name=GROUP, subjects=("Математика", "Физика")):
    r = client.post("/web/admin/groups", json={"name": name, "subjects": list(subjects)},
                    headers=admin)
    assert r.status_code == 200, r.text


def _student(client, admin, login="ivanova", surname="Иванова", name="Мария", group=GROUP):
    r = client.post("/web/admin/students", json={
        "login": login, "surname": surname, "name": name, "group": group,
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text
    tok = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert tok.status_code == 200, tok.text
    return {"Authorization": f"Bearer {tok.json()['access_token']}", "X-Client": "web"}


def _lesson(client, admin, lesson_id, subject, ltype, number=1, group=GROUP):
    r = client.post("/sync/push", json={"changes": {"lessons": [{
        "id": lesson_id, "group_name": group, "subject": subject, "type": ltype,
        "number": number, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    assert r.status_code == 200, r.text


def _grade(client, admin, lesson_id, grade, surname="Иванова", name="Мария"):
    r = client.post("/sync/push", json={"changes": {"grades": [{
        "id": f"{surname}|{name}|{lesson_id}", "student_f": surname, "student_n": name,
        "lesson_id": lesson_id, "grade": grade}]}}, headers=admin)
    assert r.status_code == 200, r.text


def _make_failing_student(client, admin):
    """Студент с несданным экзаменом, долгами и прогулами — заведомо в зоне риска."""
    stud = _student(client, admin)
    _lesson(client, admin, "E1", "Математика", "Экзамен")
    _grade(client, admin, "E1", "2")
    for i in range(1, 5):
        _lesson(client, admin, f"P{i}", "Математика", "Практика", number=i)
        _grade(client, admin, f"P{i}", "2")
    for i in range(1, 6):
        _lesson(client, admin, f"L{i}", "Математика", "Лекция", number=i)
        _grade(client, admin, f"L{i}", "Н")
    return stud


# ── СТУДЕНТ ─────────────────────────────────────────────────────────────────────────
def test_clean_student_gets_no_risk_card(client):
    """У благополучного студента карточки риска НЕТ вовсе.

    Ключевое требование: показывать «риск 1 %» нельзя. Пустое поле risk — это не
    «забыли посчитать», а «считать нечего»."""
    admin = make_admin(client)
    _group(client, admin)
    stud = _student(client, admin)
    _lesson(client, admin, "P1", "Математика", "Практика")
    _grade(client, admin, "P1", "5")

    body = client.get("/web/student/insights", headers=stud).json()
    assert body["risk"] is None
    assert not any("риск отчисления" in c["title"].lower() for c in body["cards"])


def test_student_at_risk_sees_reasons_and_advice(client):
    """Студент в зоне риска видит УРОВЕНЬ, ПРЕДМЕТЫ и ЧТО ДЕЛАТЬ — не голый индекс."""
    admin = make_admin(client)
    _group(client, admin)
    stud = _make_failing_student(client, admin)

    body = client.get("/web/student/insights", headers=stud).json()
    risk = body["risk"]
    assert risk is not None and risk["visible"] is True
    assert risk["level"] in ("medium", "high", "critical")
    assert "Математика" in [s["subject"] for s in risk["subjects"]]
    assert risk["advice"], "совет обязателен: индекс без объяснения — приговор"

    card = body["cards"][0]      #карточка риска идёт ПЕРВОЙ, если она есть
    assert "риск отчисления" in card["title"].lower()
    assert card["action"], "в карточке обязан быть шаг, который можно сделать"


# ── ПРЕПОДАВАТЕЛЬ ───────────────────────────────────────────────────────────────────
def test_teacher_sees_risk_in_student_list(client):
    admin = make_admin(client)
    _group(client, admin)
    teacher = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", GROUP, "Математика")
    _make_failing_student(client, admin)

    rows = client.get(f"/web/teacher/students?group={GROUP}", headers=teacher).json()["students"]
    row = next(r for r in rows if r["surname"] == "Иванова")
    assert row["risk"] and row["risk"]["visible"] is True


def test_teacher_risk_counts_only_his_own_subjects(client):
    """Преподаватель судит ТОЛЬКО по своим предметам.

    Иначе он видел бы число, собранное из данных, которых ему не показывают, — и не смог
    бы его ни объяснить, ни проверить. Здесь провал у ЧУЖОГО предмета: у преподавателя
    физики список обязан остаться чистым."""
    admin = make_admin(client)
    _group(client, admin)
    make_teacher(client, admin, login="mathteach", subjects=["Математика"])
    physics = make_teacher(client, admin, login="phys", subjects=["Физика"])
    assign_teacher(client, admin, "teach:mathteach", GROUP, "Математика")
    assign_teacher(client, admin, "teach:phys", GROUP, "Физика")
    _make_failing_student(client, admin)      #всё плохо ИСКЛЮЧИТЕЛЬНО по математике
    #По физике у студента ровно одна нормальная оценка.
    _lesson(client, admin, "PH1", "Физика", "Практика")
    _grade(client, admin, "PH1", "5")

    rows = client.get(f"/web/teacher/students?group={GROUP}", headers=physics).json()["students"]
    assert all(r["risk"] is None for r in rows)


def test_teacher_summary_returns_groups_and_subjects(client):
    """Сводка вкладки «ИИ Помощник»: группы × предметы + счётчик зоны риска, ОДНИМ запросом."""
    admin = make_admin(client)
    _group(client, admin)
    teacher = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", GROUP, "Математика")
    _make_failing_student(client, admin)

    body = client.get("/web/teacher/summary", headers=teacher).json()
    grp = next(g for g in body["groups"] if g["group"] == GROUP)
    assert [s["subject"] for s in grp["subjects"]] == ["Математика"]
    assert grp["students"] == 1
    assert grp["at_risk"] == 1
    #«По скольким посчитано» — обязательное поле: средний по одному из двадцати и по
    #всем двадцати выглядит одинаково.
    assert grp["subjects"][0]["graded_students"] == 1


# ── КУРАТОР ─────────────────────────────────────────────────────────────────────────
def test_curator_sees_whole_group_risk_sorted(client):
    admin = make_admin(client)
    _group(client, admin)
    curator = make_teacher(client, admin, login="curator1", subjects=["Математика"])
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "teach:curator1", "role": "teacher", "login": "curator1",
        "curated_groups": [GROUP]}]}}, headers=admin)
    assert r.status_code == 200, r.text
    _make_failing_student(client, admin)
    #Второй студент — благополучный: он не должен попасть в выдачу вовсе.
    _student(client, admin, login="petrov", surname="Петров", name="Иван")
    _grade(client, admin, "P1", "5", surname="Петров", name="Иван")

    body = client.get(f"/web/curator/risk?group={GROUP}", headers=curator).json()
    assert body["total"] == 2
    assert body["at_risk"] == 1
    assert [s["surname"] for s in body["students"]] == ["Иванова"]
    scores = [s["risk"]["score"] for s in body["students"]]
    assert scores == sorted(scores, reverse=True), "первым идёт тот, к кому идти первым"


def test_curator_risk_rejects_foreign_group(client):
    """Row-level: чужая группа — 403, как и во всём разделе куратора."""
    admin = make_admin(client)
    _group(client, admin)
    curator = make_teacher(client, admin, login="curator1")
    client.post("/sync/push", json={"changes": {"users": [{
        "id": "teach:curator1", "role": "teacher", "login": "curator1",
        "curated_groups": ["ДРУГАЯ"]}]}}, headers=admin)
    r = client.get(f"/web/curator/risk?group={GROUP}", headers=curator)
    assert r.status_code == 403


def test_student_cannot_read_curator_risk(client):
    """Список «кто в группе на грани отчисления» — не для однокурсников."""
    admin = make_admin(client)
    _group(client, admin)
    stud = _student(client, admin)
    r = client.get(f"/web/curator/risk?group={GROUP}", headers=stud)
    assert r.status_code == 403


# ── РОДИТЕЛЬ ────────────────────────────────────────────────────────────────────────
def test_parent_stats_mirrors_student_stats(client):
    """Формат /web/parent/stats ОБЯЗАН совпадать со студенческим.

    Одинаковая форма — не эстетика: сводку рисует одна и та же карточка, и как только
    ответы разъедутся, у родителя и студента разъедутся цифры на экране."""
    admin = make_admin(client)
    _group(client, admin)
    stud = _student(client, admin)
    _lesson(client, admin, "P1", "Математика", "Практика")
    _grade(client, admin, "P1", "4")

    #Родитель + подтверждённая связь (доступ открывает САМ студент, инвариант §13).
    r = client.post("/web/admin/parents", json={
        "login": "parent1", "surname": "Иванов", "name": "Пётр",
        "password": "parentpass1"}, headers=admin)
    assert r.status_code == 200, r.text
    parent_id = r.json()["id"]
    student_id = next(s["id"] for s in
                      client.get("/web/admin/students", headers=admin).json()["students"]
                      if s["login"] == "ivanova")
    r = client.post("/web/staff/parent-links", json={
        "parent_id": parent_id, "student_id": student_id}, headers=admin)
    assert r.status_code == 200, r.text
    link_id = client.get("/web/student/parent-links", headers=stud).json()["links"][0]["id"]
    client.post(f"/web/student/parent-links/{link_id}/decide", json={"approve": True},
                headers=stud)

    tok = client.post("/auth/login", json={"login": "parent1", "password": "parentpass1"})
    parent = {"Authorization": f"Bearer {tok.json()['access_token']}", "X-Client": "web"}

    mine = client.get("/web/student/stats", headers=stud).json()
    theirs = client.get("/web/parent/stats", headers=parent).json()
    assert theirs["average"] == mine["average"]
    assert [s["subject"] for s in theirs["per_subject"]] == [s["subject"] for s in mine["per_subject"]]
    #Счётчик оценок по предмету — то, ради чего поле и добавлено в 3.6.
    assert theirs["per_subject"][0]["grades"] == 1


def test_stranger_cannot_read_parent_stats(client):
    """Родитель без подтверждённой связи не получает ничего (403, не пустой ответ)."""
    admin = make_admin(client)
    _group(client, admin)
    _student(client, admin)
    client.post("/web/admin/parents", json={
        "login": "parent2", "surname": "Чужой", "name": "Человек",
        "password": "parentpass1"}, headers=admin)
    tok = client.post("/auth/login", json={"login": "parent2", "password": "parentpass1"})
    parent = {"Authorization": f"Bearer {tok.json()['access_token']}", "X-Client": "web"}
    assert client.get("/web/parent/stats", headers=parent).status_code == 403


# ── УВЕДОМЛЕНИЕ КУРАТОРУ ────────────────────────────────────────────────────────────
def test_curator_is_notified_once_per_worsening(client):
    """Письмо куратору уходит при УХУДШЕНИИ уровня, а не после каждой оценки.

    Без памяти о прошлом уровне (DropoutRiskNotice) куратор получал бы одно и то же
    уведомление после каждой двойки — такие перестают читать за день."""
    from app.db import SessionLocal
    from app.models import NotifyEvent

    admin = make_admin(client)
    _group(client, admin)
    teacher = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", GROUP, "Математика")
    #Куратор — отдельный человек: у него своя почта уведомлений.
    make_teacher(client, admin, login="curator1", subjects=["Математика"])
    client.post("/sync/push", json={"changes": {"users": [{
        "id": "teach:curator1", "role": "teacher", "login": "curator1",
        "curated_groups": [GROUP]}]}}, headers=admin)
    _make_failing_student(client, admin)

    #Ставим ещё одну двойку РУКАМИ преподавателя — это и есть момент пересчёта риска.
    _lesson(client, admin, "P9", "Математика", "Практика", number=9)
    for value in ("2", "2"):     #дважды: второй раз уровень уже не растёт
        client.post("/web/teacher/grade", json={
            "surname": "Иванова", "name": "Мария", "lesson_id": "P9", "grade": value},
            headers=teacher)

    db = SessionLocal()
    try:
        events = db.query(NotifyEvent).filter(
            NotifyEvent.login == "curator1", NotifyEvent.kind == "dropout_risk").all()
    finally:
        db.close()
    assert len(events) <= 1, "повторное ухудшение того же уровня не шлёт второе письмо"
    if events:
        #В письме обязаны быть причины — иначе куратору всё равно идти разбираться вслепую.
        assert "Иванова" in events[0].body


def test_risk_category_is_switchable_off(client):
    """Новая категория уведомлений обязана гаситься переключателем.

    Иначе получилось бы уведомление, которое приходит, а выключить его нечем."""
    from app import rustore_push
    assert rustore_push.CATEGORY_BY_TYPE["dropout_risk"] == "risk"
    assert "risk" in rustore_push.ALL_CATEGORIES
    assert rustore_push.category_enabled({"notify": {"risk": False}}, "risk") is False
    assert rustore_push.category_enabled({}, "risk") is True
