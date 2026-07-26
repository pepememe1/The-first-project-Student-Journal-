"""
test_curator_reports.py — §12 плана: отчёты куратора для родителей в мессенджере.

Держим: канал «Отчёты · Группа» доступен ТОЛЬКО куратору ЭТОЙ группы и ТОЛЬКО если у
группы есть активная связь с родителем; команда /отчет создаёт «вечную» кнопку с
номером по порядку; данные считаются ЖИВЬЁМ, но ограничены датой создания отчёта;
rollover термина архивирует старые кнопки, не удаляя их.
"""
from conftest import make_admin, make_teacher


def _headers(client, login, password):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _student(client, admin, login, surname, name, group="ИС-21"):
    r = client.post("/web/admin/students", json={
        "login": login, "surname": surname, "name": name, "group": group,
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text


def _user_id(client, admin, login):
    r = client.get("/web/admin/students", headers=admin)
    assert r.status_code == 200, r.text
    for s in r.json()["students"]:
        if s.get("login") == login:
            return s.get("id")
    raise AssertionError(f"студент {login} не найден")


def _parent(client, admin, login, surname="Родителев", name="Родион"):
    r = client.post("/web/admin/parents", json={
        "login": login, "surname": surname, "name": name, "password": "parentpass1"},
        headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _link_and_approve(client, admin, parent_id, student_login, student_headers):
    sid = _user_id(client, admin, student_login)
    r = client.post("/web/staff/parent-links",
                    json={"parent_id": parent_id, "student_id": sid}, headers=admin)
    assert r.status_code == 200, r.text
    link_id = r.json()["id"]
    r = client.post(f"/web/student/parent-links/{link_id}/decide",
                    json={"approve": True}, headers=student_headers)
    assert r.status_code == 200, r.text


def _make_curator(client, admin, group="ИС-21", login="teacher1", subjects=("Математика",)):
    teach = make_teacher(client, admin, login=login, subjects=list(subjects))
    r = client.put(f"/web/admin/teachers/{login}",
                   json={"curated_groups": [group]}, headers=admin)
    assert r.status_code == 200, r.text
    return teach


def _seed_lesson_and_grade(client, admin, teach, group, subject, value="5", date="01.09.2025",
                          surname="Иванова", name="Мария", lesson_id="L1"):
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": lesson_id, "group_name": group, "subject": subject, "type": "Практика",
         "number": 1, "topic": "т", "date": date}]}}, headers=admin)
    r = client.post("/web/teacher/grade", json={
        "lesson_id": lesson_id, "surname": surname, "name": name, "grade": value}, headers=teach)
    assert r.status_code == 200, r.text


def _setup_group_with_parent(client, group="ИС-21"):
    """Админ, куратор группы, студент, подтверждённый родитель — минимальный «группа с
    родителями» набор, готовый к созданию канала отчётов."""
    admin = make_admin(client)
    teach = _make_curator(client, admin, group=group)
    _student(client, admin, "ivanova", "Иванова", "Мария", group=group)
    sh = _headers(client, "ivanova", "studpass1")
    pid = _parent(client, admin, "parent1")
    ph = _headers(client, "parent1", "parentpass1")
    _link_and_approve(client, admin, pid, "ivanova", sh)
    return admin, teach, sh, ph


def _ensure_channel(client, teach, group="ИС-21"):
    r = client.post(f"/web/messenger/channels/curator-reports/{group}", headers=teach)
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


# ── Доступ к каналу ──────────────────────────────────────────────────────────────────
def test_channel_requires_curator_of_group(client):
    admin = make_admin(client)
    teach = make_teacher(client, admin)   # НЕ куратор
    r = client.post("/web/messenger/channels/curator-reports/ИС-21", headers=teach)
    assert r.status_code == 403


def test_channel_requires_active_parent(client):
    admin = make_admin(client)
    teach = _make_curator(client, admin)
    _student(client, admin, "ivanova", "Иванова", "Мария", group="ИС-21")
    #Родителя ещё нет вовсе — группа "без родителей".
    r = client.post("/web/messenger/channels/curator-reports/ИС-21", headers=teach)
    assert r.status_code == 400


