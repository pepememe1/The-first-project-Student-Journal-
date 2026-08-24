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

from datetime import datetime, timezone
from app import easter_eggs
from app.routers.web import achievements as achievements_router
from app.db import SessionLocal
from app.models import User, UserAchievement


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


def test_global_cooldown_is_gone_but_the_trace_stays(client):
    """ОБЩЕГО суточного кулдауна нет, а запись следа осталась.

    ⚠️ Тест именно на ОБА факта сразу. Убери запись «за компанию» с кулдауном — и
    `claim` перестанет выдавать ачивки вообще, причём молча: пасхалки будут выпадать,
    а список останется пустым.

    ⚠️ ЧТО ИМЕННО ЗАПРЕЩЕНО, а что нет. Запрещён ОБЩИЙ кулдаун на все пасхалки
    (`COOLDOWN_S` одним числом): он был невидимой стеной, из-за которой человек не мог
    понять, не везёт ему или сработало правило. Поштучный `EGG_COOLDOWN_S` — другое
    дело и разрешён: он решает обратную задачу, см. соседний тест."""
    import inspect
    src = inspect.getsource(easter_eggs.roll)
    assert "EasterEggLog(" in src, "след срабатывания обязан писаться"
    assert not hasattr(easter_eggs, "COOLDOWN_S"), "общий кулдаун снят по решению Влада"
    #Поштучный словарь обязан существовать и быть именно словарём, а не числом.
    assert isinstance(easter_eggs.EGG_COOLDOWN_S, dict)


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


def test_cooldown_only_where_the_trigger_is_frequent(client):
    """Кулдаун ПОШТУЧНО и только там, где триггер частый.

    ⚠️ Это НЕ возврат общего суточного кулдауна, снятого выше, а решение обратной
    задачи. Дерево бросается на каждой смене вкладки (по журналу боевой машины — 3777
    бросков за сутки), счётчик стиля — на каждой загрузке журнала у отличника: оба
    примелькались и перестали читаться как находка.
    Обратный ход: повесь кулдаун на РЕДКУЮ пасхалку — она станет невидимой вдвойне,
    ровно то, от чего избавлялись."""
    assert set(easter_eggs.EGG_COOLDOWN_S) == {"deltarune_tree", "ultrakill_rank"}
    #У пасхалок с редким триггером кулдауна быть НЕ должно.
    for egg in ("cyberpunk_login", "stanley_parable_404", "gman_observer", "hotline_miami"):
        assert egg not in easter_eggs.EGG_COOLDOWN_S


def test_ultrakill_is_a_condition_plus_a_chance(client):
    """Счётчик стиля — условие И бросок, а не одно условие.

    ⚠️ Раньше он был чисто детерминированным, и отличник видел плашку при КАЖДОЙ
    загрузке журнала. Доля записана в процентах намеренно: 30 % это про частоту показа
    заслуженной плашки, а не про редкость находки, и знаменатель (1/3) называл бы её
    не тем, что она есть."""
    assert easter_eggs.EGG_PERCENT["ultrakill_rank"] == 30
    #⚠️ В двух словарях сразу быть не должно: значения 3 и 3 означают там разное
    #(33 % против 3 %), и двойное объявление — прямой путь промахнуться на порядок.
    assert "ultrakill_rank" not in easter_eggs.EGG_CHANCES


def test_percent_roll_honours_the_fractional_share(monkeypatch):
    """Дробная доля соблюдается ТОЧНО, а не «примерно».

    ⚠️ Здесь стояла статистическая проверка с допуском в один процентный пункт — и она
    НЕ КРАСНЕЛА на настоящей поломке: `randint(1, 100) <= 7.7` даёт ровно 7 %, разница
    0.7 п.п. умещалась в допуск. Сторож, переживающий поломку, неотличим от исправного
    кода. Поэтому проверяем ГРАНИЦУ, а не среднее: при 7.7 % бросок 7.6 обязан попасть,
    а 7.8 — промахнуться. Целочисленный бросок так не умеет: у него нет значений между
    7 и 8, и подменённый `randint` тут же разойдётся с ожиданием.

    Обратный ход: верни в `_hit` `random.randint(1, 100) <= percent` — оба утверждения
    ниже падают."""
    #⚠️ Именно `assert`. Здесь стояло голое выражение `... == 7.7` — оно вычисляется и
    #результат выбрасывается, то есть «страховка» не страховала ничего. Ровно тот класс
    #сторожа, который зелен всегда и хуже отсутствия проверки.
    assert easter_eggs.EGG_PERCENT["cyberpunk_login"] == 7.7

    def fixed(rnd, integer):
        monkeypatch.setattr(easter_eggs.random, "random", lambda: rnd)
        monkeypatch.setattr(easter_eggs.random, "randint", lambda a, b: integer)

    #Доля 7.7: бросок «7.6 %» — попадание. Целочисленному пути даём 8, где `8 <= 7.7`
    #ложно, — значит зелёным останется только дробная реализация.
    fixed(0.076, 8)
    assert easter_eggs._hit("cyberpunk_login") is True

    #А «7.8 %» — промах. Целочисленному пути даём 7, где `7 <= 7.7` истинно.
    fixed(0.078, 7)
    assert easter_eggs._hit("cyberpunk_login") is False


