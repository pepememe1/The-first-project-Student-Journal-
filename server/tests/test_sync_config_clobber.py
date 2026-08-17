"""Синк НЕ ВПРАВЕ откатывать серверные настройки и серверный пароль (17.08.2026).

Заведено по следам адверсариального захода, где оба дефекта были ВОСПРОИЗВЕДЕНЫ на живом
приложении, а не выведены из чтения кода. Механизм общий и стоит того, чтобы его помнили:
`POST /sync/push` решает «применять или нет» СРАВНЕНИЕМ СОДЕРЖИМОГО и на `updated_at` не
смотрит вовсе — у кого содержимое иное, тот и прав. А десктоп администратора досылал
`config` и синтетическую строку `admin:{логин}` в КАЖДЫЙ цикл, потому что локальных меток
у них нет и они синтезировались как «сейчас».

Следствия были ровно два, оба тихие:
  • правка настройки на САЙТЕ откатывалась устаревшей копией десктопа за полминуты. Этим
    объясняется «воскресший оверрайд термина», который чистили руками ДВАЖДЫ (3.6.1 и
    3.7.4) и оба раза не нашли, кто создаёт его заново — кнопку перевода курса из
    интерфейса к тому моменту уже убрали;
  • смена пароля администратора на сайте отменялась тем же путём, причём `password_set_at`
    оставался НОВЫМ: карточка показывала «пароль выдан только что», а пускал прежний.

⚠️ Тесты ниже парные: на каждый запрет есть ОБРАТНЫЙ, иначе «починка» вида «синк вообще
ничего не меняет» выглядела бы правильной и сломала бы законные сценарии.
"""
from conftest import make_admin


def test_desktop_push_cannot_touch_server_config(client):
    """Устаревшая копия настроек с десктопа НЕ должна затирать серверную."""
    from app.models import ConfigKV
    from app.db import SessionLocal

    headers = make_admin(client)

    #Сайт задаёт период (routers/web/terms.py пишет ОДНОЙ строкой key='config').
    with SessionLocal() as db:
        db.add(ConfigKV(key="config",
                        value={"current_year": "2025/2026", "current_semester": 2},
                        updated_at="2026-08-17T10:00:00+00:00", deleted=False))
        db.commit()

    #Десктоп админа досылает свою копию — так делали ВСЕ версии до 3.7.5 включительно,
    #и так они будут делать ещё месяцами (в поле стоят собранные .exe).
    r = client.post("/sync/push", json={"changes": {"config": [
        {"key": "config", "value": {"current_year": "2026/2027", "current_semester": 1},
         "updated_at": "2020-01-01T00:00:00+00:00", "deleted": False},
    ]}}, headers=headers)
    assert r.status_code == 200, r.text

    with SessionLocal() as db:
        assert db.get(ConfigKV, "config").value == {
            "current_year": "2025/2026", "current_semester": 2}, (
            "серверная настройка затёрта пушем десктопа — вернулся дефект, из-за которого "
            "оверрайд термина воскресал дважды")


def test_site_can_still_change_config(client):
    """ОБРАТНЫЙ ХОД: запрет касается только синка. Настройки по-прежнему меняются на
    сервере — иначе «починка» превратилась бы в заморозку конфигурации, и это выглядело
    бы правильным (тест выше остался бы зелёным)."""
    from app.models import ConfigKV
    from app.db import SessionLocal

    make_admin(client)
    with SessionLocal() as db:
        db.add(ConfigKV(key="config", value={"current_semester": 1},
                        updated_at="", deleted=False))
        db.commit()
    with SessionLocal() as db:
        row = db.get(ConfigKV, "config")
        row.value = {"current_semester": 2}
        db.commit()
    with SessionLocal() as db:
        assert db.get(ConfigKV, "config").value == {"current_semester": 2}


def test_desktop_push_cannot_replace_an_existing_password(client):
    """Пароль, выданный на сайте, не откатывается пушем десктопа."""
    from app.models import User, set_user_password
    from app.db import SessionLocal
    from app.security import hash_password, verify_password

    headers = make_admin(client, login="admin", password="adminpass1")

    with SessionLocal() as db:
        u = db.get(User, "admin:admin")
        set_user_password(u, "brandNewPass9!")
        db.commit()

    #Десктоп шлёт ПРЕЖНИЙ хеш из своего локального config.
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "admin:admin", "role": "admin", "login": "admin",
        "password_hash": hash_password("adminpass1"),
        "full_name": "Администратор", "surname": "", "name": "", "group_name": "",
        "subjects": [], "group_assignments": {},
        "updated_at": "2020-01-01T00:00:00+00:00", "deleted": False,
    }]}}, headers=headers)
    assert r.status_code == 200, r.text

    with SessionLocal() as db:
        u = db.get(User, "admin:admin")
        assert verify_password("brandNewPass9!", u.password_hash), (
            "синк подменил существующий хеш — смена пароля на сайте отменена")

    #Живая проверка тем же путём, каким ходит человек.
    assert client.post("/auth/login",
                       json={"login": "admin", "password": "brandNewPass9!"}).status_code == 200
    assert client.post("/auth/login",
                       json={"login": "admin", "password": "adminpass1"}).status_code == 401


def test_push_still_updates_everything_except_the_secret(client):
    """ОБРАТНЫЙ ХОД: запрет точечный. Остальные поля той же строки синк меняет как прежде —
    иначе «починка» вида «строку с паролем не применять вовсе» прошла бы тест выше и тихо
    сломала бы обычную синхронизацию пользователей."""
    from app.models import User
    from app.db import SessionLocal
    from app.security import hash_password, verify_password

    headers = make_admin(client)
    client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:s1", "role": "student", "login": "s1",
        "password_hash": hash_password("studpass1"),
        "surname": "Иванов", "name": "Иван", "group_name": "К74/1",
    }]}}, headers=headers)

    #Студента перевели в другую группу и переименовали — это законная правка справочника.
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:s1", "role": "student", "login": "s1",
        "password_hash": hash_password("ПОПЫТКА-ПОДМЕНЫ"),
        "surname": "Петрова", "name": "Иван", "group_name": "К75/1",
    }]}}, headers=headers)
    assert r.status_code == 200, r.text

    with SessionLocal() as db:
        u = db.get(User, "stud:s1")
        assert u.surname == "Петрова" and u.group_name == "К75/1", (
            "обычные поля перестали синхронизироваться")
        assert verify_password("studpass1", u.password_hash), "а секрет обязан остаться прежним"
