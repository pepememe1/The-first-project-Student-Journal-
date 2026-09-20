"""
test_push_quiet_window.py — после первого пуша об оценке телефон замолкает на окно
(жалоба тестеров 20.09.2026: «облегчить уведомления во избежание спама об оценках»).

━━ ЧТО БЫЛО ━━
Преподаватель проставляет журнал за минуту: тридцать ячеек подряд — и у студента
тридцать пушей «у вас новая оценка». Телефон, который дёргается подряд, перестают
слушать, и следующий сигнал — про замену пары или про долг — уже не читают. Это тот же
урок, что записан про вибрацию и про лог со строкой на каждый запрос: сигнал ценен
редкостью.

⚠️ ГЛУШИТСЯ ТОЛЬКО ПУШ. Письмо во вкладке «Уведомления» создаёт вызывающий, и оно
остаётся: отключается то, что дёргает человека, а не история произошедшего. Это тот же
размен, что у выключателя категории, и проверяется он здесь отдельным тестом.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать проверку `_in_quiet_window` в `notify_login` — краснеет
первый тест; добавить "messages" в `QUIET_WINDOW_S` — краснеет тест про переписку.
"""
import app.rustore_push as push
from app import shared_state


def _reset():
    shared_state.reset_for_tests()


def test_second_grade_push_in_a_row_is_silent(monkeypatch):
    _reset()
    sent = []
    monkeypatch.setattr(push.config, "push_enabled", lambda: True)
    monkeypatch.setattr(push, "_muted_categories", lambda db, login: set())
    monkeypatch.setattr(push, "send_to_token", lambda *a, **kw: sent.append(a) or (True, 200, ""))

    class _Row:
        token, fail_count = "t1", 0

    class _Q:
        def filter(self, *a, **kw):
            return self

        def all(self):
            return [_Row()]

    class _DB:
        def query(self, *a, **kw):
            return _Q()

        def commit(self):
            pass

    db = _DB()
    data = {"type": "grade", "event_id": "e1"}
    assert push.notify_login(db, "bob", "t", "b", data) == 1, "первый пуш обязан уйти"
    assert push.notify_login(db, "bob", "t", "b", data) == 0, \
        "второй пуш об оценке ушёл сразу за первым — это и есть спам, на который жалуются"
    assert len(sent) == 1


def test_the_window_is_personal(monkeypatch):
    """Молчание у одного студента не глушит другого — иначе один заполненный журнал
    отключал бы уведомления всей группе."""
    _reset()
    monkeypatch.setattr(push.config, "push_enabled", lambda: True)
    monkeypatch.setattr(push, "_muted_categories", lambda db, login: set())
    monkeypatch.setattr(push, "send_to_token", lambda *a, **kw: (True, 200, ""))

    class _Row:
        token, fail_count = "t1", 0

    class _Q:
        def filter(self, *a, **kw):
            return self

        def all(self):
            return [_Row()]

    class _DB:
        def query(self, *a, **kw):
            return _Q()

        def commit(self):
            pass

    db = _DB()
    data = {"type": "grade", "event_id": "e1"}
    assert push.notify_login(db, "bob", "t", "b", data) == 1
    assert push.notify_login(db, "alice", "t", "b", data) == 1, \
        "окно одного человека заглушило другого"


def test_messages_are_never_delayed():
    """У переписки склейка ломает сам смысл: сообщение должно приходить сразу."""
    for category in ("messages", "reminders", "schedule", "risk", "events"):
        assert category not in push.QUIET_WINDOW_S, (
            f"категории {category!r} назначили тихое окно — этого не просили, и для "
            f"переписки это прямая поломка")


def test_the_letter_is_written_even_when_the_push_is_silent(client):
    """Главная граница правки: история не теряется, пропадает только стук в телефон."""
    from conftest import make_admin
    from app.security import hash_password

    admin = make_admin(client)
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:quiet", "role": "student", "login": "quiet",
        "password_hash": hash_password("studpass1"),
        "surname": "Тихонов", "name": "Тихон", "group_name": "К-24",
    }]}}, headers=admin)
    assert r.status_code == 200, r.text

    _reset()
    from app.db import SessionLocal
    from app.models import NotifyEvent
    db = SessionLocal()
    try:
        before = db.query(NotifyEvent).filter(NotifyEvent.login == "quiet").count()
        push.notify_new_grade(db, "quiet", subject="Физика", lesson_id="l1", value="5")
        push.notify_new_grade(db, "quiet", subject="Физика", lesson_id="l2", value="4")
        after = db.query(NotifyEvent).filter(NotifyEvent.login == "quiet").count()
    finally:
        db.close()
    assert after - before == 2, (
        "тихое окно съело ПИСЬМО, а не только пуш — студент не узнает об оценке вообще")