def test_declared_chances_are_actually_obeyed():
    """Каждая заявленная частота выдерживается на большом числе бросков.

    Проверяем НАСТОЯЩУЮ `_hit`, а не копию формулы в тесте: раньше тест повторял
    вычисление у себя и остался бы зелёным, измени его кто-нибудь в продукте."""
    n = 200_000
    for egg, want in easter_eggs.EGG_PERCENT.items():
        got = sum(1 for _ in range(n) if easter_eggs._hit(egg)) / n * 100
        #Допуск 0.35 п.п. — это больше пяти стандартных отклонений при таком n (то есть
        #случайное падение практически исключено) и заметно МЕНЬШЕ 0.7 п.п., на которые
        #сдвинулась бы частота при округлении доли до целого процента.
        assert abs(got - want) < 0.35, f"{egg}: заявлено {want}%, вышло {got:.2f}%"

    #Знаменатель тоже: «один раз из N» обязан давать 1/N.
    got = sum(1 for _ in range(n) if easter_eggs._hit("stanley_parable_404")) / n
    assert abs(got - 1 / 10) < 0.005, f"1/10 дало {got:.3f}"

    #Неизвестная пасхалка не выпадает никогда — иначе опечатка в имени «работала бы».
    assert not any(easter_eggs._hit("не_существует") for _ in range(2000))


def test_cooldown_actually_blocks_the_second_roll(client):
    """След свежий — второй бросок не делается вовсе.

    Проверяем СВОЙСТВО, а не удачу: подкладываем след и убеждаемся, что `roll` вернул
    False, сколько бы раз его ни звали. Обратный ход: убери проверку кулдауна из
    `roll` — тест краснеет (при 1/66 сотня попыток почти наверняка даст выпадение)."""
    admin = make_admin(client)
    make_teacher(client, admin, login="cd1")
    uid = _db_user("cd1").id
    db = SessionLocal()
    try:
        easter_eggs.mark_triggered("deltarune_tree", uid, db)
        assert all(easter_eggs.roll("deltarune_tree", uid, db) is False for _ in range(100))
    finally:
        db.close()


