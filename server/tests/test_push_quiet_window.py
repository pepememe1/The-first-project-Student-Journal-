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


#──────────────────────────────────────────────────────────────────────────────────────
#ПОЧИНКА 21.09.2026: окно закрывается ТОЛЬКО после настоящей отправки.
#
#Было: `_in_quiet_window` сама ставила метку — то есть окно закрывалось в момент
#ПРОВЕРКИ, раньше, чем пуш кому-то ушёл. Человек без установленного приложения, отказ
#RuStore и упавшая отправка давали один и тот же тихий результат: первое уведомление
#потеряно, а следующие десять минут заглушены «потому что первое уже было».
#
#⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть `shared_state.set` внутрь `_in_quiet_window` —
#краснеют оба теста ниже.
def _db_with_tokens(tokens):
    class _Row:
        def __init__(self, t):
            self.token, self.fail_count = t, 0

    rows = [_Row(t) for t in tokens]

    class _Q:
        def filter(self, *a, **kw):
            return self

        def all(self):
            return rows

    class _DB:
        def query(self, *a, **kw):
            return _Q()

        def commit(self):
            pass

    return _DB()


def test_a_push_that_never_left_does_not_close_the_window(monkeypatch):
    """У человека нет ни одного устройства — глушить его нечем и не за что."""
    _reset()
    monkeypatch.setattr(push.config, "push_enabled", lambda: True)
    monkeypatch.setattr(push, "_muted_categories", lambda db, login: set())
    data = {"type": "grade", "event_id": "e1"}

    assert push.notify_login(_db_with_tokens([]), "nodev", "t", "b", data) == 0

    #Ставит приложение через минуту — и первый же настоящий пуш обязан дойти.
    sent = []
    monkeypatch.setattr(push, "send_to_token",
                        lambda *a, **kw: sent.append(a) or (True, 200, ""))
    assert push.notify_login(_db_with_tokens(["t1"]), "nodev", "t", "b", data) == 1, (
        "окно закрылось от пуша, которого не было: человек не получил ПЕРВОЕ уведомление")
    assert len(sent) == 1


def test_a_failing_rustore_does_not_stall_the_journal(monkeypatch):
    """RuStore лежит — окно всё равно закрывается, и это ОСОЗНАННЫЙ размен.

    🔥 Здесь сначала стояло обратное утверждение («отказ RuStore не закрывает окно»), и
    оно было вредным — нашёл Полковник 21.09.2026. При лежащем RuStore `sent` равен нулю
    у каждого вызова, то есть окно не закрывалось бы НИКОГДА: все тридцать оценок,
    которые преподаватель ставит подряд, делали бы настоящий HTTP с таймаутом 8 с прямо
    в его запросе (журнал встаёт на четыре минуты), а после трёх неудач подряд
    `fail_count >= MAX_FAILS` УДАЛЯЕТ токен студента — пуши у него пропадают до
    переустановки приложения.

    Поэтому граница проходит по НАЛИЧИЮ УСТРОЙСТВ, а не по успеху: попытка состоялась —
    окно закрыто. Цена названа прямо: при отказе RuStore первое уведомление теряется.
    Это дешевле неработающего журнала и стёртого токена."""
    _reset()
    monkeypatch.setattr(push.config, "push_enabled", lambda: True)
    monkeypatch.setattr(push, "_muted_categories", lambda db, login: set())
    tries = []
    monkeypatch.setattr(push, "send_to_token",
                        lambda *a, **kw: tries.append(a) or (False, 503, "down"))
    data = {"type": "grade", "event_id": "e1"}

    for _ in range(5):
        push.notify_login(_db_with_tokens(["t1"]), "bob", "t", "b", data)
    assert len(tries) == 1, (
        f"лежащий RuStore получил {len(tries)} запросов подряд по 8 с каждый — столько "
        f"же раз подвис журнал преподавателя, и токен студента будет удалён")


def test_checking_the_window_never_changes_it(monkeypatch):
    """Предикат обязан быть предикатом: иначе метка снова окажется раньше отправки.

    Это и есть корень дефекта — проверку нельзя было позвать «просто посмотреть»."""
    _reset()
    assert push._in_quiet_window("grades", "bob") is False
    assert push._in_quiet_window("grades", "bob") is False, (
        "проверка окна сама его и закрыла — значит снова меняет состояние")
    push._mark_pushed("grades", "bob")
    assert push._in_quiet_window("grades", "bob") is True
