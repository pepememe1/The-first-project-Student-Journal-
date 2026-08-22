"""
test_birthday.py — день рождения студента: разбор, хранение, видимость.

⚠️ Хранится «ДД.ММ», БЕЗ ГОДА. Это не экономия поля: для поздравления год не нужен, а
полная дата рождения — совсем другой уровень чувствительности и лишний разговор при
проверке 152-ФЗ. Поэтому год, если его всё же вписали, молча отбрасывается.

Обратный ход ПРОВЕРЕН: снятие проверки диапазона в `_clean_birthday` красит
`test_impossible_dates_are_dropped`; замена «ключ присутствует» на «значение непустое» —
`test_editing_other_fields_does_not_erase_the_date`.
"""
from conftest import make_admin

from app.routers.web.write import _clean_birthday


def _student(client, admin, login="bd1", **extra):
    body = {"surname": "Будрин", "name": "Матвей", "login": login,
            "group": "К74/1", "password": "Passw0rd!"}
    body.update(extra)
    r = client.post("/web/admin/students", json=body, headers=admin)
    assert r.status_code in (200, 201), r.text
    return login


def test_parser_accepts_the_forms_a_human_actually_types():
    assert _clean_birthday("7.3") == "07.03"
    assert _clean_birthday("07.03") == "07.03"
    assert _clean_birthday("7-3") == "07.03"
    assert _clean_birthday("7/3") == "07.03"
    #Год отбрасываем молча, а не отказываем: отказ на ровном месте заставит вводить заново.
    assert _clean_birthday("07.03.2006") == "07.03"


def test_impossible_dates_are_dropped():
    """Мусор гасим в пустоту, а не сохраняем.

    Поле читает поздравление: «31.04» превратилось бы в пасхалку, которая не сработает
    НИ РАЗУ, и понять почему было бы неоткуда."""
    for bad in ("", "   ", "завтра", "0.5", "32.01", "31.04", "10.13", "-1.-1"):
        assert _clean_birthday(bad) == "", bad


def test_admin_sets_and_sees_the_date(client):
    admin = make_admin(client)
    _student(client, admin, login="bd2", birthday="07.03.2006")
    rows = client.get("/web/admin/students", headers=admin).json()["students"]
    row = next(s for s in rows if s["login"] == "bd2")
    assert row["birthday"] == "07.03", "год обязан быть отброшен"


def test_editing_other_fields_does_not_erase_the_date(client):
    """Ключа нет в теле — поле не трогаем.

    Иначе правка группы стирала бы дату рождения: форма админки шлёт только изменённое,
    и «пусто» от «не присылали» надо отличать."""
    admin = make_admin(client)
    _student(client, admin, login="bd3", birthday="01.09")
    client.put("/web/admin/students/bd3", json={"group": "К74/2"}, headers=admin)
    rows = client.get("/web/admin/students", headers=admin).json()["students"]
    assert next(s for s in rows if s["login"] == "bd3")["birthday"] == "01.09"


def test_admin_can_clear_the_date(client):
    """А явно присланная пустая строка — очищает: админ вправе передумать."""
    admin = make_admin(client)
    _student(client, admin, login="bd4", birthday="01.09")
    client.put("/web/admin/students/bd4", json={"birthday": ""}, headers=admin)
    rows = client.get("/web/admin/students", headers=admin).json()["students"]
    assert next(s for s in rows if s["login"] == "bd4")["birthday"] == ""


def test_date_is_visible_on_a_peer_profile(client):
    """Дату видно и в чужой карточке — года там нет, возраст из неё не вычислить."""
    from app.db import SessionLocal
    from app.models import User
    admin = make_admin(client)
    _student(client, admin, login="bd5", birthday="14.02")
    db = SessionLocal()
    try:
        uid = db.query(User).filter(User.login == "bd5").first().id
    finally:
        db.close()
    r = client.get(f"/web/messenger/users/{uid}/profile", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["birthday"] == "14.02"
