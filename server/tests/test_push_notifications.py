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