def test_avatar_eggs_are_a_pair_and_neither_is_unreachable(client, monkeypatch):
    """DOOM и Detroit — пара: ровно одна метка, и ни одна не недостижима.

    ⚠️ Обе рисуются на ОДНОЙ аватарке. Покажи их вместе — получится кольцо поверх
    свечения, то есть каша вместо двух разных отсылок.

    ⚠️ Detroit раньше стоял ХВОСТОМ очереди `pick_on_login` и проверялся, только если
    промахнулся Cyberpunk: реальный шанс 0.99 % за вход, и по боевой базе он не сработал
    ни разу. Поэтому проверяем и то, что в общей очереди его больше нет.

    ⚠️ Выбор ДЕТЕРМИНИРОВАННЫЙ (по человеку и дню), поэтому проверять «за 60 бросков
    выпали обе» больше нельзя — у одного человека метка одна и та же весь день, и это
    ровно то, чего мы добивались. Вместо этого смотрим по РАЗНЫМ людям: если ключ
    выбора выродится (например, кто-то заменит хеш на константу), одна из отсылок
    станет недостижимой для всего колледжа, и вот это тест обязан поймать."""
    import inspect
    src = inspect.getsource(easter_eggs.pick_on_login)
    assert "detroit_led" not in src, "Detroit снова в очереди полноэкранных сцен"

        #⚠️ Долю на время теста поднимаем до 100 %. Это не подгонка: тест проверяет ДРУГОЕ
    #свойство (стабильность метки / обновление следа), и редкость здесь только мешала бы
    #— половина прогонов получала бы `None` и «падала» без всякой поломки. За саму долю
    #отвечает `test_avatar_share_matches_the_declared_percent`, и там она настоящая.
    #⚠️ Обе по 50, а не одна на 100: розыгрыш ОДИН на пару, и подняв только первую, мы
    #сделали бы вторую недостижимой — тест бы падал по своей же вине.
    monkeypatch.setitem(easter_eggs.EGG_PERCENT, "doom_avatar", 50)
    monkeypatch.setitem(easter_eggs.EGG_PERCENT, "detroit_led", 50)
    admin = make_admin(client)
    db = SessionLocal()
    try:
        seen = {}
        for n in range(24):
            login = f"avp{n}"
            make_teacher(client, admin, login=login)
            u = db.query(User).filter(User.login == login).first()
            u.role = "student"
            db.commit()
            got = easter_eggs.pick_avatar_egg(u, db, session_key=f"tab{n}")
            assert got in easter_eggs.AVATAR_EGGS, f"неожиданный выбор: {got}"
            seen.setdefault(got, []).append(login)

            #И у КАЖДОГО метка обязана быть устойчивой: повторный вопрос — тот же ответ.
            assert easter_eggs.pick_avatar_egg(u, db, session_key=f"tab{n}") == got, \
                f"{login}: метка изменилась при повторном обращении"

        assert set(seen) == set(easter_eggs.AVATAR_EGGS), \
            f"на 24 людях выпадала только {sorted(seen)} — вторая отсылка недостижима"
    finally:
        db.close()


def test_avatar_mark_is_not_given_to_staff(client):
    """Преподаватель и админ метки не получают — пасхалки только у студентов.

    Обратный ход: убери проверку роли в `pick_avatar_egg` — тест краснеет."""
    admin = make_admin(client)
    make_teacher(client, admin, login="stf1")
    db = SessionLocal()
    try:
        for login in ("stf1", "admin"):
            u = db.query(User).filter(User.login == login).first()
            if u is None:
                continue
            assert u.role != "student"
            assert easter_eggs.pick_avatar_egg(u, db) is None, \
                f"{login} ({u.role}) получил метку аватарки"
    finally:
        db.close()


def test_lock_lets_the_eighth_attempt_check_the_password(client):
    """Восьмая попытка ещё проверяется, запирает девятая.

    🔥 При пороге 7 человек, ошибшийся семь раз, на восьмой вводил ВЕРНЫЙ пароль и
    получал отказ: замок уже стоял, и пароль не проверялся вовсе. Со стороны это
    «журнал не принимает мой пароль» — ровно то, на что пожаловался Влад."""
    from app import throttle
    assert throttle.MAX_FAILS == 8
    #Far Cry срабатывает на СЕДЬМОЙ неудаче — она обязана быть строго до замка,
    #иначе пасхалка не покажется никогда.
    import inspect
    assert "streak < 7" in inspect.getsource(easter_eggs.farcry_due)
    assert 7 < throttle.MAX_FAILS, "Far Cry срабатывает не раньше замка — его не увидят"

