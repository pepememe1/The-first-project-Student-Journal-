"""
test_homework.py — домашнее задание как тип занятия (3.1).

Что защищается:
  • нумерация ДЗ идёт СВОЕЙ дорожкой и начинается с №1 (требование заказчика);
  • при создании ДЗ уведомление получает ВСЯ группа, и текст задания есть в письме;
  • ДЗ, созданное на ДЕСКТОПЕ, доезжает синком и тоже уведомляет — иначе фича работала
    бы только для тех, кто ведёт журнал с сайта, а эталон у нас десктоп;
  • повторный push того же ДЗ НЕ шлёт уведомление второй раз (полный снимок уезжает
    заново каждые N циклов — без защиты группа получала бы одно и то же ДЗ вечно);
  • оценка за ДЗ идёт в средний балл наравне с практикой.
"""
import pytest

from conftest import make_admin, make_teacher


@pytest.fixture(autouse=True)
def push_on(monkeypatch):
    """Пуши включены, сеть подменена списком (как в test_notifications_inbox)."""
    from app import config, rustore_push
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "test-project")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "test-token")
    sent = []

    def fake_post(payload):
        sent.append(payload)
        return True, 200, "{}"
    monkeypatch.setattr(rustore_push, "_post", fake_post)
    return sent


def _student(client, admin, login="ivanova", surname="Иванова", name="Мария"):
    r = client.post("/web/admin/students", json={
        "login": login, "surname": surname, "name": name, "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text


def _headers(client, login="ivanova"):
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _events(client, headers, kind=None):
    r = client.get("/me/events?limit=100&all=1", headers=headers)
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    return [i for i in items if kind is None or i.get("kind") == kind]


def test_homework_numbering_starts_at_one_independently(client):
    """У ДЗ своя нумерация: две практики уже есть, а первое ДЗ всё равно №1."""
    admin = make_admin(client)
    teach = make_teacher(client, admin, subjects=["Математика"])
    for n in (1, 2):
        r = client.post("/web/teacher/lesson", json={
            "group": "ИС-21", "subject": "Математика", "type": "Практика",
            "topic": f"п{n}"}, headers=teach)
        assert r.status_code == 200, r.text
        assert r.json()["number"] == n

    r = client.post("/web/teacher/lesson", json={
        "group": "ИС-21", "subject": "Математика", "type": "ДЗ",
        "topic": "создать базу данных"}, headers=teach)
    assert r.status_code == 200, r.text
    assert r.json()["number"] == 1, "первое ДЗ обязано быть №1, а не продолжать практики"

    r = client.post("/web/teacher/lesson", json={
        "group": "ИС-21", "subject": "Математика", "type": "ДЗ",
        "topic": "нормализация"}, headers=teach)
    assert r.json()["number"] == 2


def test_homework_notifies_whole_group_with_task_text(client):
    admin = make_admin(client)
    _student(client, admin)
    _student(client, admin, login="petrov", surname="Петров", name="Пётр")
    teach = make_teacher(client, admin, subjects=["Математика"])

    r = client.post("/web/teacher/lesson", json={
        "group": "ИС-21", "subject": "Математика", "type": "ДЗ",
        "topic": "создать базу данных"}, headers=teach)
    assert r.status_code == 200, r.text

    for login in ("ivanova", "petrov"):
        hw = _events(client, _headers(client, login), kind="homework")
        assert len(hw) == 1, f"{login}: ожидалось одно письмо о ДЗ, пришло {len(hw)}"
        assert "Математика" in hw[0]["title"], hw[0]
        assert "создать базу данных" in hw[0]["body"], hw[0]


def test_homework_task_text_not_in_push_body(client, push_on):
    """Само задание идёт в НАШЕ письмо, но не в тело пуша: пуш проходит через RuStore."""
    admin = make_admin(client)
    _student(client, admin)
    teach = make_teacher(client, admin, subjects=["Математика"])
    client.post("/web/teacher/lesson", json={
        "group": "ИС-21", "subject": "Математика", "type": "ДЗ",
        "topic": "секретная тема задания"}, headers=teach)

    blob = str(push_on)
    assert "секретная тема задания" not in blob, "текст задания утёк в пуш"


def test_homework_from_desktop_sync_notifies_group(client):
    """Преподаватель создал ДЗ на десктопе → оно приезжает push'ем → группа уведомлена."""
    admin = make_admin(client)
    _student(client, admin)
    teach = make_teacher(client, admin, subjects=["Математика"])

    lesson = {"id": "HW-1", "group_name": "ИС-21", "subject": "Математика", "type": "ДЗ",
              "number": 1, "topic": "сделать лабораторную", "date": "01.09.2025"}
    r = client.post("/sync/push", json={"changes": {"lessons": [lesson]}}, headers=teach)
    assert r.status_code == 200, r.text

    hw = _events(client, _headers(client), kind="homework")
    assert len(hw) == 1, hw
    assert "сделать лабораторную" in hw[0]["body"], hw[0]


def test_repeated_full_push_does_not_resend_homework(client):
    """Полный снимок уезжает заново каждые N циклов. Уведомление должно быть ОДНО."""
    admin = make_admin(client)
    _student(client, admin)
    teach = make_teacher(client, admin, subjects=["Математика"])

    lesson = {"id": "HW-1", "group_name": "ИС-21", "subject": "Математика", "type": "ДЗ",
              "number": 1, "topic": "сделать лабораторную", "date": "01.09.2025"}
    for _ in range(3):
        r = client.post("/sync/push", json={"changes": {"lessons": [lesson]}}, headers=teach)
        assert r.status_code == 200, r.text

    hw = _events(client, _headers(client), kind="homework")
    assert len(hw) == 1, f"повторный push продублировал уведомление: {len(hw)}"


def test_homework_grade_counts_into_average(client):
    """Оценка за ДЗ участвует в среднем балле наравне с практикой (решение заказчика)."""
    admin = make_admin(client)
    _student(client, admin)
    teach = make_teacher(client, admin, subjects=["Математика"])

    prac = client.post("/web/teacher/lesson", json={
        "group": "ИС-21", "subject": "Математика", "type": "Практика", "topic": "п"},
        headers=teach).json()["id"]
    hw = client.post("/web/teacher/lesson", json={
        "group": "ИС-21", "subject": "Математика", "type": "ДЗ", "topic": "д"},
        headers=teach).json()["id"]

    for lid, val in ((prac, "5"), (hw, "3")):
        r = client.post("/web/teacher/grade", json={
            "lesson_id": lid, "surname": "Иванова", "name": "Мария", "grade": val},
            headers=teach)
        assert r.status_code == 200, r.text

    r = client.get("/web/teacher/journal?group=ИС-21&subject=Математика", headers=teach)
    assert r.status_code == 200, r.text
    row = next(s for s in r.json()["students"] if s["surname"] == "Иванова")
    assert row["average"] == 4.0, f"ДЗ не учтено в среднем: {row}"
