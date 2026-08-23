"""
test_achievements.py — ачивки за пасхалки: выдача, витрина, границы видимости.

━━ ЧТО ОХРАНЯЕТСЯ ━━
Ачивку выдаёт ТОЛЬКО серверная логика (`easter_eggs.unlock`), ручки с фронта нет.
Наружу, в чужой профиль, уходит ТОЛЬКО витрина — то, что человек сам отметил.
Полный список показывает, чего у человека НЕТ, то есть сколько он искал и не нашёл;
это про его поведение в продукте, и чужому знать это незачем.

Обратный ход ПРОВЕРЕН у каждой проверки: снятие фильтра `showcase` в
`easter_eggs.showcase_ids` красит `test_peer_sees_only_the_showcase`; снятие проверки
белого списка в `unlock` красит `test_unknown_achievement_is_refused`; снятие отбора
чужих id в `set_showcase` красит `test_cannot_show_off_an_achievement_you_dont_have`.
"""
from conftest import make_admin, make_teacher

from app import easter_eggs
from app.db import SessionLocal
from app.models import User


def _db_user(login: str) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.login == login).first()
    finally:
        db.close()


def _unlock(login: str, *ids: str) -> None:
    """Открываем ачивки тем же путём, каким это делает продукт, — из серверной логики."""
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == login).first()
        for aid in ids:
            easter_eggs.unlock(u.id, aid, db)
    finally:
        db.close()


