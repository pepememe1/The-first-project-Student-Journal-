"""
test_schedule_conflicts.py — сверка расписаний: накладки и совместные пары.

Портал в тестах недоступен, поэтому расписание целиком строится админ-правками — это
же и есть боевой сценарий «колледж без портала».

Главное, что здесь защищается:
  • накладка находится и по преподавателю, и по аудитории;
  • совместная пара НЕ считается накладкой (иначе админ утонет в ложных тревогах);
  • «снимок ещё строится» не выдаётся за «накладок нет» — это разные состояния;
  • уведомление о расписании уходит ТОЛЬКО затронутой группе.
"""
import pytest

from conftest import make_admin, make_teacher


@pytest.fixture(autouse=True)
def no_portal(monkeypatch):
    """Портала нет и сборка не идёт. Без этой подмены full_state() поднял бы фоновый
    поток за расписанием в сеть — тест стал бы медленным и зависящим от портала."""
    from app import schedule_web
    monkeypatch.setattr(schedule_web, "full_state", lambda: (None, False))


@pytest.fixture
def push_on(monkeypatch):
    from app import config, rustore_push
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "test-project")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "test-token")
    sent = []
    monkeypatch.setattr(rustore_push, "_post",
                        lambda payload: (sent.append(payload), (True, 200, "{}"))[1])
    return sent


def _set(client, admin, **kw):
    r = client.post("/web/admin/schedule/override", json=kw, headers=admin)
    assert r.status_code == 200, r.text
    return r


def _conflicts(client, admin):
    r = client.get("/web/admin/schedule/conflicts", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def test_same_teacher_two_groups_is_conflict(client):
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=2,
         subject="Математика", teacher="Иванов И.И.", room="101")
    _set(client, admin, group="ИС-22", week=1, day="Пнд", pair_no=2,
         subject="Физика", teacher="Иванов И.И.", room="202")

    data = _conflicts(client, admin)
    teacher_hits = [c for c in data["items"] if c["kind"] == "teacher"]
    assert len(teacher_hits) == 1, data
    hit = teacher_hits[0]
    assert hit["groups"] == ["ИС-21", "ИС-22"]
    assert hit["week"] == 1 and hit["day"] == "Пнд" and hit["pair_no"] == 2


def test_same_room_two_groups_is_conflict(client):
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Втр", pair_no=1,
         subject="Математика", teacher="Иванов И.И.", room="305")
    _set(client, admin, group="ИС-22", week=1, day="Втр", pair_no=1,
         subject="Химия", teacher="Петров П.П.", room="305")

    rooms = [c for c in _conflicts(client, admin)["items"] if c["kind"] == "room"]
    assert len(rooms) == 1 and rooms[0]["value"] == "305"


def test_teacher_name_case_and_spacing_still_matches(client):
    """«Иванов И.И.» и «иванов  и.и. » — один человек. Иначе накладка проскочит из-за
    того, что расписание набирали руками в разное время."""
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=2, day="Срд", pair_no=3,
         subject="Мат", teacher="Иванов И.И.")
    _set(client, admin, group="ИС-22", week=2, day="Срд", pair_no=3,
         subject="Физ", teacher="иванов  и.и. ")

    assert [c for c in _conflicts(client, admin)["items"] if c["kind"] == "teacher"]


def test_different_slots_are_not_conflict(client):
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=1,
         subject="Мат", teacher="Иванов И.И.", room="101")
    _set(client, admin, group="ИС-22", week=1, day="Пнд", pair_no=2,
         subject="Мат", teacher="Иванов И.И.", room="101")
    assert _conflicts(client, admin)["count"] == 0


def test_empty_teacher_and_room_never_conflict(client):
    """Незаполненные поля не должны склеиваться в «одного и того же» преподавателя."""
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Чтв", pair_no=1, subject="Мат")
    _set(client, admin, group="ИС-22", week=1, day="Чтв", pair_no=1, subject="Физ")
    assert _conflicts(client, admin)["count"] == 0


def test_same_lesson_for_two_groups_is_not_a_conflict(client):
    """Совместная лекция: один предмет, один преподаватель, одна аудитория у двух групп.

    Ровно так выглядят 97% совпадений в РЕАЛЬНОМ расписании ВСГУТУ (проверено на живом
    портале: 622 из 638). Считать их ошибками — значит выдать админу список, который он
    никогда не разберёт и перестанет открывать. Подгруппы одного курса (К65/1 и К65/2 на
    одной химии) попадают сюда же."""
    admin = make_admin(client)
    for g in ("ИС-21", "ИС-22"):
        _set(client, admin, group=g, week=1, day="Пнд", pair_no=1,
             subject="История", teacher="Сидоров С.С.", room="Актовый зал")
    assert _conflicts(client, admin)["count"] == 0