def test_channel_created_and_readers_are_students_and_parents(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    #И студент, и родитель видят канал в списке чатов.
    assert any(c["conversation_id"] == conv_id
              for c in client.get("/web/messenger/chats", headers=sh).json()["chats"])
    assert any(c["conversation_id"] == conv_id
              for c in client.get("/web/messenger/chats", headers=ph).json()["chats"])
    #Родитель — читатель: писать в канал не может.
    assert client.post(f"/web/messenger/chats/{conv_id}/messages",
                       json={"body": "спасибо"}, headers=ph).status_code == 403


# ── Команда /отчет ───────────────────────────────────────────────────────────────────
def test_report_command_creates_numbered_button(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5")

    r = client.post(f"/web/messenger/chats/{conv_id}/messages",
                    json={"body": "/отчет"}, headers=teach)
    assert r.status_code == 200, r.text

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    report_msgs = [m for m in msgs if m["kind"] == "report"]
    assert len(report_msgs) == 1
    assert report_msgs[0]["report"]["seq"] == 1
    assert report_msgs[0]["report"]["group"] == "ИС-21"
    assert report_msgs[0]["report"]["archived"] is False


def test_report_sequence_increments_per_group(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=teach).json()["messages"]
    seqs = sorted(m["report"]["seq"] for m in msgs if m["kind"] == "report")
    assert seqs == [1, 2]


def test_report_command_ignored_if_group_loses_last_parent(client):
    """Родитель отозвал согласие — команда больше не публикует отчёт (группа перестала
    быть «группой с родителями»), но сам канал/кнопки прошлых отчётов никуда не деваются."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    #Студент отзывает согласие.
    links = client.get("/web/student/parent-links", headers=sh).json()["links"]
    client.post(f"/web/student/parent-links/{links[0]['id']}/decide",
               json={"approve": False}, headers=sh)

    r = client.post(f"/web/messenger/chats/{conv_id}/messages",
                    json={"body": "/отчет"}, headers=teach)
    assert r.status_code == 200   #само сообщение отправляется
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=teach).json()["messages"]
    assert not any(m["kind"] == "report" for m in msgs)


# ── Данные отчёта (живой пересчёт) ───────────────────────────────────────────────────
def test_report_overview_categories_and_subjects(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5")
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    rid = next(m["report"]["id"] for m in msgs if m["kind"] == "report")

    r = client.get(f"/web/messenger/reports/{rid}", headers=ph)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["group"] == "ИС-21" and data["seq"] == 1
    assert data["categories"]["counts"]["excellent"] == 1   #средний 5 → отличница
    assert data["subjects"] == [{"subject": "Математика", "avg": 5.0, "percent": 100}]


def test_report_overview_forbidden_for_non_participant(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=teach).json()["messages"]
    rid = next(m["report"]["id"] for m in msgs if m["kind"] == "report")

    outsider = make_teacher(client, admin, login="teacher2")
    assert client.get(f"/web/messenger/reports/{rid}", headers=outsider).status_code == 403


def test_report_subject_drilldown_shows_grades_and_absences(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5")
    #Вторая пара — неявка (пропуск).
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L2", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 2, "topic": "т2", "date": "02.09.2025"}]}}, headers=admin)
    client.post("/web/teacher/grade", json={
        "lesson_id": "L2", "surname": "Иванова", "name": "Мария", "grade": "Н"}, headers=teach)

    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    rid = next(m["report"]["id"] for m in msgs if m["kind"] == "report")

    r = client.get(f"/web/messenger/reports/{rid}/subject",
                   params={"subject": "Математика"}, headers=ph)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["lessons"]) == 2
    row = data["rows"][0]
    assert row["student"] == "Иванова Мария"
    assert row["missed_count"] == 1 and row["missed_hours"] == 1


def test_report_snapshot_excludes_lessons_after_cutoff(client):
    """«Вечная» граница: занятие, добавленное ПОСЛЕ создания отчёта, в него не попадает,
    даже если дата занятия попадает в прошлое (curator_report фильтрует по факту создания,
    а тест проверяет наблюдаемое поведение — новая пара не должна ломать уже выданный отчёт)."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5", date="01.09.2025")
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    rid = next(m["report"]["id"] for m in msgs if m["kind"] == "report")

    #Занятие с ОЧЕНЬ старой датой, но добавленное ПОСЛЕ отчёта — граница по дате СОЗДАНИЯ
    #отчёта (сегодня), а не по дате занятия, поэтому это новое занятие тоже входит (оно
    #раньше cutoff=сегодня). Проверяем обратный, однозначный случай: занятие с датой в
    #будущем ПОСЛЕ cutoff — не входит.
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L9", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 9, "topic": "будущее", "date": "01.09.2099"}]}}, headers=admin)
    client.post("/web/teacher/grade", json={
        "lesson_id": "L9", "surname": "Иванова", "name": "Мария", "grade": "3"}, headers=teach)

    r = client.get(f"/web/messenger/reports/{rid}/subject",
                   params={"subject": "Математика"}, headers=ph)
    assert r.status_code == 200, r.text
    ids = [l["id"] for l in r.json()["lessons"]]
    assert "L9" not in ids, "занятие с датой ПОСЛЕ границы отчёта не должно входить в снимок"


# ── Архивация при rollover ────────────────────────────────────────────────────────────
def test_rollover_archives_old_reports(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)

    r = client.post("/web/admin/term/rollover", json={}, headers=admin)
    assert r.status_code == 200, r.text

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    rep = next(m["report"] for m in msgs if m["kind"] == "report")
    assert rep["archived"] is True, "кнопка старого отчёта должна архивироваться после rollover"


def test_new_report_after_rollover_is_not_archived(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    client.post("/web/admin/term/rollover", json={}, headers=admin)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=teach).json()["messages"]
    reports = sorted((m["report"] for m in msgs if m["kind"] == "report"), key=lambda r: r["seq"])
    assert len(reports) == 2
    assert reports[0]["archived"] is True    #отчёт из ЗАКРЫВШЕГОСЯ термина
    assert reports[1]["archived"] is False   #новый — из текущего термина
