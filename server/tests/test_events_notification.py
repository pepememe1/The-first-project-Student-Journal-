"""
test_events_notification.py — POST /web/events: мероприятия/события (олимпиады,
конкурсы и т.п.), которые заводит преподаватель или админ и которые уходят выбранной
аудитории уведомлением kind="event" (вкладка «Мероприятия» в NotificationsInbox.vue).

Роль-скоуп — как и везде: админ может широковещательно («все группы») или в конкретные
группы; преподаватель — ТОЛЬКО в свои группы (по предметам, как в журнале), без «все».
"""
import pytest

from conftest import make_admin, make_teacher


@pytest.fixture(autouse=True)
def push_on(monkeypatch):
    """Пуши включены, но сетевой вызов подменяем — проверяем только НАШУ БД (NotifyEvent)."""
    from app import config, rustore_push
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "test-project")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "test-token")
    monkeypatch.setattr(rustore_push, "_post", lambda payload: (True, 200, "{}"))


def _make_student(client, admin, login, group):
    from app.security import hash_password
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": "Студент Тестов",
        "surname": "Тестов", "name": "Студент", "group_name": group,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_teacher_group(client, admin, group="ИС-21", subject="Математика"):
    """Занятие в группе по предмету + явное назначение препода (webdata.teacher_
    assignments) — без назначения препод теперь НЕ увидит группу (§ролей препод↔предмет
    ↔группа, 3.3.1: раньше «предмет числится у препода» ошибочно значило «видны все
    группы предмета»)."""
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L1", "group_name": group, "subject": subject, "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    teach = make_teacher(client, admin, subjects=[subject])  # id детерминирован: teach:teacher1
    r = client.post("/web/admin/groups", json={"name": group, "subjects": [subject]}, headers=admin)
    #Группа могла уже существовать (создана раньше в этом же тесте) — тогда 409, не страшно.
    assert r.status_code in (200, 409), r.text
    r = client.post("/web/admin/group-hours",
                    json={"group": group, "teachers": {subject: "teach:teacher1"}}, headers=admin)
    assert r.status_code == 200, r.text
    return teach


def test_admin_broadcasts_to_all_groups(client):
    admin = make_admin(client)
    _make_student(client, admin, "bob", "К-24")
    sh2 = _make_student(client, admin, "carol", "К-25")

    r = client.post("/web/events", json={
        "title": "Олимпиада по программированию", "body": "Регистрация до пятницы.",
        "groups": []}, headers=admin)
    assert r.status_code == 200, r.text
    #Сравниваем ПО ПОЛЯМ, а не весь ответ целиком: в нём появился `batch_id` (метка
    #рассылки для вкладки «Отправленные»), и точное равенство словарей ломалось бы на
    #каждом новом поле, ничего при этом не проверяя по существу.
    body = r.json()
    assert body["ok"] is True and body["sent"] == 2 and body["recipients"] == 2
    assert body["batch_id"], "рассылка обязана получить метку партии"

    items = client.get("/me/events", headers=sh2).json()["items"]
    assert len(items) == 1 and items[0]["kind"] == "event"
    assert items[0]["title"] == "Олимпиада по программированию"
    assert "пятницы" in items[0]["body"]


def test_admin_targets_specific_group(client):
    admin = make_admin(client)
    sh_a = _make_student(client, admin, "bob", "К-24")
    sh_b = _make_student(client, admin, "carol", "К-25")

    r = client.post("/web/events", json={
        "title": "Конкурс", "body": "Только для К-24.", "groups": ["К-24"]}, headers=admin)
    assert r.status_code == 200 and r.json()["recipients"] == 1

    assert len(client.get("/me/events", headers=sh_a).json()["items"]) == 1
    assert len(client.get("/me/events", headers=sh_b).json()["items"]) == 0


def test_teacher_can_notify_own_group(client):
    admin = make_admin(client)
    teach = _seed_teacher_group(client, admin, group="ИС-21", subject="Математика")
    sh = _make_student(client, admin, "bob", "ИС-21")

    r = client.post("/web/events", json={
        "title": "Выступление", "body": "Готовим доклад.", "groups": ["ИС-21"]}, headers=teach)
    assert r.status_code == 200, r.text
    assert r.json()["recipients"] == 1
    assert len(client.get("/me/events", headers=sh).json()["items"]) == 1


def test_teacher_cannot_broadcast_to_all(client):
    admin = make_admin(client)
    teach = _seed_teacher_group(client, admin)
    r = client.post("/web/events", json={
        "title": "Т", "body": "Т", "groups": []}, headers=teach)
    assert r.status_code == 400


def test_teacher_cannot_target_foreign_group(client):
    admin = make_admin(client)
    teach = _seed_teacher_group(client, admin, group="ИС-21", subject="Математика")
    r = client.post("/web/events", json={
        "title": "Т", "body": "Т", "groups": ["К-99"]}, headers=teach)
    assert r.status_code == 403


