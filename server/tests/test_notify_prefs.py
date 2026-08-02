"""
test_notify_prefs.py — человек отключает категорию уведомлений, и она перестаёт приходить.

Что здесь защищается:
  • ЕДИНСТВЕННОСТЬ проверки. Пуши уходят из восьми мест (оценка, ДЗ, расписание,
    сообщение, отметка, мероприятие, напоминание, системный канал). Проверка стоит в
    `notify_login`, через который проходят ВСЕ; вынеси её к вызывающим — и достаточно
    забыть одно место, чтобы отключённое продолжало приходить.
  • «НАСТРОЙКИ НЕТ» ЗНАЧИТ «ВКЛЮЧЕНО». У всех уже заведённых пользователей поля `notify`
    в prefs просто нет, и трактовка пустоты как запрета молча выключила бы уведомления
    всему колледжу при первом же обновлении.
  • ИСТОРИЯ ОСТАЁТСЯ. Выключатель гасит пуш, а не запись во вкладке «Уведомления»:
    иначе студент, приглушивший телефон, потерял бы сам факт выставленной оценки.
  • МУСОР В ПОЛЕ НЕ ПРОХОДИТ. Значение читает сервер, а строка "false" в Python
    истинна — то есть выключенная в интерфейсе категория продолжала бы приходить.
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
    """Студент, занятие и преподаватель по нему. Возвращает заголовок преподавателя."""
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L1", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    teach = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    return teach


def _student(client):
    r = client.post("/auth/login", json={"login": "ivanova", "password": "studpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _grade(client, teach, value="5"):
    return client.post("/web/teacher/grade", json={
        "lesson_id": "L1", "surname": "Иванова", "name": "Мария", "grade": value},
        headers=teach)


def test_grades_arrive_when_nothing_is_configured(client, push_on):
    """Отсутствие настройки — это «присылать». Иначе обновление выключило бы всем всё."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student(client)
    client.post("/me/push-token", json={"token": "dev-1"}, headers=sh)
    _grade(client, teach)
    assert len(push_on) == 1


def test_disabled_category_stops_the_push(client, push_on):
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student(client)
    client.post("/me/push-token", json={"token": "dev-1"}, headers=sh)
    assert client.post("/me/prefs", json={"notify": {"grades": False}},
                       headers=sh).status_code == 200

    _grade(client, teach)
    assert push_on == [], "оценки отключены — пуш идти не должен"


def test_disabling_one_category_does_not_touch_the_others(client, push_on):
    """Отключены сообщения, а оценка приходит: категории независимы."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student(client)
    client.post("/me/push-token", json={"token": "dev-1"}, headers=sh)
    client.post("/me/prefs", json={"notify": {"messages": False}}, headers=sh)

    _grade(client, teach)
    assert len(push_on) == 1


def test_history_survives_the_switch(client, push_on):
    """Выключатель гасит ПУШ, а не запись: без этого студент, приглушивший телефон,
    терял бы сам факт оценки, а не только звук."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student(client)
    client.post("/me/push-token", json={"token": "dev-1"}, headers=sh)
    client.post("/me/prefs", json={"notify": {"grades": False}}, headers=sh)

    _grade(client, teach)
    assert push_on == []
    events = client.get("/me/events", params={"filter": "all"}, headers=sh).json()
    assert any(e["kind"] == "grade" for e in events["items"]), \
        "письмо во вкладке «Уведомления» обязано остаться"


def test_switch_can_be_turned_back_on(client, push_on):
    admin = make_admin(client)
    teach = _seed(client, admin)
    sh = _student(client)
    client.post("/me/push-token", json={"token": "dev-1"}, headers=sh)
    client.post("/me/prefs", json={"notify": {"grades": False}}, headers=sh)
    client.post("/me/prefs", json={"notify": {"grades": True}}, headers=sh)

    _grade(client, teach)
    assert len(push_on) == 1


def test_garbage_in_the_field_is_normalised(client):
    """Сервер читает это поле при каждой отправке. Строка "false" в Python ИСТИННА —
    без приведения к bool выключенная в интерфейсе категория продолжала бы приходить.
    Незнакомые ключи выбрасываем: список категорий задаёт сервер."""
    admin = make_admin(client)
    _seed(client, admin)
    sh = _student(client)
    r = client.post("/me/prefs", json={"notify": {
        "grades": "false", "messages": 0, "выдуманное": True}}, headers=sh)
    assert r.status_code == 200, r.text
    box = r.json()["prefs"]["notify"]
    assert box == {"grades": True, "messages": False}, box


def test_non_dict_notify_is_dropped(client):
    """`notify` строкой не свалит отправку: у строки нет .get, и первый же пуш упал бы
    внутри проверки категории."""
    admin = make_admin(client)
    _seed(client, admin)
    sh = _student(client)
    r = client.post("/me/prefs", json={"notify": "всё выключить"}, headers=sh)
    assert r.status_code == 200, r.text
    assert "notify" not in r.json()["prefs"]


def test_every_push_type_has_a_category():
    """Каждый вид пуша обязан попадать в известную категорию.

    Иначе новый вид уведомления окажется неотключаемым: пользователь видит шесть
    переключателей, а приходит седьмое, которое ими не гасится."""
    from app import rustore_push
    known = set(rustore_push.ALL_CATEGORIES)
    for kind, category in rustore_push.CATEGORY_BY_TYPE.items():
        assert category in known, f"{kind} → неизвестная категория {category}"


def test_categories_match_the_settings_page():
    """Ключи на странице настроек и на сервере — один список.

    Разъедутся — переключатель будет писать в поле, которого сервер не читает, и
    «выключено» останется включённым. Читаем сам файл страницы: тест на веб-часть
    здесь дешевле, чем целый стенд для Vue."""
    import pathlib
    import re
    page = (pathlib.Path(__file__).resolve().parents[2]
            / "web" / "src" / "pages" / "Settings.vue").read_text(encoding="utf-8")
    block = page.split("const NOTIFY_KINDS = computed(() => [", 1)[1].split("]", 1)[0]
    from app import rustore_push
    assert set(re.findall(r"key:\s*'([a-z]+)'", block)) == set(rustore_push.ALL_CATEGORIES)
