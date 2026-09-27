"""
test_journal_base_version.py — правка журнала, досланная очередью, не затирает чужую, а
повтор создания занятия не плодит дубли (аудит 22.09.2026, находки F-03, F-05, F-09).

━━ ЗАЧЕМ ━━
Программа выставляет оценку в своей копии мгновенно, а на бой досылает её очередью —
через минуты или дни (`desktop/desk_outbox.py`). За это время ту же оценку могли
поменять на сайте. Раньше досланная правка молча побеждала: кто позже дошёл, тот и
прав, и об этом не узнавал никто. Теперь очередь присылает `base_updated_at` — версию,
которую человек видел, когда правил, — и сервер отвечает 409 с текущим состоянием, если
запись с тех пор изменилась. Решает человек (экран конфликтов в программе).

⚠️ Сайт `base_updated_at` не шлёт — для него правило прежнее, «последняя дошедшая правка
побеждает» (§4.3). Держит `test_web_client_without_base_keeps_last_write_wins`.

Обратный ход (проверен): убрать вызов `_ensure_base_version` из `teacher_set_grade` —
краснеет `test_queued_grade_on_an_old_version_is_a_conflict`; убрать разбор `id` у
создания занятия — краснеет `test_retried_lesson_create_does_not_duplicate`.
"""
import uuid

import pytest

from conftest import make_admin, make_teacher, assign_teacher
from app.security import hash_password

GROUP = "К-24"
SUBJ = "Математика"


@pytest.fixture()
def cast(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="tbase", subjects=(SUBJ,))
    assign_teacher(client, admin, "teach:tbase", GROUP, SUBJ)
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:petrov", "role": "student", "login": "petrov",
        "password_hash": hash_password("studpass1"), "full_name": "Петров Пётр",
        "surname": "Петров", "name": "Пётр", "group_name": GROUP}]}}, headers=admin)
    assert r.status_code == 200, r.text
    return {"admin": admin, "teacher": teacher}


def _lesson(client, teacher, **extra):
    body = {"group": GROUP, "subject": SUBJ, "type": "Практика", "topic": "Тема",
            "date": "01.09.2026", **extra}
    return client.post("/web/teacher/lesson", json=body, headers=teacher)


def _grade(client, cast, lesson_id, value, **extra):
    return client.post("/web/teacher/grade", json={
        "surname": "Петров", "name": "Пётр", "lesson_id": lesson_id, "grade": value,
        **extra}, headers=cast["teacher"])


# ── F-05: идемпотентное создание занятия ─────────────────────────────────────────────
def test_retried_lesson_create_does_not_duplicate(client, cast):
    """Ответ на создание потерялся в сети, очередь повторила запрос с тем же id — занятие
    одно, второй ответ помечен как повтор и возвращает то же занятие."""
    lid = str(uuid.uuid4())
    r1 = _lesson(client, cast["teacher"], id=lid)
    r2 = _lesson(client, cast["teacher"], id=lid)
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert r1.json()["id"] == r2.json()["id"] == lid
    assert r2.json().get("replayed") is True
    journal = client.get("/web/teacher/journal", params={"group": GROUP, "subject": SUBJ},
                         headers=cast["teacher"]).json()
    ids = [l["id"] for l in journal.get("lessons", [])]
    assert ids.count(lid) == 1, f"повтор создал второе занятие: {ids}"


def test_lesson_id_collision_with_another_journal_is_refused(client, cast):
    lid = str(uuid.uuid4())
    assert _lesson(client, cast["teacher"], id=lid).status_code == 200
    r = _lesson(client, cast["teacher"], id=lid, type="Лекция")
    assert r.status_code == 409, r.text


def test_lesson_id_must_be_a_uuid(client, cast):
    r = _lesson(client, cast["teacher"], id="../../etc")
    assert r.status_code == 400, r.text