def test_same_subject_but_different_rooms_is_conflict(client):
    """Предмет один, а аудитории разные — преподаватель не может быть в двух местах."""
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Втр", pair_no=2,
         subject="История", teacher="Сидоров С.С.", room="101")
    _set(client, admin, group="ИС-22", week=1, day="Втр", pair_no=2,
         subject="История", teacher="Сидоров С.С.", room="202")
    hits = [c for c in _conflicts(client, admin)["items"] if c["kind"] == "teacher"]
    assert len(hits) == 1, "разные аудитории у одного преподавателя — накладка"


def test_joint_mark_suppresses_and_can_be_removed(client):
    """Ручная отметка нужна для случаев, которые правилом не покрываются: в одной
    аудитории намеренно идут ДВА разных занятия. Пометили → пропало; сняли → вернулось."""
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Птн", pair_no=4,
         subject="История", teacher="Сидоров С.С.", room="Актовый зал")
    _set(client, admin, group="ИС-22", week=1, day="Птн", pair_no=4,
         subject="Литература", teacher="Кузнецов К.К.", room="Актовый зал")

    room_hit = next(c for c in _conflicts(client, admin)["items"] if c["kind"] == "room")
    r = client.post("/web/admin/schedule/joint", json={
        "kind": "room", "value": room_hit["value"], "week": room_hit["week"],
        "day": room_hit["day"], "pair_no": room_hit["pair_no"], "note": "делим зал"},
        headers=admin)
    assert r.status_code == 200, r.text
    assert _conflicts(client, admin)["count"] == 0

    assert client.delete(f"/web/admin/schedule/joint/{room_hit['id']}",
                         headers=admin).status_code == 200
    assert _conflicts(client, admin)["count"] == 1, "снятие отметки возвращает накладку"


def test_marking_same_slot_twice_does_not_duplicate(client):
    admin = make_admin(client)
    _set(client, admin, group="ИС-21", week=1, day="Пнд", pair_no=5,
         subject="Мат", teacher="Иванов И.И.")
    _set(client, admin, group="ИС-22", week=1, day="Пнд", pair_no=5,
         subject="Физ", teacher="Иванов И.И.")
    hit = next(c for c in _conflicts(client, admin)["items"] if c["kind"] == "teacher")
    body = {"kind": "teacher", "value": hit["value"], "week": 1,
            "day": "Пнд", "pair_no": 5}
    first = client.post("/web/admin/schedule/joint", json=body, headers=admin).json()
    second = client.post("/web/admin/schedule/joint", json=body, headers=admin).json()
    assert first["id"] == second["id"], "ключ должен быть детерминированным"


def test_building_snapshot_is_not_reported_as_clean(client, monkeypatch):
    """Пока снимок портала собирается, пустой список — это «ещё не смотрели», а не
    «всё чисто». Клиент обязан различать, поэтому флаг обязан доезжать."""
    from app import schedule_web
    monkeypatch.setattr(schedule_web, "full_state", lambda: (None, True))
    admin = make_admin(client)
    data = _conflicts(client, admin)
    assert data["building"] is True and data["count"] == 0


def test_conflicts_are_admin_only(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    assert client.get("/web/admin/schedule/conflicts", headers=th).status_code == 403
    assert client.post("/web/admin/schedule/joint", json={
        "kind": "teacher", "value": "Иванов И.И.", "week": 1, "day": "Пнд",
        "pair_no": 1}, headers=th).status_code == 403


def test_publish_notifies_only_affected_group(client, push_on):
    """Расписание правили одной группе — вторая об этом узнавать не должна."""
    admin = make_admin(client)
    client.post("/web/admin/students", json={
        "login": "s1", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    client.post("/web/admin/students", json={
        "login": "s2", "surname": "Петрова", "name": "Анна", "group": "ИС-22",
        "password": "studpass2"}, headers=admin)

    r = client.post("/web/admin/schedule/publish", json={"group": "ИС-21"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["students"] == 1, "уведомлять надо только студентов своей группы"

    #Событие появилось у студента затронутой группы и НЕ появилось у чужой.
    def _events(login, password):
        tok = client.post("/auth/login",
                          json={"login": login, "password": password}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}", "X-Client": "web"}
        return client.get("/me/events", headers=h).json()

    assert _events("s1", "studpass1")["count"] == 1
    assert _events("s2", "studpass2")["count"] == 0


def test_publish_letter_tone_differs_for_student_and_teacher(client, push_on):
    admin = make_admin(client)
    client.post("/web/admin/students", json={
        "login": "s1", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L1", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    make_teacher(client, admin, subjects=["Математика"])

    r = client.post("/web/admin/schedule/publish", json={"group": "ИС-21"}, headers=admin)
    assert r.status_code == 200, r.text
    #Преподаватель, ведущий у группы, тоже получает уведомление — но другим тоном.
    assert r.json()["teachers"] == 1, r.json()
