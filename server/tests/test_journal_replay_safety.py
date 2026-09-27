"""
test_journal_replay_safety.py — повтор записи журнала из очереди безопасен: удаление
идемпотентно, а создание занятия и итоговая называют период, которым их проштамповали
(исследование синка 25.09.2026, находки W-08, W-09).

  • W-09: запрос удаления дошёл, ответ потерялся — очередь (программы или телефона) шлёт
    его снова. Раньше повтор получал 404 и уходил в «не принято сервером»: человек видел
    тревогу «удаление не прошло» при удалённом занятии. Теперь повтор — 200 «уже удалено».
    Права проверяются ДО этого ответа: чужому он не рассказывает, что занятие было.
  • W-08: очередь программы досылает на бой период из ответа своей копии. Без него
    `_require_intended_term` на бою молчал, и занятие, созданное офлайн до смены
    семестра, ложилось в новый семестр, а в копии оставалось в прежнем.

Обратный ход (проверен): вернуть `row is None or row.deleted` → 404 — краснеет
`test_repeated_delete_is_a_success_not_a_rejection`; убрать проверку прав перед ответом
«уже удалено» — краснеет `test_already_deleted_lesson_is_not_confirmed_to_a_stranger`;
убрать `year`/`semester` из ответа создания — краснеет `test_lesson_create_names_its_term`.
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
    teacher = make_teacher(client, admin, login="treplay", subjects=(SUBJ,))
    assign_teacher(client, admin, "teach:treplay", GROUP, SUBJ)
    stranger = make_teacher(client, admin, login="tstranger", subjects=("Физика",))
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:sidorov", "role": "student", "login": "sidorov",
        "password_hash": hash_password("studpass1"), "full_name": "Сидоров Семён",
        "surname": "Сидоров", "name": "Семён", "group_name": GROUP}]}}, headers=admin)
    assert r.status_code == 200, r.text
    return {"admin": admin, "teacher": teacher, "stranger": stranger}


def _create(client, headers, **extra):
    body = {"group": GROUP, "subject": SUBJ, "type": "Практика", "topic": "Тема",
            "date": "01.09.2026", **extra}
    r = client.post("/web/teacher/lesson", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _current_term():
    from app import webdata as W
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        return W.current_term(W.load_config(db))
    finally:
        db.close()


# ── W-09 ─────────────────────────────────────────────────────────────────────────────
def test_repeated_delete_is_a_success_not_a_rejection(client, cast):
    lid = _create(client, cast["teacher"])["id"]
    first = client.delete(f"/web/teacher/lesson/{lid}", headers=cast["teacher"])
    assert first.status_code == 200, first.text
    again = client.delete(f"/web/teacher/lesson/{lid}", headers=cast["teacher"])
    assert again.status_code == 200, (
        "повтор удаления (ответ потерялся в сети) получил отказ — очередь показала бы "
        f"тревогу при удалённом занятии: {again.text}")
    body = again.json()
    assert body["already"] is True and body["id"] == lid
    assert body["updated_at"] == first.json()["updated_at"], (
        "повтор ничего не меняет — метка удаления та же")


def test_already_deleted_lesson_is_not_confirmed_to_a_stranger(client, cast):
    lid = _create(client, cast["teacher"])["id"]
    assert client.delete(f"/web/teacher/lesson/{lid}", headers=cast["teacher"]).status_code == 200
    r = client.delete(f"/web/teacher/lesson/{lid}", headers=cast["stranger"])
    assert r.status_code == 403, (
        f"чужому преподавателю «уже удалено» раскрыло бы, что занятие было: {r.status_code}")


def test_deleting_a_lesson_that_never_existed_is_still_404(client, cast):
    r = client.delete(f"/web/teacher/lesson/{uuid.uuid4()}", headers=cast["teacher"])
    assert r.status_code == 404, r.text


# ── W-08 ─────────────────────────────────────────────────────────────────────────────
def test_lesson_create_names_its_term(client, cast):
    year, semester = _current_term()
    lid = str(uuid.uuid4())
    created = _create(client, cast["teacher"], id=lid)
    assert (created.get("year"), created.get("semester")) == (year, semester), created
    replayed = _create(client, cast["teacher"], id=lid)
    assert replayed.get("replayed") is True
    assert (replayed.get("year"), replayed.get("semester")) == (year, semester), (
        "повтор создания тоже обязан назвать период — очередь досылает его как есть")


def test_term_grade_names_its_term(client, cast):
    year, semester = _current_term()
    r = client.post("/web/teacher/term-grade", json={
        "group": GROUP, "subject": SUBJ, "surname": "Сидоров", "name": "Семён",
        "student_id": "stud:sidorov", "grade": "5", "form": "экзамен"},
        headers=cast["teacher"])
    assert r.status_code == 200, r.text
    assert (r.json().get("year"), r.json().get("semester")) == (year, semester), r.json()


def test_replay_carrying_the_named_term_is_refused_once_the_term_is_over(client, cast):
    """Сквозная суть W-08: период из ответа, досланный позже, бой сверяет со своим."""
    year, semester = _current_term()
    stale_year = f"{int(year[:4]) - 1}/{int(year[:4])}"
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": "Практика", "id": str(uuid.uuid4()),
        "year": stale_year, "semester": semester}, headers=cast["teacher"])
    assert r.status_code == 409, r.text
