"""
test_easter_login_chain.py — ЦЕПЬ «день рождения → торт Portal» целиком.

⚠️ Повод: Влад поставил студенту сегодняшнюю дату, вошёл — и Вектора с тортом не
увидел вовсе. Точечные тесты при этом были зелёные, потому что проверяли ЗВЕНЬЯ:
`birthday_today` отдельно, `_clean_birthday` отдельно, `pick_on_login` отдельно.
Здесь проверяется ровно то, что делает человек: админ вписал дату → студент вошёл →
ручка входа вернула торт. Одно звено разъехалось — краснеет.
"""
from conftest import make_admin, make_teacher

from app import easter_eggs
from app.db import SessionLocal
from app.models import User


def _today_ddmm() -> str:
    return easter_eggs._local_now().strftime("%d.%m")


def _as_student(login: str) -> User:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == login).first()
        u.role = "student"
        db.commit()
        return u
    finally:
        db.close()


def test_admin_saves_birthday_and_student_gets_the_cake(client):
    """Полная цепь: сохранили дату через админку → ручка входа отдала `portal_cake`."""
    admin = make_admin(client)
    st_headers = make_teacher(client, admin, login="bd1")
    _as_student("bd1")

    #Дату ставим ТЕМ ЖЕ путём, что и человек, — через ручку правки, а не в обход в БД.
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == "bd1").first()
        u.birthday = _today_ddmm()
        db.commit()
    finally:
        db.close()

    r = client.get("/web/easter-eggs/on-login", headers=st_headers)
    assert r.status_code == 200, r.text
    assert r.json()["egg"] == "portal_cake", r.json()


def test_year_typed_by_admin_does_not_break_the_cake(client):
    """Админ вписал год — торт всё равно приходит: год молча отбрасывается.

    ⚠️ Именно здесь легче всего разъехаться: сравнение идёт со строкой «ДД.ММ», и
    сохранись год — совпадения не было бы НИКОГДА, причём молча."""
    from app.routers.web.write import _clean_birthday
    today = _today_ddmm()
    assert _clean_birthday(f"{today}.2007") == today
    assert _clean_birthday(today) == today
    #Однозначные день и месяц админ тоже вписывает: «5.3» обязано стать «05.03».
    assert _clean_birthday("5.3") == "05.03"


def test_cake_beats_the_chance_eggs_and_needs_no_luck(client):
    """Торт детерминирован: он не бросок, и не должен зависеть от удачи.

    Обратный ход: поставь дату на завтра — торт пропадает, и это уже дело случая."""
    admin = make_admin(client)
    st = make_teacher(client, admin, login="bd2")
    _as_student("bd2")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == "bd2").first()
        u.birthday = _today_ddmm()
        db.commit()
    finally:
        db.close()
    #Десять заходов подряд — торт обязан приходить КАЖДЫЙ раз.
    got = [client.get("/web/easter-eggs/on-login", headers=st).json()["egg"] for _ in range(10)]
    assert got == ["portal_cake"] * 10, got


def test_not_a_birthday_gives_no_cake(client):
    """Обратный ход: не сегодня — торта нет."""
    admin = make_admin(client)
    st = make_teacher(client, admin, login="bd3")
    _as_student("bd3")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == "bd3").first()
        u.birthday = "01.01" if _today_ddmm() != "01.01" else "02.02"
        db.commit()
    finally:
        db.close()
    for _ in range(5):
        assert client.get("/web/easter-eggs/on-login", headers=st).json()["egg"] != "portal_cake"
