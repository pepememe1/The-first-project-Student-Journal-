"""
test_notifications_inbox.py — вкладка «Уведомления»: список писем, чтение, отметки,
а также РАЗЛИЧЕНИЕ «оценку поставили» и «оценку исправили».

Что здесь защищается (по убыванию цены ошибки):
  • совместимость: GET /me/events по умолчанию по-прежнему отдаёт ТОЛЬКО непрочитанные —
    его уже вызывают установленные Android-приложения, у которых старый бандл;
  • приватность: чужие события не видны и не отмечаются прочитанными;
  • правдивость: исправление оценки не выдаётся за новую оценку;
  • 152-ФЗ: балл и предмет живут в НАШЕМ письме, но не в теле пуша.
"""
import pytest

from conftest import make_admin, make_teacher, assign_teacher


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
    teach = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    return teach


def _student_headers(client):
    r = client.post("/auth/login", json={"login": "ivanova", "password": "studpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _set_grade(client, teach, value, lesson_id="L1"):
    r = client.post("/web/teacher/grade", json={
        "lesson_id": lesson_id, "surname": "Иванова", "name": "Мария", "grade": value},
        headers=teach)
    assert r.status_code == 200, r.text
    return r


def test_new_grade_letter_has_mark_and_subject(client):
    """В НАШЕМ письме балл и предмет есть — иначе оно бессмысленно (в пуше их нет,
    это проверяет test_push_notifications)."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    _set_grade(client, teach, "5")

    items = client.get("/me/events", headers=sh).json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "grade"
    assert "5" in items[0]["body"]
    assert "Математика" in items[0]["body"]


def test_changed_grade_is_not_reported_as_new(client):
    """Исправление оценки — отдельный kind и текст «X изменена на Y».

    Подмена одного другим дезинформирует: студент пойдёт искать несуществующий новый
    балл, не поняв, что исправили старый."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    _set_grade(client, teach, "3")
    _set_grade(client, teach, "5")

    items = client.get("/me/events", headers=sh).json()["items"]
    kinds = [i["kind"] for i in items]
    assert kinds.count("grade_changed") == 1, "исправление должно быть отдельным событием"
    assert kinds.count("grade") == 1, "первая простановка остаётся «новой оценкой»"

    changed = next(i for i in items if i["kind"] == "grade_changed")
    assert "3" in changed["body"] and "5" in changed["body"]

    full = client.get(f"/me/events/{changed['id']}", headers=sh).json()
    assert full["payload"] == {"old": "3", "new": "5"}


def test_same_grade_saved_twice_is_silent(client):
    """Повторное сохранение того же балла ничего не меняет — уведомлять не о чем.
    Лишние уведомления приучают отключать уведомления вовсе."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    _set_grade(client, teach, "4")
    _set_grade(client, teach, "4")

    assert client.get("/me/events", headers=sh).json()["count"] == 1


def test_grade_after_clearing_is_new_not_changed(client):
    """Снятую оценку поставили заново — это НОВАЯ оценка, а не исправление: прежнего
    значения уже не было."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    _set_grade(client, teach, "3")
    _set_grade(client, teach, "")        #сняли
    _set_grade(client, teach, "4")

    kinds = [i["kind"] for i in client.get("/me/events", headers=sh).json()["items"]]
    assert kinds.count("grade_changed") == 0
    assert kinds.count("grade") == 2


def test_default_listing_stays_unread_only(client):
    """СОВМЕСТИМОСТЬ: без параметров эндпоинт отдаёт только непрочитанные — на это
    рассчитывают уже установленные приложения. Полный список — только по ?filter=all."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    _set_grade(client, teach, "5")
    _set_grade(client, teach, "4", lesson_id="L1")   #исправление → второе событие

    ids = [i["id"] for i in client.get("/me/events", headers=sh).json()["items"]]
    assert len(ids) == 2
    client.post(f"/me/events/{ids[0]}/read", headers=sh)

    assert client.get("/me/events", headers=sh).json()["count"] == 1
    assert client.get("/me/events?filter=all", headers=sh).json()["count"] == 2


def test_unread_count_and_read_all(client):
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    _set_grade(client, teach, "5")
    _set_grade(client, teach, "4")

    assert client.get("/me/events/unread-count", headers=sh).json()["unread"] == 2
    r = client.post("/me/events/read-all", headers=sh)
    assert r.status_code == 200 and r.json()["updated"] == 2
    assert client.get("/me/events/unread-count", headers=sh).json()["unread"] == 0
    #Список при этом никуда не делся — письма прочитаны, а не удалены.
    assert client.get("/me/events?filter=all", headers=sh).json()["count"] == 2


def test_unread_count_route_is_not_eaten_by_event_id(client):
    """Регрессия на порядок маршрутов: /events/unread-count обязан идти РАНЬШЕ
    /events/{event_id}, иначе счётчик попадает в обработчик события и даёт 404."""
    admin = make_admin(client)
    _seed(client, admin)
    sh = _student_headers(client)
    r = client.get("/me/events/unread-count", headers=sh)
    assert r.status_code == 200, "маршрут перехвачен шаблоном /events/{event_id}"
    assert "unread" in r.json()


def test_foreign_event_cannot_be_read(client):
    """Чужое событие не отмечается прочитанным и отвечает 404 (не 403): 403 подтвердил
    бы факт его существования."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student_headers(client)
    _set_grade(client, teach, "5")
    event_id = client.get("/me/events", headers=sh).json()["items"][0]["id"]

    r = client.post(f"/me/events/{event_id}/read", headers=teach)
    assert r.status_code == 404
    #У владельца событие осталось непрочитанным.
    assert client.get("/me/events/unread-count", headers=sh).json()["unread"] == 1


def test_schedule_letter_tone_differs_by_role(client):
    """Заказчик просил разный тон: студенту по-дружески, преподавателю официально."""
    from app import rustore_push
    st_title, st_body = rustore_push._schedule_words("student", "ИС-21")
    tc_title, tc_body = rustore_push._schedule_words("teacher", "ИС-21")
    assert st_body != tc_body
    assert "ИС-21" in st_body and "ИС-21" in tc_body
    assert tc_body.startswith("Здравствуйте")