def test_student_forbidden(client):
    admin = make_admin(client)
    sh = _make_student(client, admin, "bob", "К-24")
    r = client.post("/web/events", json={"title": "Т", "body": "Т", "groups": []}, headers=sh)
    assert r.status_code == 403


def test_missing_title_or_body_rejected(client):
    admin = make_admin(client)
    assert client.post("/web/events", json={"title": "", "body": "Т", "groups": []},
                       headers=admin).status_code == 400
    assert client.post("/web/events", json={"title": "Т", "body": "", "groups": []},
                       headers=admin).status_code == 400


# ── Вкладка «Отправленные» (GET /web/events/sent) ───────────────────────────────────
# Показывает СВОИ рассылки, одной строкой на рассылку. Смысл раздела — «дошло ли»,
# поэтому проверяем именно схлопывание по партии и счётчик прочитавших, а не просто 200.

def test_sent_groups_one_row_per_mailing(client):
    """Рассылка на двух студентов — ОДНА строка с двумя получателями, а не две строки.
    Без метки партии (NotifyEvent.batch_id) список пришлось бы собирать по совпадению
    текста, и одинаковые объявления разных дней слиплись бы в одно."""
    admin = make_admin(client)
    _make_student(client, admin, "bob", "К-24")
    sh2 = _make_student(client, admin, "carol", "К-25")
    client.post("/web/events", json={
        "title": "Олимпиада", "body": "Регистрация до пятницы.", "groups": []}, headers=admin)

    items = client.get("/web/events/sent", headers=admin).json()["items"]
    assert len(items) == 1, items
    assert items[0]["title"] == "Олимпиада"
    assert items[0]["recipients"] == 2
    assert items[0]["read"] == 0

    #Один из двоих прочитал — счётчик обязан это показать, иначе раздел бесполезен.
    ev = client.get("/me/events", headers=sh2).json()["items"][0]
    client.post(f"/me/events/{ev['id']}/read", headers=sh2)
    items = client.get("/web/events/sent", headers=admin).json()["items"]
    assert items[0]["read"] == 1 and items[0]["recipients"] == 2


def test_sent_shows_only_my_own_mailings(client):
    """Чужая рассылка — не моя сводка. Письма коллеги это его переписка с его группами;
    для надзора есть аудит, а не вкладка «Отправленные»."""
    admin = make_admin(client)
    teach = _seed_teacher_group(client, admin)
    _make_student(client, admin, "bob", "ИС-21")
    client.post("/web/events", json={
        "title": "От админа", "body": "текст", "groups": []}, headers=admin)
    client.post("/web/events", json={
        "title": "От препода", "body": "текст", "groups": ["ИС-21"]}, headers=teach)

    mine = client.get("/web/events/sent", headers=teach).json()["items"]
    assert [i["title"] for i in mine] == ["От препода"]
    theirs = client.get("/web/events/sent", headers=admin).json()["items"]
    assert "От препода" not in [i["title"] for i in theirs]


def test_sent_excludes_automatic_letters(client):
    """Уведомления об оценке/расписании автора-человека не имеют — в «Отправленных» им
    не место. Держит правило «author_login пуст у автоматики»."""
    admin = make_admin(client)
    sh = _make_student(client, admin, "bob", "К-24")
    from app.db import SessionLocal
    from app import rustore_push
    db = SessionLocal()
    try:
        rustore_push.notify_new_grade(db, "bob", subject="Математика", value="5")
    finally:
        db.close()
    assert client.get("/me/events", headers=sh).json()["items"], "письмо студенту дошло"
    assert client.get("/web/events/sent", headers=admin).json()["items"] == []


def test_sent_forbidden_for_student(client):
    admin = make_admin(client)
    sh = _make_student(client, admin, "bob", "К-24")
    assert client.get("/web/events/sent", headers=sh).status_code == 403


def test_homework_lands_in_teacher_sent(client):
    """ДЗ — тоже рассылка автора: преподаватель должен видеть, что задал и кто прочитал.
    Одна строка на группу, а не на каждого студента."""
    admin = make_admin(client)
    teach = _seed_teacher_group(client, admin)
    _make_student(client, admin, "bob", "ИС-21")
    _make_student(client, admin, "carol", "ИС-21")
    r = client.post("/web/teacher/lesson", json={
        "group": "ИС-21", "subject": "Математика", "type": "ДЗ",
        "topic": "Задачи 1-10", "date": "10.09.2025"}, headers=teach)
    assert r.status_code == 200, r.text

    items = client.get("/web/events/sent", headers=teach).json()["items"]
    assert len(items) == 1, items
    assert items[0]["kind"] == "homework" and items[0]["recipients"] == 2