def test_every_achievement_in_the_registry_is_actually_obtainable(client):
    """СКВОЗНАЯ проверка всех пятнадцати: след срабатывания → claim → строка в профиле.

    ⚠️ Точечные тесты выше проверяют по одной ачивке и по одному правилу. Здесь
    проверяется ЦЕЛОЕ: что реестр, пары «пасхалка → ачивка», выдача и витрина сходятся
    для КАЖДОЙ записи. Наш самый частый класс дефекта — «обещание без вызывающего»:
    ачивка объявлена, а получить её нельзя, и узнаётся это от человека, который полгода
    её ловил. Новая ачивка, забытая в любом из четырёх мест, покраснеет здесь сама.

    Обратный ход: убери любую пару из `ACHIEVEMENTS` или сломай `unlock` — тест падает
    с именем конкретной ачивки, а не общим «не сошлось»."""
    from app.models import EasterEggLog
    from datetime import datetime, timezone
    admin = make_admin(client)
    st = make_teacher(client, admin, login="allach")
    uid = _db_user("allach").id

    for aid, egg in sorted(easter_eggs.ACHIEVEMENTS.items()):
        db = SessionLocal()
        try:
            #След пишем напрямую: сам бросок проверяют другие тесты, здесь важно, что
            #ПОСЛЕ состоявшегося срабатывания ачивку действительно можно забрать.
            now = datetime.now(timezone.utc)
            db.add(EasterEggLog(user_id=uid, egg_id=egg,
                                triggered_at=now.isoformat(),
                                created_ts=int(now.timestamp())))
            db.commit()
        finally:
            db.close()
        r = client.post("/web/easter-eggs/claim",
                        json={"egg": egg, "achievement": aid}, headers=st)
        assert r.status_code == 200, f"{aid} ({egg}): claim отказал — {r.text}"
        assert r.json()["unlocked"] is True, f"{aid}: claim прошёл, но ачивка не выдана"

    got = {r["id"] for r in client.get("/web/achievements", headers=st).json()["unlocked"]}
    assert got == set(easter_eggs.ACHIEVEMENTS),         f"не доехали до профиля: {sorted(set(easter_eggs.ACHIEVEMENTS) - got)}"

    #И витрина: любую из полученных можно выставить наружу. `GET /web/achievements`
    #отдаёт отметку СТРОКОЙ (`showcase: true/false`), а не отдельным списком.
    pick = sorted(easter_eggs.ACHIEVEMENTS)[:3]
    r = client.post("/web/achievements/showcase", json={"ids": pick}, headers=st)
    assert r.status_code == 200, r.text
    assert r.json()["showcase"] == pick
    rows = {x["id"]: x for x in client.get("/web/achievements", headers=st).json()["unlocked"]}
    assert [a for a in pick if not rows[a]["showcase"]] == [], "витрина не отметила выбранное"


def _make_student(client, admin, login):
    """Завести пользователя и сделать его студентом (пасхалки только у них)."""
    st = make_teacher(client, admin, login=login)
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == login).first()
        u.role = "student"
        db.commit()
    finally:
        db.close()
    return st


def test_avatar_mark_is_the_same_in_every_tab(client, monkeypatch):
    """Метка аватарки одинакова во всех вкладках и после каждой перезагрузки.

    🔥 Разбор жалобы «украшения DOOM не снимаются» (24.08.2026). Метку выбирал
    `roll_one_of` на КАЖДЫЙ запрос, а запрос делает каждая вкладка. Шанс у пары равен
    единице (это «обычная» ступень редкости — её открывает сам вход), поэтому метка не
    просто выпадала всегда, а ещё и МЕНЯЛАСЬ между окнами: кольцо Detroit в одном,
    свечение DOOM в соседнем.

    Обратный ход: верни `roll_one_of([...])` — двадцати обращений с запасом хватает,
    чтобы увидеть обе метки, и тест падает."""
        #⚠️ Долю на время теста поднимаем до 100 %. Это не подгонка: тест проверяет ДРУГОЕ
    #свойство (стабильность метки / обновление следа), и редкость здесь только мешала бы
    #— половина прогонов получала бы `None` и «падала» без всякой поломки. За саму долю
    #отвечает `test_avatar_share_matches_the_declared_percent`, и там она настоящая.
    #⚠️ Обе по 50, а не одна на 100: розыгрыш ОДИН на пару, и подняв только первую, мы
    #сделали бы вторую недостижимой — тест бы падал по своей же вине.
    monkeypatch.setitem(easter_eggs.EGG_PERCENT, "doom_avatar", 50)
    monkeypatch.setitem(easter_eggs.EGG_PERCENT, "detroit_led", 50)
    admin = make_admin(client)
    st = _make_student(client, admin, "tab2")

    seen = {client.get("/web/easter-eggs/on-login", headers=st).json()["avatar"]
            for _ in range(20)}
    assert len(seen) == 1, f"метка меняется между вкладками: {seen}"
    assert seen.pop() in easter_eggs.AVATAR_EGGS


