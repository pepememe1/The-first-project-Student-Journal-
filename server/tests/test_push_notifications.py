"""
test_push_notifications.py — пуши о новой оценке: доставка, приватность, переходы.

Главное, что здесь защищается, — НЕ факт отправки, а два свойства:
  • в теле уведомления НЕТ персональных данных (оно идёт через серверы RuStore);
  • сбой доставки НЕ мешает преподавателю поставить оценку.
Сам RuStore не дёргаем: тест чужого сервиса — не наш тест.
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
#
#Адресность и тон писем проверяет test_schedule_conflicts.py (схема Влада: рассылка
#по кнопке «Опубликовать», а не на каждую правку ячейки). Здесь остаётся то, чего там
#нет: отсутствие ПДн в теле пуша и «пустое» сохранение ячейки.

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


def test_schedule_push_has_no_personal_data(client, push_on):
    """152-ФЗ: тело уходит через серверы RuStore, поэтому ни предмета, ни аудитории,
    ни ФИО. Подробности студент получает от НАС, открыв приложение."""
    admin = make_admin(client)
    sh = _mk_student(client, admin, "ivanova", "ИС-21")
    client.post("/me/push-token", json={"token": "dev-mine"}, headers=sh)
    _override(client, admin, "ИС-21", subject="Физика")
    client.post("/web/admin/schedule/publish", json={"group": "ИС-21"}, headers=admin)

    assert push_on, "публикация должна разослать уведомление"
    text = str(push_on[0])
    for leak in ("Физика", "301", "Ivanova", "ivanova"):
        assert leak not in text, f"в пуш утекло: {leak}"
    assert "расписан" in text.lower()


def test_saving_cell_without_changes_does_not_bump_timestamp(client):
    """Сохранение ячейки БЕЗ правок не двигает updated_at.

    Иначе строка уезжала бы в дельте синка на все ПК при каждом открытии редактора —
    трафик и лишний шум в LWW на ровном месте."""
    admin = make_admin(client)
    _override(client, admin, "ИС-21", subject="Физика")

    def _stamp():
        ch = client.get("/sync/pull", headers=admin).json()["changes"]
        return [o["updated_at"] for o in ch["schedule_overrides"]][0]

    first = _stamp()
    _override(client, admin, "ИС-21", subject="Физика")      #та же самая правка
    assert _stamp() == first, "без реальных изменений метку двигать нельзя"

    _override(client, admin, "ИС-21", subject="Химия")       #а тут уже правка
    assert _stamp() != first, "реальная правка обязана обновить метку"


# ── 152-ФЗ: у посредника не должно оседать НИЧЕГО, кроме факта «что-то пришло» ──────
def test_push_text_is_built_from_type_not_from_caller(push_on):
    """🔥 ГЛАВНОЕ СВОЙСТВО, а не частный случай: текст пуша собирает САМ `notify_login`
    по типу события, а переданные вызывающим заголовок и тело в пуш НЕ ПОПАДАЮТ.

    Почему именно так, а не «поправить восемь вызывающих»: проверка «нет ПДн» у каждого
    отправителя — это восемь мест, где однажды забудут. Ровно этим путём в пуш и уехали
    ФИО: докстринг обещал «ни ФИО», а мессенджер спокойно клал имя отправителя в
    заголовок. Здесь дверь закрыта по построению — протащить текст наружу нечем.

    Обратный ход: вернуть `send_to_token(row.token, title, body, data)` — тест краснеет.
    """
    from app import rustore_push

    class _Row:
        token, fail_count, login = "dev-1", 0, "ivanova"

    class _DB:
        def query(self, *a, **k): return self
        def filter(self, *a, **k): return self
        def all(self): return [_Row()]
        def first(self): return None
        def commit(self): pass
        def rollback(self): pass
        def delete(self, row): pass

    rustore_push.notify_login(_DB(), "ivanova",
                              "Иванова Мария Петровна",
                              "Иванова Мария: Математика, оценка 2",
                              {"type": "message", "conversation_id": "c1"})
    text = str(push_on)
    for leak in ("Иванова", "Мария", "Петровна", "Математика"):
        assert leak not in text, f"в пуш протащили: {leak}"
    assert "сообщени" in text.lower(), "человек должен понять, что именно пришло"


def test_direct_message_push_does_not_carry_sender_name(client, push_on, monkeypatch):
    """Живой путь целиком: личное сообщение → пуш. Имя отправителя раньше уезжало в
    ЗАГОЛОВОК (`messenger.py::_notify_new_message`), то есть у RuStore оседал социальный
    граф колледжа: кто кому и когда пишет.

    ⚠️ `_online_logins` подменяем ОБЯЗАТЕЛЬНО. Первая версия этого теста была ЛОЖНО
    ЗЕЛЁНОЙ: получатель только что вошёл, сервер считал его активным, пуш не отправлялся
    вовсе — и проверка «в пуше нет ФИО» проходила по пустому списку. Поймано обратным
    ходом: с откаченной починкой тест не краснел."""
    from app.routers import messenger as messenger_router
    from test_messenger import _make_student

    monkeypatch.setattr(messenger_router, "_online_logins", lambda: set())

    admin = make_admin(client)
    _seed(client, admin)
    sh = _student_headers(client)
    client.post("/me/push-token", json={"token": "dev-token-1"}, headers=sh)
    _, bob = _make_student(client, admin, "bob", "Боб Бобов")

    r = client.post("/web/messenger/chats/direct/stud:ivanova", headers=bob)
    assert r.status_code == 200, r.text
    conv = r.json()["conversation_id"]
    client.post(f"/web/messenger/chats/{conv}/messages",
                json={"body": "привет, встретимся в 14:00"}, headers=bob)

    assert push_on, "пуш не ушёл вовсе — тест ничего не проверяет (см. _online_logins)"
    text = str(push_on)
    for leak in ("Боб", "Бобов", "bob", "встретимся"):
        assert leak not in text, f"в пуш утекло: {leak}"


def test_only_notify_login_may_send_a_push():
    """СТРУКТУРНЫЙ сторож: `send_to_token` зовётся ровно из одного места.

    Нейтрализация текста живёт внутри `notify_login`. Появится второй вызывающий —
    и он унесёт в RuStore что угодно, а тесты выше этого не заметят: они проверяют
    поведение `notify_login`, а не отсутствие обходных путей."""
    import re
    from pathlib import Path

    #Смотрим и server/app, и КОРНЕВЫЕ общие модули: они тоже деплоятся на бой
    #(grading.py, voice_command.py и т.п.), и вызов оттуда сторож обязан видеть.
    repo = Path(__file__).resolve().parents[2]
    files = list((repo / "server" / "app").rglob("*.py")) + list(repo.glob("*.py"))
    callers = []
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "def send_to_token" in line:
                continue
            if re.search(r"send_to_token\s*\(", line):
                callers.append(f"{f.name}:{i}")
    #⚠️ Номер строки в ожидание НЕ вписываем: он сдвигается при любой правке файла, и
    #сторож начинает краснеть на ровном месте — а чинят такое «обновлением ожидания»,
    #то есть ровно тем, от чего он защищает. Проверяем СВОЙСТВО: вызывающий один, и он
    #в rustore_push.py.
    assert len(callers) == 1 and callers[0].startswith("rustore_push.py:"),         f"пуш отправляется мимо нейтрализации: {callers}"