def test_create_without_id_still_gets_a_server_uuid(client, cast):
    r = _lesson(client, cast["teacher"])
    assert r.status_code == 200
    uuid.UUID(r.json()["id"])          #формат прежний


# ── F-09/F-03: базовая версия у досланной правки ─────────────────────────────────────
def test_queued_grade_on_an_old_version_is_a_conflict(client, cast):
    lid = _lesson(client, cast["teacher"]).json()["id"]
    first = _grade(client, cast, lid, "5").json()
    seen_version = first["updated_at"]                 #эту версию видела программа
    assert _grade(client, cast, lid, "4").status_code == 200   #правка «на сайте»

    r = _grade(client, cast, lid, "3", base_updated_at=seen_version)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "conflict" and detail["kind"] == "grade", detail
    assert detail["server"]["grade"] == "4", "человеку нужно показать ТЕКУЩЕЕ значение"
    now = client.get("/web/teacher/journal", params={"group": GROUP, "subject": SUBJ},
                     headers=cast["teacher"]).json()
    assert "4" in str(now), "конфликтная правка не должна была лечь"


def test_queued_grade_on_the_current_version_applies(client, cast):
    lid = _lesson(client, cast["teacher"]).json()["id"]
    current = _grade(client, cast, lid, "5").json()["updated_at"]
    r = _grade(client, cast, lid, "3", base_updated_at=current)
    assert r.status_code == 200, r.text
    assert r.json()["base_updated_at"] == current, "ответ обязан назвать затёртую версию"


def test_same_value_is_not_a_conflict(client, cast):
    """Двое поставили одно и то же — спорить не о чем."""
    lid = _lesson(client, cast["teacher"]).json()["id"]
    old = _grade(client, cast, lid, "5").json()["updated_at"]
    assert _grade(client, cast, lid, "4").status_code == 200
    r = _grade(client, cast, lid, "4", base_updated_at=old)
    assert r.status_code == 200, r.text


def test_row_created_meanwhile_is_a_conflict(client, cast):
    """Программа ставила оценку, которой у неё не было (base ''), а на сайте её тем
    временем уже поставили — тоже конфликт, а не молчаливая перезапись."""
    lid = _lesson(client, cast["teacher"]).json()["id"]
    assert _grade(client, cast, lid, "4").status_code == 200
    r = _grade(client, cast, lid, "2", base_updated_at="")
    assert r.status_code == 409, r.text


def test_web_client_without_base_keeps_last_write_wins(client, cast):
    lid = _lesson(client, cast["teacher"]).json()["id"]
    assert _grade(client, cast, lid, "5").status_code == 200
    assert _grade(client, cast, lid, "4").status_code == 200
    assert _grade(client, cast, lid, "3").status_code == 200


def test_lesson_update_on_an_old_version_is_a_conflict(client, cast):
    created = _lesson(client, cast["teacher"]).json()
    lid, seen = created["id"], created["updated_at"]
    assert client.put(f"/web/teacher/lesson/{lid}", json={"topic": "Новая тема"},
                      headers=cast["teacher"]).status_code == 200
    r = client.put(f"/web/teacher/lesson/{lid}",
                   json={"topic": "Моя тема", "base_updated_at": seen},
                   headers=cast["teacher"])
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["server"]["topic"] == "Новая тема"


def test_term_grade_on_an_old_version_is_a_conflict(client, cast):
    body = {"group": GROUP, "subject": SUBJ, "surname": "Петров", "name": "Пётр",
            "form": "экзамен"}
    first = client.post("/web/teacher/term-grade", json={**body, "grade": "5"},
                        headers=cast["teacher"]).json()
    assert client.post("/web/teacher/term-grade", json={**body, "grade": "4"},
                       headers=cast["teacher"]).status_code == 200
    r = client.post("/web/teacher/term-grade",
                    json={**body, "grade": "3", "base_updated_at": first["updated_at"]},
                    headers=cast["teacher"])
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["server"]["grade"] == "4"
