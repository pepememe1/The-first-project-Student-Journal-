"""
test_group_course.py — КУРС группы: портал ВСГУТУ главнее нашего календаря.

Живой отзыв 27.08.2026: «в сортировке расписания мы уже третий курс, а в профилях
студентов всё ещё второй». Болезнь ловилась ТРИЖДЫ и каждый раз лечилась сдвигом
календарной границы термина (1 июля → 25 августа → 1 сентября, см. `db.default_term`).
Лечение не работает по построению: портал переключает курс когда переключает, и угадать
эту дату календарём нельзя. Поэтому источников теперь два, с явным порядком —
`webdata.group_course`: портал, а при его молчании формула по году поступления.

Что здесь держится (и что покраснеет, если правку откатить):
  • курс с портала ПОБЕЖДАЕТ формулу — обратный ход на дефект: столбец «3 курс» при
    формуле, дающей 2, обязан дать 3. Уберёшь приоритет портала — тест краснеет;
  • портал молчит → формула ЖИВА. Уберёшь фолбэк — краснеет;
  • профиль студента и админский список показывают ОДНО число — сторож против третьей
    версии расчёта, которая уже дважды заводилась в проекте.
"""
from app import schedule_web
from app.security import hash_password
from conftest import make_admin


GROUP = "К74/1"


def _make_group(client, admin, name=GROUP, enrollment_year=None, category=None):
    """Группа через синк (тот же путь, которым её заводит десктоп)."""
    payload = {"id": f"grp:{name}", "name": name, "subjects": []}
    if enrollment_year is not None:
        payload["enrollment_year"] = enrollment_year
    if category is not None:
        payload["category"] = category
    r = client.post("/sync/push", json={"changes": {"groups": [payload]}}, headers=admin)
    assert r.status_code == 200, r.text


def _make_student(client, admin, login="stud_c", password="studpass1", group=GROUP):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password(password), "full_name": "Иван Иванов",
        "surname": "Иванов", "name": "Иван", "group_name": group,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _portal(monkeypatch, mapping):
    """Подменяем ИНДЕКС портала: {курс: [имена групп]}. Сеть в тестах не трогаем."""
    monkeypatch.setattr(schedule_web, "groups_by_course_cached", lambda category="": mapping)


def _silent_portal(monkeypatch):
    """Портал недоступен — ровно так же, как в бою: пустой словарь, а не исключение."""
    monkeypatch.setattr(schedule_web, "groups_by_course_cached", lambda category="": {})


def _student_course(client, headers):
    r = client.get("/web/student/overview", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["course"]


def _admin_course(client, admin, login="stud_c"):
    r = client.get("/web/admin/students", headers=admin)
    assert r.status_code == 200, r.text
    row = next(s for s in r.json()["students"] if s["login"] == login)
    return row["course"]


def test_portal_course_beats_our_calendar(client, monkeypatch):
    """САМ ДЕФЕКТ: портал перевёл группу на 3 курс, формула ещё держит 2 — показываем 3."""
    admin = make_admin(client)
    #Год поступления заведомо «отстающий»: по нему формула никак не даст третий курс
    #(разница между годом термина и годом поступления — не больше единицы).
    _make_group(client, admin, enrollment_year=2025)
    stud = _make_student(client, admin)
    _portal(monkeypatch, {3: [GROUP]})

    assert _student_course(client, stud) == 3
    assert _admin_course(client, admin) == 3


def test_formula_survives_when_portal_is_silent(client, monkeypatch):
    """Обратный ход к фолбэку: без портала курс по-прежнему считается по году поступления."""
    admin = make_admin(client)
    _make_group(client, admin, enrollment_year=2025)
    stud = _make_student(client, admin)
    _silent_portal(monkeypatch)

    from app import webdata as W
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        expected = W.group_course(db, GROUP)
    finally:
        db.close()

    assert expected is not None, "формула обязана считать курс при заданном годе поступления"
    assert _student_course(client, stud) == expected


def test_group_missing_from_portal_index_falls_back(client, monkeypatch):
    """Группы нет в индексе (чужая категория, опечатка имени) — это НЕ «курс неизвестен»."""
    admin = make_admin(client)
    _make_group(client, admin, enrollment_year=2025)
    stud = _make_student(client, admin)
    _portal(monkeypatch, {1: ["К99/9"], 2: ["К88/8"]})

    assert _student_course(client, stud) is not None


def test_no_year_and_no_portal_is_honestly_unknown(client, monkeypatch):
    """Ни портала, ни года поступления → null, а НЕ выдуманный первый курс."""
    admin = make_admin(client)
    _make_group(client, admin)                     # без enrollment_year
    stud = _make_student(client, admin)
    _silent_portal(monkeypatch)

    assert _student_course(client, stud) is None
    assert _admin_course(client, admin) is None


def test_portal_course_works_without_enrollment_year(client, monkeypatch):
    """Портал знает курс — года поступления для ответа больше не требуется.

    До правки такая группа отдавала null: функция выходила на `not row.enrollment_year`
    ДО того, как вообще посмотреть на портал."""
    admin = make_admin(client)
    _make_group(client, admin)                     # без enrollment_year
    stud = _make_student(client, admin)
    _portal(monkeypatch, {4: [GROUP]})

    assert _student_course(client, stud) == 4


def test_student_and_admin_never_disagree(client, monkeypatch):
    """Два экрана — одно число. Именно расхождение этих двух и было жалобой.

    Сторож на СВОЙСТВО: он краснеет не на конкретной цифре, а на самом факте, что
    кто-то завёл вторую арифметику курса на одном из экранов."""
    admin = make_admin(client)
    _make_group(client, admin, enrollment_year=2024)
    stud = _make_student(client, admin)

    for mapping in ({3: [GROUP]}, {1: [GROUP]}, {}):
        _portal(monkeypatch, mapping)
        assert _student_course(client, stud) == _admin_course(client, admin), mapping
