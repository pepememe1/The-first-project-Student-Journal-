"""
test_push_notifications.py — пуши о новой оценке: доставка, приватность, переходы.

Главное, что здесь защищается, — НЕ факт отправки, а два свойства:
  • в теле уведомления НЕТ персональных данных (оно идёт через серверы RuStore);
  • сбой доставки НЕ мешает преподавателю поставить оценку.
Сам RuStore не дёргаем: тест чужого сервиса — не наш тест.
"""
import pytest

from conftest import make_admin, make_teacher


@pytest.fixture(autouse=True)
def push_on(monkeypatch):
    """Включаем пуши и подменяем сетевой вызов на запись в список."""
    from app import config, rustore_push
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "test-project")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "test-token")
    sent = []

    def fake_post(payload):
        sent.append(payload)
        return True, 200, "{}"
    monkeypatch.setattr(rustore_push, "_post", fake_post)
    return sent


def _seed(client, admin):
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L1", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    return make_teacher(client, admin, subjects=["Математика"])


def _student_headers(client):
    r = client.post("/auth/login", json={"login": "ivanova", "password": "studpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def test_grade_triggers_push(client, push_on):
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    client.post("/me/push-token", json={"token": "dev-token-1"}, headers=sh)

    r = client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "5"},
        headers=teach)
    assert r.status_code == 200, r.text
    assert len(push_on) == 1, "студенту должен уйти ровно один пуш"


def test_push_body_has_no_personal_data(client, push_on):
    """152-ФЗ: тело уходит через RuStore, поэтому ни балла, ни предмета, ни ФИО."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    client.post("/me/push-token", json={"token": "dev-token-1"}, headers=sh)
    client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "5"},
        headers=teach)

    text = str(push_on[0])
    for leak in ("Иванова", "Мария", "Математика", "ivanova"):
        assert leak not in text, f"в пуш утекло: {leak}"
    assert "новая оценка" in text.lower()


def test_cleared_grade_does_not_notify(client, push_on):
    """Снятие оценки не уведомляем: «у вас новая оценка» при удалении — дезинформация."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    client.post("/me/push-token", json={"token": "dev-token-1"}, headers=sh)
    client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": ""},
        headers=teach)
    assert push_on == []


def test_push_failure_does_not_break_grading(client, monkeypatch):
    """RuStore лёг — оценка всё равно ставится. Пуш это дополнение, а не условие."""
    from app import config, rustore_push
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "p")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "t")
    monkeypatch.setattr(rustore_push, "_post",
                        lambda payload: (_ for _ in ()).throw(OSError("сеть легла")))
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    client.post("/me/push-token", json={"token": "dev-token-1"}, headers=sh)

    r = client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "4"},
        headers=teach)
    assert r.status_code == 200, "падение пуша не должно ронять выставление оценки"


def test_event_lets_app_open_right_journal(client, push_on):
    """По id из пуша приложение узнаёт, КУДА открыть экран."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    client.post("/me/push-token", json={"token": "dev-token-1"}, headers=sh)
    client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "5"},
        headers=teach)

    event_id = push_on[0]["message"]["android"]["data"]["event_id"]
    assert event_id
    r = client.get(f"/me/events/{event_id}", headers=sh)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject"] == "Математика"
    assert body["lesson_id"] == "L1"


def test_event_of_other_user_is_not_disclosed(client, push_on):
    """Чужое событие → 404, а НЕ 403: 403 подтвердил бы, что оно существует, и перебор
    id стал бы способом узнать чужую активность."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    client.post("/me/push-token", json={"token": "dev-token-1"}, headers=sh)
    client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "5"},
        headers=teach)
    event_id = push_on[0]["message"]["android"]["data"]["event_id"]

    #админ — не владелец события
    assert client.get(f"/me/events/{event_id}", headers=admin).status_code == 404


def test_token_follows_last_logged_in_account(client, push_on):
    """Телефон один, аккаунты разные: уведомления идут ПОСЛЕДНЕМУ вошедшему."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    client.post("/web/admin/students", json={
        "login": "petrov", "surname": "Петров", "name": "Пётр", "group": "ИС-21",
        "password": "studpass2"}, headers=admin)

    sh1 = _student_headers(client)
    client.post("/me/push-token", json={"token": "same-device"}, headers=sh1)
    r = client.post("/auth/login", json={"login": "petrov", "password": "studpass2"})
    sh2 = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}
    client.post("/me/push-token", json={"token": "same-device"}, headers=sh2)

    #оценка ПЕРВОМУ студенту — на это устройство пуш идти уже не должен
    client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "5"},
        headers=teach)
    assert push_on == [], "устройство принадлежит другому аккаунту"


def test_logout_removes_token(client, push_on):
    """После выхода уведомления на это устройство не идут."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    client.post("/me/push-token", json={"token": "dev-token-1"}, headers=sh)
    assert client.request("DELETE", "/me/push-token", json={"token": "dev-token-1"},
                          headers=sh).status_code == 200

    client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": "5"},
        headers=teach)
    assert push_on == []


