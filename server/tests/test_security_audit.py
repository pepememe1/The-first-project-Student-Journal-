"""
test_security_audit.py — регрессии на находки аудита безопасности 3.6.

Каждый тест здесь закрывает КОНКРЕТНУЮ дыру, найденную при разборе синка, токенов и
конфигурации. Файл отдельный намеренно: эти проверки не про поведение фич, а про то,
что нельзя сломать молча, и держать их вперемешку с функциональными тестами значит
однажды «поправить» такой тест заодно с рефакторингом.
"""
import pytest

from conftest import make_admin, make_teacher, assign_teacher

_LESSON = {"id": "L1", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
           "number": 1, "topic": "т", "date": "01.09.2025"}


def _push(client, headers, **changes):
    return client.post("/sync/push", json={"changes": changes}, headers=headers)


# ── 1. Боевой сервер не имеет права работать с дефолтным ключом подписи ─────────────
def test_production_refuses_default_jwt_secret():
    """🔒 Сервер, подписывающий токены ключом из исходников, — это открытая дверь.

    Ключ известен всем, у кого есть репозиторий (команда, покупатель, любой, кому
    отдали архив), и подделать себе токен с ролью admin — задача на три строки. Поэтому
    на бою это ОТКАЗ ЗАПУСКАТЬСЯ, а не предупреждение: упавший сервер чинят за минуты,
    а тихо работающий с дев-ключом не чинят никогда — о нём просто не знают."""
    from app import config

    with pytest.raises(RuntimeError, match="GRADEBOOK_JWT_SECRET"):
        _run_assert(config, is_prod=True, secret=config.DEV_JWT_SECRET)


def test_development_allows_default_jwt_secret():
    """В разработке дефолт удобен и безопасен: ни ПДн, ни внешнего доступа там нет.
    Падать на каждом `uvicorn --reload` мы не собираемся."""
    from app import config

    assert _run_assert(config, is_prod=False, secret=config.DEV_JWT_SECRET) == []


def test_production_warns_about_unencrypted_db_and_short_secret():
    """Остальное — ПРЕДУПРЕЖДЕНИЯ, а не отказ.

    Без шифрования базы продукт нарушает 152-ФЗ, но работает; останавливать из-за этого
    колледж на середине учебного дня — хуже, чем громко пожаловаться в лог и журнал
    событий администратора."""
    from app import config

    warns = _run_assert(config, is_prod=True, secret="x" * 8, db_key="")
    assert any("GRADEBOOK_DB_KEY" in w for w in warns)
    assert any("32" in w for w in warns)


def _run_assert(config, is_prod: bool, secret: str, db_key: str = "") -> list:
    """Прогнать проверку с подменёнными значениями (модуль читает их при импорте)."""
    old = (config.IS_PROD, config.JWT_SECRET, config.DB_KEY)
    config.IS_PROD, config.JWT_SECRET, config.DB_KEY = is_prod, secret, db_key
    try:
        return config.assert_production_secrets()
    finally:
        config.IS_PROD, config.JWT_SECRET, config.DB_KEY = old


# ── 2. /sync/pull не отдаёт ничего роли, которой там не место ───────────────────────
def test_sync_pull_gives_nothing_to_parent(client):
    """🔒 Родитель через /sync/pull не получает НИЧЕГО.

    Раньше он попадал в общий студенческий скоуп, а тот отбирает оценки по совпадению
    ФАМИЛИИ И ИМЕНИ владельца токена. У родителя они свои — и родитель-однофамилец
    (в семье это буквально норма, да и просто совпадение ФИО с чужим студентом)
    выкачал бы чужие оценки целиком. Его кабинет — веб (§14), офлайн-синк ему не нужен
    по построению."""
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "ИС-21", "subjects": ["Математика"]},
                headers=admin)
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванов", "name": "Пётр", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    _push(client, admin, lessons=[_LESSON])
    _push(client, admin, grades=[{"id": "g1", "student_f": "Иванов", "student_n": "Пётр",
                                  "lesson_id": "L1", "grade": "2"}])

    #Родитель — ПОЛНЫЙ ТЁЗКА студента. Это и есть боевой сценарий утечки.
    client.post("/web/admin/parents", json={
        "login": "parent1", "surname": "Иванов", "name": "Пётр",
        "password": "parentpass1"}, headers=admin)
    tok = client.post("/auth/login", json={"login": "parent1", "password": "parentpass1"})
    parent = {"Authorization": f"Bearer {tok.json()['access_token']}"}

    changes = client.get("/sync/pull", headers=parent).json()["changes"]
    assert all(not rows for rows in changes.values()), \
        f"родителю уехали данные: {[k for k, v in changes.items() if v]}"


