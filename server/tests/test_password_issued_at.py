"""test_password_issued_at.py — дата последней выдачи пароля (users.password_set_at).

Зачем поле: САМ пароль администратору показать нельзя — в базе лежит необратимый хеш
(гибрид PBKDF2-SHA512 + Стрибог). Но вопрос «свежий у человека пароль или выдан
полгода назад» законный, и на него отвечает дата.

Главная проверка здесь — НЕ «поле заполняется» (это очевидно), а то, что оно
заполняется ВЕЗДЕ, где меняется пароль. Мест таких семь, и ровно на такой раскладке
«правило расписано по семи местам вместо одного» эта команда уже обожглась: в одном
из семи его забыли, тесты остались зелёными. Поэтому ниже есть структурный тест, что
прямых присваиваний `password_hash` в коде не осталось вовсе.
"""
import pathlib
import re

from conftest import make_admin, make_teacher


def _student(client, h, login="ivanov", password="studpass1"):
    return client.post("/web/admin/students", headers=h, json={
        "surname": "Иванов", "name": "Иван", "login": login, "group": "ИС-21",
        "password": password})


def test_new_student_gets_issue_date(client):
    h = make_admin(client)
    assert _student(client, h).status_code in (200, 201)
    row = next(s for s in client.get("/web/admin/students", headers=h).json()["students"]
               if s["login"] == "ivanov")
    assert row["password_set_at"], "у только что заведённого студента дата выдачи пуста"


def test_date_changes_only_when_password_actually_changes(client):
    """Правка БЕЗ пароля дату не двигает — иначе «выдан» означало бы «карточку открывали»."""
    h = make_admin(client)
    _student(client, h)
    first = next(s for s in client.get("/web/admin/students", headers=h).json()["students"]
                 if s["login"] == "ivanov")["password_set_at"]

    #Меняем только ФИО, пароль не трогаем (пустая строка = «не менять»).
    client.put("/web/admin/students/ivanov", headers=h,
               json={"surname": "Петров", "name": "Иван", "password": ""})
    same = next(s for s in client.get("/web/admin/students", headers=h).json()["students"]
                if s["login"] == "ivanov")["password_set_at"]
    assert same == first, "дата сдвинулась, хотя пароль не меняли"

    client.put("/web/admin/students/ivanov", headers=h,
               json={"surname": "Петров", "name": "Иван", "password": "newpass123"})
    moved = next(s for s in client.get("/web/admin/students", headers=h).json()["students"]
                 if s["login"] == "ivanov")["password_set_at"]
    assert moved > first, "пароль заменили, а дата выдачи осталась прежней"


def test_teacher_created_by_admin_gets_issue_date(client):
    h = make_admin(client)
    client.post("/web/admin/teachers", headers=h, json={
        "login": "teach1", "full_name": "Петров П.П.", "password": "teacherpass1"})
    row = next(t for t in client.get("/web/admin/teachers", headers=h).json()["teachers"]
               if t["login"] == "teach1")
    assert row["password_set_at"]


def test_user_arrived_by_sync_has_no_issue_date_and_that_is_correct(client):
    """Пользователь, приехавший синком с десктопа, приносит ГОТОВЫЙ хеш.

    Когда там выдавали пароль — сервер не знает и знать не может, поэтому дата пуста.
    Это не пробел, а единственный честный ответ: подставить сюда время синка значило бы
    показать администратору дату, к выдаче пароля отношения не имеющую."""
    h = make_admin(client)
    make_teacher(client, h, login="synced", password="teacherpass1")
    row = next(t for t in client.get("/web/admin/teachers", headers=h).json()["teachers"]
               if t["login"] == "synced")
    assert row["password_set_at"] == ""


def test_old_account_without_date_is_reported_as_empty_not_faked(client):
    """Учётке, заведённой ДО появления поля, дату задним числом не выдумываем.

    Пустая строка честно значит «неизвестно»; подставленная дата выглядела бы фактом
    и говорила бы администратору неправду о том, когда пароль в последний раз меняли."""
    from app.db import SessionLocal
    from app.models import User
    h = make_admin(client)
    _student(client, h)
    db = SessionLocal()
    row = db.query(User).filter(User.login == "ivanov").first()
    row.password_set_at = ""          #эмулируем строку из старой схемы
    db.commit()
    db.close()
    got = next(s for s in client.get("/web/admin/students", headers=h).json()["students"]
               if s["login"] == "ivanov")
    assert got["password_set_at"] == ""


def test_no_direct_password_hash_assignment_outside_the_single_helper():
    """Сторож на ту самую граблю: пароль меняется ТОЛЬКО через set_user_password.

    Прямое `row.password_hash = hash_password(...)` где угодно ещё означает пароль,
    выданный без даты, — и обнаружится это не тестом, а администратором, который
    смотрит на «неизвестно» у человека, которому вчера выдал пароль лично.
    ⚠️ Проверка обязана быть структурной: поведенческий тест ловит только те места,
    которые кто-то вспомнил покрыть, а забывают как раз незамеченные."""
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"\.password_hash\s*=\s*hash_password\(")
    offenders = []
    for path in root.rglob("*.py"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(root).as_posix())
    #models.py — сама функция-помощник, ей присваивать положено.
    offenders = [p for p in offenders if p != "models.py"]
    assert not offenders, (
        "пароль меняется в обход set_user_password (дата выдачи не проставится): "
        + ", ".join(offenders))
