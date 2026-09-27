"""
test_desk_write_policy.py — ПРОВОДКА политики записи на НАСТОЯЩЕМ локальном сервере
программы (аудит 22.09.2026, находка F-02, P1).

Правила очереди проверяет `test_desk_outbox.py`. Здесь — то, без чего они не значат
ничего: что запрос интерфейса ДЕЙСТВИТЕЛЬНО до них доходит. Это наш самый частый класс
дефекта — «обещание без вызывающего»: очередь могла быть написана, покрыта тестами и не
подключена к серверу, и всё было бы зелёным.

  • оценка и занятие, выставленные через HTTP, лежат в копии И стоят в очереди;
  • запись справочника (не журнал) уходит на бой: без связи — 503 с «НЕ сохранено», и
    в копии от неё НЕ остаётся следа (раньше она молча оседала там с ответом 200);
  • явно локальное (Вектор) обслуживается копией и без связи.

Обратный ход (проверен): убрать `install_write_policy(app)` из `LocalAPI.start` —
краснеют оба теста записи; третий держит обратное направление (локальное не уходит
на бой) и зелен с политикой и без неё — он страхует от «починки», пересылающей всё.
"""
import json
import os
import tempfile
import urllib.error
import urllib.request

import pytest

from desktop import desk_outbox, local_api

GROUP, SUBJ = "К-24", "Математика"


@pytest.fixture(scope="module")
def api():
    tmp_db = os.path.join(tempfile.mkdtemp(), "write_policy.db").replace("\\", "/")
    os.environ["GRADEBOOK_DB_URL"] = f"sqlite:///{tmp_db}"
    srv = local_api.LocalAPI()
    if not srv.start():
        pytest.fail(f"локальный сервер не поднялся: {srv.error}")
    _seed()
    yield srv
    srv.stop()


def _seed():
    from app.db import SessionLocal
    from app.models import Group, SubjectHours, User, subject_hours_id
    from app import webdata as W
    db = SessionLocal()
    try:
        ty, ts = W.current_term(W.load_config(db))
        now = "2026-09-25T00:00:00+00:00"
        db.merge(User(id="teach:tw", login="tw", role="teacher", full_name="Тестов Т.",
                      subjects=[SUBJ], deleted=False, updated_at=now))
        db.merge(User(id="admin:aw", login="aw", role="admin", full_name="Админ",
                      deleted=False, updated_at=now))
        db.merge(User(id="stud:sw", login="sw", role="student", surname="Петров",
                      name="Пётр", group_name=GROUP, deleted=False, updated_at=now))
        db.merge(Group(id=f"grp:{GROUP}", name=GROUP, subjects=[SUBJ], deleted=False,
                       updated_at=now))
        db.merge(SubjectHours(id=subject_hours_id(GROUP, SUBJ, ty, ts), group_name=GROUP,
                              subject=SUBJ, year=ty, semester=ts, teacher_id="teach:tw",
                              deleted=False, updated_at=now))
        db.commit()
    finally:
        db.close()


def _call(api, method, path, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(api.url(path), data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "X-Client": "web"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


@pytest.fixture()
def as_teacher(api, monkeypatch):
    monkeypatch.setattr(local_api, "_session_login", lambda: "tw")
    #Фоновая досылка в тесте не нужна: проверяется, что правка ВСТАЛА в очередь.
    monkeypatch.setattr(desk_outbox, "kick", lambda: None)
    token, _ = local_api.issue_local_session("tw", "teacher")
    assert token
    return token


def test_journal_write_goes_to_the_outbox(api, as_teacher):
    before = desk_outbox.counts("tw")["pending"]
    code, lesson = _call(api, "POST", "/web/teacher/lesson", as_teacher,
                         {"group": GROUP, "subject": SUBJ, "type": "Практика",
                          "topic": "Дроби", "date": "25.09.2026"})
    assert code == 200, lesson
    code, grade = _call(api, "POST", "/web/teacher/grade", as_teacher,
                        {"surname": "Петров", "name": "Пётр", "lesson_id": lesson["id"],
                         "grade": "5"})
    assert code == 200, grade
    assert desk_outbox.counts("tw")["pending"] == before + 2, (
        "правка журнала легла в копию, но в очередь на бой не встала — ровно дефект F-02")
    keys = desk_outbox.pending_keys("tw")
    assert ("lessons", lesson["id"]) in keys and ("grades", grade["id"]) in keys


def test_directory_write_goes_to_the_server_not_into_the_copy(api, monkeypatch):
    """Запись справочника без связи — честный отказ, и в копии от неё ничего нет."""
    monkeypatch.setattr(local_api, "_session_login", lambda: "aw")
    monkeypatch.setattr(local_api, "_remote_auth", lambda: ("", "", "offline"))
    token, _ = local_api.issue_local_session("aw", "admin")
    code, body = _call(api, "POST", "/web/admin/groups", token,
                       {"name": "НОВАЯ-1", "subjects": [SUBJ]})
    assert code == 503, (code, body)
    assert "НЕ сохранено" in body.get("detail", ""), body
    from app.db import SessionLocal
    from app.models import Group
    db = SessionLocal()
    try:
        assert db.get(Group, "grp:НОВАЯ-1") is None, (
            "запись справочника осела в локальной копии — на бой она не ушла бы никогда")
    finally:
        db.close()


def test_local_by_design_is_served_by_the_copy(api, as_teacher, monkeypatch):
    """Вектор отвечает по копии и без связи — это и есть его офлайн-режим."""
    monkeypatch.setattr(local_api, "_remote_auth", lambda: ("", "", "offline"))
    code, body = _call(api, "POST", "/web/vector/ask", as_teacher, {"question": "привет"})
    assert code == 200, (code, body)