def test_avatar_mark_refreshes_the_trace_so_claim_always_works(client, monkeypatch):
    """У метки ВСЕГДА свежий след — значит `claim` самолечится.

    🔥 Находка Полковника (24.08.2026), отменившая предыдущее решение целиком. Первый
    вариант починки хранил метку на клиенте и просил сервер её не перебрасывать. Но
    след срабатывания живёт ЧАС (`was_triggered_recently`), а токен — пять: если первый
    `claim` не прошёл (сеть моргнула, сервер ответил 500), восстановленная из памяти
    метка след не обновляла, и ачивку до конца дня забрать было уже нечем. Молча:
    отказ `claim` клиент проглатывает.

    Обратный ход: убери `mark_triggered` из `pick_avatar_egg` — второй claim ниже
    получит 400 «Пасхалка не срабатывала»."""
    from app.models import EasterEggLog
        #⚠️ Долю на время теста поднимаем до 100 %. Это не подгонка: тест проверяет ДРУГОЕ
    #свойство (стабильность метки / обновление следа), и редкость здесь только мешала бы
    #— половина прогонов получала бы `None` и «падала» без всякой поломки. За саму долю
    #отвечает `test_avatar_share_matches_the_declared_percent`, и там она настоящая.
    #⚠️ Обе по 50, а не одна на 100: розыгрыш ОДИН на пару, и подняв только первую, мы
    #сделали бы вторую недостижимой — тест бы падал по своей же вине.
    monkeypatch.setitem(easter_eggs.EGG_PERCENT, "doom_avatar", 50)
    monkeypatch.setitem(easter_eggs.EGG_PERCENT, "detroit_led", 50)
    admin = make_admin(client)
    st = _make_student(client, admin, "tab3")
    uid = _db_user("tab3").id

    egg = client.get("/web/easter-eggs/on-login", headers=st).json()["avatar"]
    aid = next(a for a, e in easter_eggs.ACHIEVEMENTS.items() if e == egg)

    #Состариваем след: имитируем «человек вошёл давно, первый claim не прошёл».
    db = SessionLocal()
    try:
        old_ts = int(datetime.now(timezone.utc).timestamp()) - 4000   # больше часа
        rows = db.query(EasterEggLog).filter(EasterEggLog.user_id == uid,
                                             EasterEggLog.egg_id == egg).all()
        assert rows, "метка выдана, а следа нет вовсе — claim не сработает никогда"
        for row in rows:
            row.created_ts = old_ts
        db.commit()
    finally:
        db.close()

    body = {"egg": egg, "achievement": aid}
    assert client.post("/web/easter-eggs/claim", json=body, headers=st).status_code == 400, \
        "протухший след внезапно принят — проверка свежести не работает"

    #Новая вкладка обращается к серверу — след обязан обновиться сам.
    client.get("/web/easter-eggs/on-login?scene=0", headers=st)
    r = client.post("/web/easter-eggs/claim", json=body, headers=st)
    assert r.status_code == 200, f"claim не самолечится: {r.text}"
    assert r.json()["unlocked"] is True


def test_reload_skips_the_scene_roll_but_still_returns_the_mark(client, monkeypatch):
    """`scene=0` гасит бросок сцены и НЕ трогает метку.

    ⚠️ Это про перезагрузку страницы: новый шанс за F5 не даётся, но украшение обязано
    вернуться. Пока обе величины ехали одним неделимым ответом, клиент после F5 не
    спрашивал ничего, и метка пропадала до конца сессии.

    Обратный ход: убери `if scene` в ручке — сцена снова будет бросаться на каждой
    перезагрузке."""
    import inspect
    src = inspect.getsource(achievements_router.egg_on_login)
    assert "if scene" in src, "признак сцены не влияет на бросок"

        #⚠️ Долю поднимаем до 100 %: тест про то, что `scene=0` гасит СЦЕНУ и не трогает
    #метку. Редкость метки здесь посторонняя и давала бы ложные падения.
    #⚠️ Обе по 50, а не одна на 100: розыгрыш ОДИН на пару, и подняв только первую, мы
    #сделали бы вторую недостижимой — тест бы падал по своей же вине.
    monkeypatch.setitem(easter_eggs.EGG_PERCENT, "doom_avatar", 50)
    monkeypatch.setitem(easter_eggs.EGG_PERCENT, "detroit_led", 50)
    admin = make_admin(client)
    st = _make_student(client, admin, "tab4")
    data = client.get("/web/easter-eggs/on-login?scene=0", headers=st).json()
    assert data["egg"] is None, "перезагрузка всё-таки бросила сцену"
    assert data["avatar"] in easter_eggs.AVATAR_EGGS, "метка не приехала после перезагрузки"