# ── 3. Преподаватель не пишет синком в чужую группу ─────────────────────────────────
def test_teacher_push_cannot_reach_unassigned_group(client):
    """🔒 Преподаватель с назначением в ОДНОЙ группе не пишет во ВТОРУЮ.

    До 3.6 синк проверял только ПРЕДМЕТ: препод «Математики» мог отправить оценки в
    любую группу колледжа, где эта математика вообще числится. На сайте тот же сценарий
    закрыт с 3.3.1 (`_teacher_check_assignment`) — синк просто отстал, и получилась
    дверь пошире парадной."""
    admin = make_admin(client)
    for g in ("ИС-21", "ИС-22"):
        client.post("/web/admin/groups", json={"name": g, "subjects": ["Математика"]},
                    headers=admin)
    th = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")

    #Своя группа — проходит.
    r = _push(client, th, lessons=[dict(_LESSON, id="OWN", group_name="ИС-21")])
    assert r.json()["applied"].get("lessons") == 1

    #Чужая группа с ТЕМ ЖЕ предметом — отвергается.
    r = _push(client, th, lessons=[dict(_LESSON, id="FOREIGN", group_name="ИС-22")])
    assert r.json()["applied"].get("lessons", 0) == 0
    assert r.json().get("rejected", {}).get("lessons") == 1


def test_teacher_without_assignments_keeps_working(client):
    """⚠️ Мост: у преподавателя БЕЗ назначений работает прежнее правило по предмету.

    Строгая проверка без этого моста молча отвергала бы офлайн-правки в колледже, где
    админ ещё не расставил нагрузку, — а потерянная оценка хуже лишнего разрешения.
    Тот же компромисс уже принят в webdata.teacher_assignments (allow_fallback)."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    r = _push(client, th, lessons=[_LESSON])
    assert r.json()["applied"].get("lessons") == 1
    #Но чужой ПРЕДМЕТ по-прежнему нельзя — мост не отменяет проверку, а смягчает её.
    r = _push(client, th, lessons=[dict(_LESSON, id="PH", subject="Физика")])
    assert r.json().get("rejected", {}).get("lessons") == 1


# ── 4. Инварианты, которые уже держат прод и не должны разъехаться ─────────────────
def test_pull_never_leaks_other_peoples_password_hashes(client):
    """Хеш пароля уезжает на чужой компьютер ТОЛЬКО свой собственный."""
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "ИС-21", "subjects": ["Математика"]},
                headers=admin)
    client.post("/web/admin/students", json={
        "login": "s1", "surname": "Петров", "name": "Иван", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    th = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")

    users = client.get("/sync/pull", headers=th).json()["changes"]["users"]
    for u in users:
        if u["login"] != "teacher1":
            assert not u.get("password_hash"), f"уехал чужой хеш: {u['login']}"


def test_pull_never_leaks_ai_secrets_to_non_admin(client):
    """Секретные ключи config (токен GigaChat и подобные) не покидают сервер к не-админу."""
    admin = make_admin(client)
    #Настройки кладём ПРЯМО в БД, как это делает сайт: синком `config` не принимается
    #с 17.08.2026 (см. PUSH_SCOPE) — проверяем здесь РАЗДАЧУ, а не приём.
    from app.models import ConfigKV
    from app.db import SessionLocal
    with SessionLocal() as db:
        db.add(ConfigKV(key="gigachat_credentials", value="СЕКРЕТ", updated_at="", deleted=False))
        db.add(ConfigKV(key="ai_provider", value="gigachat", updated_at="", deleted=False))
        db.commit()
    th = make_teacher(client, admin)
    keys = {c["key"] for c in client.get("/sync/pull", headers=th).json()["changes"]["config"]}
    assert "gigachat_credentials" not in keys
    assert "ai_provider" in keys, "несекретные настройки обязаны доезжать как раньше"


def test_sync_is_closed_for_web_clients(client):
    """Браузеру полный дамп базы не отдаём ни при каких правах — у него /web/*."""
    admin = dict(make_admin(client), **{"X-Client": "web"})
    assert client.get("/sync/pull", headers=admin).status_code == 403
    assert client.post("/sync/push", json={"changes": {}}, headers=admin).status_code == 403


def test_student_cannot_push_anything(client):
    """Студент не пишет в общий синк вовсе (PUSH_SCOPE пуст) — даже свои оценки."""
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "ИС-21", "subjects": ["Математика"]},
                headers=admin)
    client.post("/web/admin/students", json={
        "login": "s1", "surname": "Петров", "name": "Иван", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    tok = client.post("/auth/login", json={"login": "s1", "password": "studpass1"})
    stud = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    _push(client, stud, lessons=[_LESSON])
    #Занятие не должно появиться ни у кого.
    lessons = client.get("/sync/pull", headers=make_admin_again(client)).json()["changes"]["lessons"]
    assert all(l["id"] != "L1" for l in lessons)


def make_admin_again(client):
    """Повторный вход тем же администратором (bootstrap срабатывает только один раз)."""
    r = client.post("/auth/login", json={"login": "admin", "password": "adminpass1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