def test_push_disabled_when_not_configured(client, monkeypatch):
    """Без ключей RuStore пуши просто выключены — и это не ошибка."""
    from app import config
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "")
    assert config.push_enabled() is False


#Уведомления об изменении РАСПИСАНИЯ

def _mk_student(client, admin, login, group):
    client.post("/web/admin/students", json={
        "login": login, "surname": login.capitalize(), "name": "Тест",
        "group": group, "password": "studpass1"}, headers=admin)
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _override(client, admin, group, subject="Физика", action="set"):
    return client.post("/web/admin/schedule/override", json={
        "group": group, "week": 1, "day": "Пнд", "pair_no": 2,
        "action": action, "subject": subject, "time": "09:00", "room": "301"},
        headers=admin)


def test_schedule_change_notifies_only_that_group(client, push_on):
    """Ключевое требование: уведомление получает ТОЛЬКО группа, чьё расписание
    изменилось. Рассылать всему колледжу — прямой путь к тому, что уведомления
    отключат, и вместе с ними потеряются важные."""
    admin = make_admin(client)
    sh_mine = _mk_student(client, admin, "ivanova", "ИС-21")
    sh_other = _mk_student(client, admin, "petrov", "ИС-22")
    client.post("/me/push-token", json={"token": "dev-mine"}, headers=sh_mine)
    client.post("/me/push-token", json={"token": "dev-other"}, headers=sh_other)

    r = _override(client, admin, "ИС-21")
    assert r.status_code == 200, r.text

    tokens = [p["message"]["token"] for p in push_on]
    assert tokens == ["dev-mine"], f"уведомление ушло не туда: {tokens}"


def test_no_notification_when_nothing_actually_changed(client, push_on):
    """Админ открыл ячейку и сохранил её без правок — пуша быть не должно."""
    admin = make_admin(client)
    sh = _mk_student(client, admin, "ivanova", "ИС-21")
    client.post("/me/push-token", json={"token": "dev-mine"}, headers=sh)

    assert _override(client, admin, "ИС-21").json()["changed"] is True
    push_on.clear()
    #ровно та же правка второй раз
    r = _override(client, admin, "ИС-21")
    assert r.json()["changed"] is False, "повторное сохранение — не изменение"
    assert push_on == [], "за сохранение без правок уведомлять нельзя"


def test_real_change_notifies_again(client, push_on):
    """А вот реальная правка (сменился предмет) уведомление даёт."""
    admin = make_admin(client)
    sh = _mk_student(client, admin, "ivanova", "ИС-21")
    client.post("/me/push-token", json={"token": "dev-mine"}, headers=sh)
    _override(client, admin, "ИС-21", subject="Физика")
    push_on.clear()

    r = _override(client, admin, "ИС-21", subject="Химия")
    assert r.json()["changed"] is True
    assert len(push_on) == 1


def test_schedule_push_has_no_personal_data(client, push_on):
    """152-ФЗ: ни предмета, ни аудитории, ни ФИО — тело идёт через RuStore."""
    admin = make_admin(client)
    sh = _mk_student(client, admin, "ivanova", "ИС-21")
    client.post("/me/push-token", json={"token": "dev-mine"}, headers=sh)
    _override(client, admin, "ИС-21", subject="Физика")

    text = str(push_on[0])
    for leak in ("Физика", "301", "Ivanova", "ivanova"):
        assert leak not in text, f"в пуш утекло: {leak}"
    assert "расписание" in text.lower()


def test_removing_override_also_notifies(client, push_on):
    """Снятие правки — тоже изменение: пара вернулась к порталу, студент должен знать."""
    admin = make_admin(client)
    sh = _mk_student(client, admin, "ivanova", "ИС-21")
    client.post("/me/push-token", json={"token": "dev-mine"}, headers=sh)
    ov_id = _override(client, admin, "ИС-21").json()["id"]
    push_on.clear()

    r = client.delete(f"/web/admin/schedule/override/{ov_id}", headers=admin)
    assert r.status_code == 200, r.text
    assert len(push_on) == 1


def test_schedule_event_opens_schedule_screen(client, push_on):
    """По событию приложение понимает, что открывать расписание, а не журнал."""
    admin = make_admin(client)
    sh = _mk_student(client, admin, "ivanova", "ИС-21")
    client.post("/me/push-token", json={"token": "dev-mine"}, headers=sh)
    _override(client, admin, "ИС-21")

    event_id = push_on[0]["message"]["android"]["data"]["event_id"]
    body = client.get(f"/me/events/{event_id}", headers=sh).json()
    assert body["kind"] == "schedule"