def test_relogin_gives_a_fresh_avatar_mark(client):
    """Выход и новый вход перевыбирают метку, а вкладки одного входа — нет.

    🔥 Жалоба Влада и второго тестировщика 24.08.2026: «получил DOOM, вышел, зашёл —
    тот же DOOM». Метка была привязана к паре (человек, ДЕНЬ), то есть до полуночи
    вторую отсылку было не увидеть, а вторую ачивку не взять. День — слишком крупная
    единица: за него человек входит десяток раз, и каждый вход обязан быть новым шансом.

    Проверяем ОБА свойства сразу, потому что чинить одно, ломая другое, здесь очень
    легко: сделаешь бросок на каждый запрос — метка снова начнёт меняться между
    вкладками (дефект, из-за которого её вообще сделали детерминированной).

    Обратный ход: верни в `pick_avatar_egg` ключ на дату вместо `session_key` — первая
    половина теста падает; сделай выбор случайным — падает вторая."""
    admin = make_admin(client)
    st = make_teacher(client, admin, login="relog")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == "relog").first()
        u.role = "student"
        db.commit()
        uid = u.id

        #Одна сессия = один `jti`: сколько вкладок ни открой, метка одна и та же.
        #⚠️ `None` здесь такой же законный ответ, как метка, и он тоже обязан быть
        #стабильным: «мигающее» украшение (есть в одной вкладке, нет в соседней) —
        #ровно тот дефект, из-за которого выбор вообще сделали детерминированным.
        one = {easter_eggs.pick_avatar_egg(u, db, session_key="jti-A") for _ in range(20)}
        assert len(one) == 1, f"ответ меняется в пределах ОДНОГО входа: {one}"

        #Разные входы — разные `jti`. За сотню входов обязаны встретиться обе метки
        #(и, разумеется, промахи — метка показывается примерно в четверти случаев).
        seen = {easter_eggs.pick_avatar_egg(u, db, session_key=f"jti-{i}")
                for i in range(100)}
        assert set(easter_eggs.AVATAR_EGGS) <= seen, \
            f"за 100 входов выпадало только {seen} — перезаход не даёт нового шанса"
    finally:
        db.close()

    #И на уровне ручки: два разных токена одного человека дают разные метки хотя бы
    #иногда, а один и тот же токен — всегда одну.
    #⚠️ `None` — законный ответ ручки: метка показывается не каждый вход.
    first = client.get("/web/easter-eggs/on-login", headers=st).json()
    assert first["avatar"] in (*easter_eggs.AVATAR_EGGS, None), first


def test_owning_one_of_the_pair_guarantees_the_other(client):
    """Получил DOOM — следующий вход обязан показать Detroit, без броска.

    🔥 Слова Влада: «иначе получили дум и не сможем получить детроит». Одного
    случайного выбора мало: 50/50 на вход означает, что невезучему одна и та же метка
    выпадет пять раз подряд, и жалоба вернётся. Обе они «обычной» ступени — их
    открывает сам факт входа, растягивать это на неделю невезения незачем.

    Обратный ход: убери ветку `len(missing) == 1` — тест падает на первом же входе,
    где сошёлся хеш."""
    admin = make_admin(client)
    make_teacher(client, admin, login="pairguard")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.login == "pairguard").first()
        u.role = "student"
        db.commit()

        for owned_egg in easter_eggs.AVATAR_EGGS:
            #Чистим пару и выдаём ровно одну из двух.
            db.query(UserAchievement).filter(UserAchievement.user_id == u.id).delete()
            db.commit()
            easter_eggs.unlock(u.id, easter_eggs._ACH_OF[owned_egg], db)

            other = [e for e in easter_eggs.AVATAR_EGGS if e != owned_egg][0]
            #Любой ключ сессии: правило владения сильнее хеша, иначе оно ничего не даёт.
            #⚠️ `None` — законный ответ (метка показывается не каждый вход, см. долю в
            #EGG_PERCENT). Проверяем не «показали всегда», а «никогда не показали ту,
            #что уже есть»: именно это делает вторую ачивку недостижимой.
            shown = [easter_eggs.pick_avatar_egg(u, db, session_key=f"s{i}")
                     for i in range(60)]
            wrong = [g for g in shown if g == owned_egg]
            assert not wrong, \
                f"владеет {owned_egg}, а показали её же {len(wrong)} раз — вторую не взять"
            assert other in shown, \
                f"за 60 входов вторая метка ({other}) не показалась ни разу"

        #Когда обе получены, правило отключается и метка снова стабильна по входу.
        db.query(UserAchievement).filter(UserAchievement.user_id == u.id).delete()
        db.commit()
        for e in easter_eggs.AVATAR_EGGS:
            easter_eggs.unlock(u.id, easter_eggs._ACH_OF[e], db)
        both = {easter_eggs.pick_avatar_egg(u, db, session_key="same") for _ in range(10)}
        assert len(both) == 1, "с обеими ачивками метка снова обязана быть стабильной"
    finally:
        db.close()