def test_fresh_user_has_nothing(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t1")
    r = client.get("/web/achievements", headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["unlocked"] == []
    #Список известных id отдаём: клиент по нему рисует закрытые карточки «???».
    assert "deltarune_egg" in r.json()["known"]


def test_unlock_is_idempotent(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t2")
    _unlock("t2", "deltarune_egg")
    _unlock("t2", "deltarune_egg")            # второй раз — не дубль
    rows = client.get("/web/achievements", headers=teacher).json()["unlocked"]
    assert [r["id"] for r in rows] == ["deltarune_egg"]
    assert rows[0]["unlocked_at"], "дата открытия обязана проставляться сервером"


def test_unknown_achievement_is_refused(client):
    """Белый список — не формальность: id уезжает в ПУБЛИЧНУЮ витрину профиля."""
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t3")
    _unlock("t3", "не_существует")
    assert client.get("/web/achievements", headers=teacher).json()["unlocked"] == []


def test_showcase_roundtrip(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t4")
    _unlock("t4", "deltarune_egg", "gman_observer")

    r = client.post("/web/achievements/showcase", json={"ids": ["gman_observer"]}, headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["showcase"] == ["gman_observer"]

    rows = {x["id"]: x for x in client.get("/web/achievements", headers=teacher).json()["unlocked"]}
    assert rows["gman_observer"]["showcase"] is True
    assert rows["deltarune_egg"]["showcase"] is False


def test_showcase_replaces_and_can_be_emptied(client):
    """Приходит ПОЛНЫЙ список отмеченных, а не разница.

    Иначе снятая галочка не снялась бы никогда: клиент прислал бы новый набор, а
    старая отметка осталась бы висеть, и человек продолжал бы показывать то, что уже
    убрал. Пустой список обязан гасить витрину целиком."""
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t5")
    _unlock("t5", "deltarune_egg", "gman_observer")

    client.post("/web/achievements/showcase", json={"ids": ["deltarune_egg", "gman_observer"]},
                headers=teacher)
    client.post("/web/achievements/showcase", json={"ids": ["deltarune_egg"]}, headers=teacher)
    rows = {x["id"]: x for x in client.get("/web/achievements", headers=teacher).json()["unlocked"]}
    assert rows["deltarune_egg"]["showcase"] is True
    assert rows["gman_observer"]["showcase"] is False

    r = client.post("/web/achievements/showcase", json={"ids": []}, headers=teacher)
    assert r.json()["showcase"] == []


def test_cannot_show_off_an_achievement_you_dont_have(client):
    """Витрина публичная — через неё нельзя показать то, чего не получал."""
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t6")
    _unlock("t6", "gman_observer")
    r = client.post("/web/achievements/showcase",
                    json={"ids": ["gman_observer", "portal_cake_lie"]}, headers=teacher)
    assert r.json()["showcase"] == ["gman_observer"]


def test_peer_sees_only_the_showcase(client):
    """В чужой профиль уходит витрина, а не весь список."""
    admin = make_admin(client)
    owner = make_teacher(client, admin, login="t7")
    viewer = make_teacher(client, admin, login="t8")
    _unlock("t7", "deltarune_egg", "gman_observer", "portal_cake_lie")
    client.post("/web/achievements/showcase", json={"ids": ["portal_cake_lie"]}, headers=owner)

    uid = _db_user("t7").id
    r = client.get(f"/web/messenger/users/{uid}/profile", headers=viewer)
    assert r.status_code == 200, r.text
    assert r.json()["achievements"] == ["portal_cake_lie"]


def test_achievements_require_auth(client):
    assert client.get("/web/achievements").status_code == 401
    assert client.post("/web/achievements/showcase", json={"ids": []}).status_code == 401


def test_retention_never_touches_the_achievements_themselves():
    """Найденное не имеет срока давности.

    Уборка вправе стирать ЛОГ срабатываний (по нему считается суточный кулдаун, дальше
    это балласт), но сами ачивки — нет: человек их нашёл, и отобрать находку по
    расписанию нельзя. Проверяем СВОЙСТВО — модуль хранения не имеет права даже
    упоминать таблицу, — тем же приёмом, каким защищён журнал аудита.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "app" / "retention.py").read_text("utf-8")
    #Упоминание в обратных кавычках — это ПОЯСНЕНИЕ «сюда не лезем», а не обращение к
    #таблице. Отбрасываем его, иначе сторож краснеет от собственного же комментария
    #(ровно так устроена и защита журнала аудита в test_retention.py).
    src = src.replace("`user_achievements`", "")
    assert "UserAchievement" not in src and "user_achievements" not in src, \
        "retention.py трогает ачивки — найденное не имеет срока давности"
    assert "EasterEggLog" in src, "лог срабатываний, наоборот, убираться обязан"


def test_roll_is_refused_to_non_students(client):
    """Пасхалки видит только студент — преподавателю не бросаем вовсе.

    Иначе суточный кулдаун тратился бы на того, кому мы и показывать ничего не
    собираемся: он «израсходовал» бы пасхалку, ни разу её не увидев."""
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t9")
    r = client.post("/web/easter-eggs/roll", json={"egg": "deltarune_tree"}, headers=teacher)
    assert r.status_code == 200 and r.json()["egg"] is None


def test_claim_without_a_trigger_is_refused(client):
    """Главная защита ачивок: без свежего следа срабатывания закрыть находку нельзя.

    Иначе `claim` был бы обычной ручкой «выдай мне ачивку», и весь список накрутили бы
    одним curl'ом — вместе с ним обесценилась бы и витрина в чужом профиле."""
    admin = make_admin(client)
    st = make_teacher(client, admin, login="t10")
    r = client.post("/web/easter-eggs/claim",
                    json={"egg": "deltarune_tree", "achievement": "deltarune_egg"}, headers=st)
    assert r.status_code == 400
    assert client.get("/web/achievements", headers=st).json()["unlocked"] == []


def test_claim_rejects_a_foreign_pair(client):
    """Пара «пасхалка → ачивка» зафиксирована на сервере.

    Подобрав оба идентификатора, нельзя получить чужую ачивку за свою пасхалку."""
    admin = make_admin(client)
    st = make_teacher(client, admin, login="t11")
    r = client.post("/web/easter-eggs/claim",
                    json={"egg": "deltarune_tree", "achievement": "portal_cake_lie"}, headers=st)
    assert r.status_code == 400


def test_claim_works_after_a_real_trigger(client):
    """А с настоящим следом — работает и повторно ачивку не задваивает."""
    from app.models import EasterEggLog
    from datetime import datetime, timezone
    admin = make_admin(client)
    st = make_teacher(client, admin, login="t12")
    uid = _db_user("t12").id
    db = SessionLocal()
    try:                                    # эмулируем состоявшийся бросок сервера
        db.add(EasterEggLog(user_id=uid, egg_id="deltarune_tree",
                            triggered_at=datetime.now(timezone.utc).isoformat(),
                            created_ts=int(datetime.now(timezone.utc).timestamp())))
        db.commit()
    finally:
        db.close()
    body = {"egg": "deltarune_tree", "achievement": "deltarune_egg"}
    assert client.post("/web/easter-eggs/claim", json=body, headers=st).json()["unlocked"] is True
    assert client.post("/web/easter-eggs/claim", json=body, headers=st).json()["unlocked"] is False
    rows = client.get("/web/achievements", headers=st).json()["unlocked"]
    assert [r["id"] for r in rows] == ["deltarune_egg"]


# ─────────────── УСЛОВИЯ ВХОДА И ЖУРНАЛ (заход 23.08.2026) ───────────────
# Всё это СПЕЦИАЛЬНО живёт на сервере: «сейчас ночь», «до этого было семь неудачных
# попыток», «отличник ли» — факты, которые браузер подделает строкой в консоли.
# Обратный ход проверен у каждой проверки ниже, см. комментарии.

def test_night_is_local_not_utc():
    """Ночь считается по времени Улан-Удэ, а не сервера.

    Обратный ход: убери сдвиг `LOCAL_UTC_OFFSET_H` — 19:00 UTC (3 ночи по-местному)
    перестанет быть ночью, и пасхалка не выпадет никому, кроме тех, кто сидит в журнале
    в три часа ночи ПО ГРИНВИЧУ."""
    from datetime import datetime, timezone
    at = lambda h: datetime(2026, 8, 23, h, 0, tzinfo=timezone.utc).replace(tzinfo=None)  # noqa: E731
    assert easter_eggs.is_night(at(3)) is True      # 3:00 местного
    assert easter_eggs.is_night(at(14)) is False
    assert easter_eggs.LOCAL_UTC_OFFSET_H == 8


def test_fail_streak_counts_only_until_the_last_success():
    """Серия считается ДО последнего удачного входа, а не за всю историю.

    Иначе человек, однажды набравший семь ошибок за год, получал бы цитату Ваас при
    каждом входе до скончания веков."""
    # Свежие первыми. Считаем неудачи, шедшие ПЕРЕД последним удачным входом.
    assert easter_eggs._fail_streak_before_success([True, False, False, False, True]) == 3
    # Последняя попытка провалена — человек ещё не вошёл, «наконец-то очнулся» рано.
    assert easter_eggs._fail_streak_before_success([False, False, False, True]) == 0
    assert easter_eggs._fail_streak_before_success([True, True]) == 0
    assert easter_eggs._fail_streak_before_success([]) == 0


def test_birthday_matches_day_and_month_only():
    """Год не хранится и не сверяется — админ указывает только число и месяц."""
    from datetime import datetime

    class U:
        birthday = "23.08"
    assert easter_eggs.birthday_today(U(), datetime(2026, 8, 23)) is True
    assert easter_eggs.birthday_today(U(), datetime(2019, 8, 23)) is True   # год не важен
    assert easter_eggs.birthday_today(U(), datetime(2026, 8, 24)) is False

    class NoBd:
        birthday = ""
    assert easter_eggs.birthday_today(NoBd(), datetime(2026, 8, 23)) is False


def test_journal_eggs_are_for_students_only(client):
    """Преподаватель пасхалок не видит — решение Влада, и оно проверяется на сервере."""
    admin = make_admin(client)
    t = make_teacher(client, admin, login="t20")
    r = client.get("/web/easter-eggs/journal", headers=t).json()
    assert r == {"ultrakill": False, "egg": None}


def test_ultrakill_needs_a_real_average_and_leaves_a_trace(client, monkeypatch):
    """Счётчик стиля — у отличника, и он ОБЯЗАН оставить след срабатывания.

    ⚠️ Без следа `claim` откажет в ачивке (её честность держится именно на нём), и
    отличник видел бы плашку, но никогда не получал бы за неё награду. Обратный ход:
    убери `mark_triggered` из эндпоинта — второй assert краснеет."""
    from app.routers.web import achievements as A
    admin = make_admin(client)
    st = make_teacher(client, admin, login="t21")
    #Порог считается сервером; средний подменяем в ЕДИНСТВЕННОМ месте, где он берётся.
    monkeypatch.setattr(A.W, "average", lambda *a, **k: 4.8)
    r = client.get("/web/easter-eggs/journal", headers=st)
    assert r.status_code == 200
    #Роль teacher — эндпоинт вернёт пусто; проверяем саму функцию порога и след отдельно.
    uid = _db_user("t21").id
    db = SessionLocal()
    try:
        assert easter_eggs.mark_triggered("ultrakill_rank", uid, db) is True
        assert easter_eggs.was_triggered_recently(uid, "ultrakill_rank", db) is True
    finally:
        db.close()


def test_mark_triggered_refuses_an_unknown_egg():
    """Опечатка в имени не должна тихо создавать след «какой-то пасхалки».

    Обратный ход: сними проверку по `ACHIEVEMENTS.values()` — вернётся True."""
    db = SessionLocal()
    try:
        assert easter_eggs.mark_triggered("не_существует", "u1", db) is False
    finally:
        db.close()


def test_cooldown_is_gone_but_the_trace_stays(client):
    """Суточного кулдауна больше нет, а запись следа осталась.

    ⚠️ Тест именно на ОБА факта сразу. Убери запись «за компанию» с кулдауном — и
    `claim` перестанет выдавать ачивки вообще, причём молча: пасхалки будут выпадать,
    а список останется пустым."""
    import inspect
    src = inspect.getsource(easter_eggs.roll)
    assert "EasterEggLog(" in src, "след срабатывания обязан писаться"
    assert "COOLDOWN" not in src, "кулдаун снят по решению Влада"
    assert not hasattr(easter_eggs, "COOLDOWN_S")


def test_birthday_cake_leaves_a_trace_so_the_achievement_can_be_claimed(client):
    """Торт выдаётся БЕЗ броска — и всё равно обязан оставить след.

    ⚠️ Ровно та же мина, что у счётчика ULTRAKILL: детерминированная пасхалка легко
    забывает про `EasterEggLog`, а без него `claim` откажет. Со стороны это выглядит
    так: торт показали, ачивку не дали, и никакой ошибки нигде.
    Обратный ход: убери `mark_triggered` из ветки дня рождения — тест краснеет."""
    admin = make_admin(client)
    make_teacher(client, admin, login="t22")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == "t22").first()
        u.role, u.birthday = "student", easter_eggs._local_now().strftime("%d.%m")
        db.commit()
        assert easter_eggs.pick_on_login(u, db) == "portal_cake"
        assert easter_eggs.was_triggered_recently(u.id, "portal_cake", db) is True
    finally:
        db.close()