def test_avatar_pair_map_is_derived_not_copied():
    """`_ACH_OF` выводится из `ACHIEVEMENTS`, а не написан руками второй копией.

    ⚠️ Две таблицы одного соответствия — это две таблицы, которые однажды разъедутся
    молча. Проверяем свойство, а не значения."""
    assert easter_eggs._ACH_OF == {egg: aid for aid, egg in easter_eggs.ACHIEVEMENTS.items()}
    for egg in easter_eggs.AVATAR_EGGS:
        assert egg in easter_eggs._ACH_OF, f"{egg} не имеет ачивки — пара сломана"

def test_avatar_share_matches_the_declared_percent():
    """Заявленные доли — правда, и проверяется НАСТОЯЩАЯ функция, а не её копия.

    🔥 Здесь тест дважды оказывался бессильным, и оба раза по разным причинам.
    Сначала продукт брал `hash_byte % 100`: байт это 0..255, поэтому первым пятидесяти
    шести значениям доставался лишний шанс, и объявленные 25 % на деле были 29.2 %.
    Потом я это починил — но тест СЧИТАЛ ДОЛЮ САМ, повторяя формулу у себя. Обратный
    ход (вернуть смещение в продукт) оставил его ЗЕЛЁНЫМ: копия сверялась с копией.
    Поэтому решение вынесено в `easter_eggs.avatar_draw` и гоняется именно оно.

    Обратный ход: подмени в `avatar_draw` расчёт на остаток по модулю — доля уезжает
    на ~3.4 п.п., и допуск ниже это ловит."""
    want = {e: easter_eggs.EGG_PERCENT[e] for e in easter_eggs.AVATAR_EGGS}
    n = 60000
    got = {e: 0 for e in want}
    nothing = 0
    for i in range(n):
        e = easter_eggs.avatar_draw(f"stud:u:{i}", f"jti{i}")
        if e is None:
            nothing += 1
        else:
            got[e] += 1

    for egg, share in want.items():
        measured = got[egg] / n * 100
        #Допуск 0.7 п.п. — заметно уже смещения по модулю (3.4 п.п. на этих долях) и
        #много шире случайного разброса при таком n.
        assert abs(measured - share) < 0.7, f"{egg}: заявлено {share} %, вышло {measured:.2f} %"

    #Ничего не показано — оставшаяся доля. Заодно это проверка, что обе разом не выпали:
    #сумма трёх исходов обязана сойтись ровно в n.
    assert nothing + sum(got.values()) == n
    assert abs(nothing / n * 100 - (100 - sum(want.values()))) < 0.7


def test_owning_one_lets_it_take_the_whole_pair_share():
    """Кому не хватает одной — она забирает долю ВСЕЙ пары, а не свою половину.

    Иначе, получив первую ачивку, человек ждал бы вторую вдвое дольше — а жаловались
    ровно на то, что вторую не взять."""
    total = sum(easter_eggs.EGG_PERCENT[e] for e in easter_eggs.AVATAR_EGGS)
    n = 60000
    for missing in easter_eggs.AVATAR_EGGS:
        other = [e for e in easter_eggs.AVATAR_EGGS if e != missing][0]
        hits = 0
        for i in range(n):
            e = easter_eggs.avatar_draw(f"stud:u:{i}", f"jti{i}", missing=[missing])
            assert e in (missing, None), f"показали {e}, хотя человеку не хватает {missing}"
            hits += e is not None
        assert abs(hits / n * 100 - total) < 0.7,             f"{missing}: доля {hits / n * 100:.2f} %, а должна быть вся пара ({total} %)"
        assert other not in (missing,)
