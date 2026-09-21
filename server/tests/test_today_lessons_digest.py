"""
test_today_lessons_digest.py — сводка «Пары на сегодня» (просьба тестеров 20.09.2026).

━━ ЧТО ЭТО ━━
Отдельная категория уведомлений и отдельное письмо: сколько сегодня пар и во сколько
первая. Тестеры просили её именно тумблером, и категория заведена своя, а не «schedule»:
то уведомление про ПРАВКУ расписания и приходит редко, а это — каждый учебный день.
Одной кнопкой человек выключил бы вместе со сводкой и замены пар.

⚠️ ЧЕСТНАЯ ГРАНИЦА, названная прямо и проверенная последним тестом: сводка уходит ПРИ
ОБРАЩЕНИИ к `/me/events` (тем же попутным приёмом, что напоминания), а не по будильнику.
Кто не открывал приложение и чьё устройство не опрашивало события — тот её не получит.
Настоящая рассылка «всем к 8:00» требует планировщика, а фоновый поток на одноядерной
машине у нас запрещён (см. CLAUDE.md). Делать вид, что будильник уже есть, нельзя.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `_notify_today_lessons` из `/me/events` — краснеет
первый тест; снять метку «уже отправляли сегодня» — краснеет второй.
"""
from conftest import make_admin
from app.security import hash_password


def _student(client, admin, login="dig1", group="К-24"):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": "stud:" + login, "role": "student", "login": login,
        "password_hash": hash_password("studpass1"),
        "surname": "Дигестов", "name": "Дмитрий", "group_name": group,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _fake_digest(monkeypatch, count=3, first="09:00"):
    """Расписание в тестах НЕ ТЯНЕМ: оно приходит с чужого портала по сети, и прогон,
    зависящий от него, краснел бы от чужой аварии. Сам расчёт проверяется ниже отдельно."""
    from app.routers import me as me_mod
    from app.routers.web import schedule as sched
    monkeypatch.setattr(sched, "today_digest", lambda db, user: (count, first))
    return me_mod


def test_the_digest_arrives_once_a_day(client, monkeypatch):
    admin = make_admin(client)
    sh = _student(client, admin)
    _fake_digest(monkeypatch)

    assert client.get("/me/events?filter=all", headers=sh).status_code == 200
    first = [e for e in client.get("/me/events?filter=all", headers=sh).json()["items"]
             if e.get("kind") == "lessons_today"]
    assert len(first) == 1, f"сводка не отправлена при обращении за уведомлениями: {first}"
    assert "3" in (first[0].get("body") or ""), first[0]


def test_the_digest_is_not_repeated_on_every_request(client, monkeypatch):
    """Иначе каждое открытие приложения за день добавляло бы новое письмо — то есть
    правка, сделанная ПРОТИВ спама, сама стала бы спамом."""
    admin = make_admin(client)
    sh = _student(client, admin)
    _fake_digest(monkeypatch)

    for _ in range(4):
        assert client.get("/me/events?filter=all", headers=sh).status_code == 200
    got = [e for e in client.get("/me/events?filter=all", headers=sh).json()["items"]
           if e.get("kind") == "lessons_today"]
    assert len(got) == 1, f"сводка пришла {len(got)} раз за один день"


def test_an_empty_day_produces_nothing(client, monkeypatch):
    """Воскресенье и каникулы: «сегодня пар: 0» — это не сводка, а лишний стук."""
    admin = make_admin(client)
    sh = _student(client, admin)
    _fake_digest(monkeypatch, count=0, first="")

    assert client.get("/me/events?filter=all", headers=sh).status_code == 200
    got = [e for e in client.get("/me/events?filter=all", headers=sh).json()["items"]
           if e.get("kind") == "lessons_today"]
    assert not got, "прислали сводку о том, что пар нет"


def test_a_teacher_does_not_get_a_student_digest(client, monkeypatch):
    """У преподавателя пары в нескольких группах — это другая сводка, и делать вид, что
    она та же, значило бы показать ему расписание одной случайной группы."""
    admin = make_admin(client)
    _fake_digest(monkeypatch)
    r = client.get("/me/events?filter=all", headers=admin)
    assert r.status_code == 200, r.text
    assert not [e for e in r.json()["items"] if e.get("kind") == "lessons_today"]


def test_the_category_can_be_switched_off(client, monkeypatch):
    """Тумблер «Пары на сегодня» гасит ПУШ, а письмо остаётся — то же правило, что у
    остальных категорий: отключается то, что дёргает человека, а не история."""
    from app import rustore_push
    admin = make_admin(client)
    sh = _student(client, admin, login="dig2")
    _fake_digest(monkeypatch)

    r = client.post("/me/prefs", json={"notify": {"lessons": False}}, headers=sh)
    assert r.status_code == 200, r.text

    sent = []
    monkeypatch.setattr(rustore_push.config, "push_enabled", lambda: True)
    monkeypatch.setattr(rustore_push, "send_to_token",
                        lambda *a, **kw: sent.append(a) or (True, 200, ""))
    assert client.get("/me/events?filter=all", headers=sh).status_code == 200
    got = [e for e in client.get("/me/events?filter=all", headers=sh).json()["items"]
           if e.get("kind") == "lessons_today"]
    assert got, "письмо пропало вместе с пушем — человек не узнает о парах вовсе"
    assert not sent, "категория выключена, а пуш всё равно ушёл"


#──────────────────────────────────────────────────────────────────────────────────────
#САМ РАСЧЁТ. Проверяется отдельно и БЕЗ СЕТИ: расписание приходит с чужого портала, и
#прогон, который туда ходит, краснел бы от чужой аварии (у нас это уже стоило двух
#мигающих тестов входа, см. CLAUDE.md про `test_login_bridge`).
def test_the_count_comes_from_the_same_schedule_the_screen_shows(monkeypatch):
    """Ключевое свойство: считает ТОТ ЖЕ код, что строит расписание на экране, — иначе
    сводка покажет снятую админом пару или не покажет добавленную."""
    from app.routers.web import schedule as sched
    from schedule.model import WEEKDAYS
    from datetime import datetime, timezone

    #Берём ЗАВЕДОМО учебный день (понедельник), а не «сегодня»: 20.09.2026 — воскресенье,
    #и тест «по сегодня» был бы зелёным только шесть дней из семи, а в седьмой проверял
    #бы совсем другое. Инвариант «тест не привязан к календарю» в действии.
    monday = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    day_key = WEEKDAYS[monday.weekday()]
    week = sched.schedule_web.current_week_parity()

    #Снимок ЕСТЬ в кэше (иначе сработает ранний выход «расписание не прогрето»), а
    #раскладку дня подменяем на уровне `_group_schedule` — там она уже с правками.
    monkeypatch.setattr(sched.schedule_web, "get_group",
                        lambda name, category="", force=False, cached_only=False: {"weeks": {}})
    monkeypatch.setattr(sched, "_group_schedule", lambda db, g, c, cached_only=False: {"weeks": {
        week: {day_key: [
            {"raw": "лек.Математика", "time": "10:45-12:20"},
            {"raw": "_", "time": "09:00-10:35"},          #окно — не пара
            {"raw": "пр.Физика", "time": "09:00-10:35"},
        ]},
    }})

    class _U:
        group_name, role, login, id = "К-24", "student", "bob", "stud:bob"

    class _Q:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return None

    class _DB:
        def query(self, *a, **kw):
            return _Q()

    count, first_at = sched.today_digest(_DB(), _U(), today=monday)
    assert count == 2, f"окно посчитали парой: {count}"
    assert first_at == "09:00", f"время первой пары определено неверно: {first_at!r}"


def test_a_student_without_a_group_gets_nothing(monkeypatch):
    """Только что заведённый студент без группы: расписания у него нет, и спрашивать
    портал незачем — это поход в сеть ради заведомо пустого ответа."""
    from app.routers.web import schedule as sched

    called = []
    monkeypatch.setattr(sched, "_group_schedule", lambda db, g, c, cached_only=False: called.append(g) or {})

    class _U:
        group_name, role, login, id = "", "student", "bob", "stud:bob"

    assert sched.today_digest(object(), _U()) == (0, "")
    assert not called, "полезли за расписанием, хотя группы у человека нет"


#──────────────────────────────────────────────────────────────────────────────────────
#ПОЧИНКА 21.09.2026: день недели берётся из ТОГО ЖЕ календаря, что чётность недели.
#
#Было: `datetime.now(timezone.utc).weekday()`, а чётность считает
#`schedule_web.current_week_parity()` от `date.today()` — по ЛОКАЛЬНОМУ времени машины.
#Боевой сервер живёт в Europe/Moscow (проверено `date` на бою), поэтому каждые сутки с
#00:00 до 03:00 МСК день брался вчерашний, а неделя сегодняшняя: сводка показывала
#ЧУЖОЙ день и выглядела совершенно настоящей. В Улан-Удэ это окно приходится на
#05:00–08:00 утра — ровно на то время, когда «что у меня сегодня» и спрашивают.
#
#⚠️ Тест НЕ привязан к календарю: он не ждёт конкретного дня, а проверяет СВОЙСТВО —
#обе величины взяты из одного источника. Иначе он краснел бы три часа в сутки и был бы
#зелёным всё остальное время, то есть проверял бы погоду, а не код.
#
#⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть `datetime.now(timezone.utc)` — краснеет первый тест.
def test_the_day_and_the_week_come_from_one_calendar():
    import re
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "routers" / "web" / "schedule.py").read_text(encoding="utf-8")
    body = src[src.index("def today_digest"):]
    body = body[:body.index("\n@router")] if "\n@router" in body else body
    body = re.sub(r"#.*", "", body)          #пояснения рядом объясняют сам дефект
    body = re.sub(r'"""[\s\S]*?"""', "", body)

    assert "timezone.utc" not in body, (
        "день недели снова считается в UTC, а чётность недели — по локальной дате: "
        "каждую ночь с 00:00 до 03:00 МСК сводка показывает ЧУЖОЙ день")
    assert re.search(r"datetime\.now\(\)\.weekday\(\)|today or datetime\.now\(\)", body), (
        "день перестал браться локально — сверьте с schedule_web.current_week_parity")


def test_the_digest_day_matches_what_the_schedule_page_would_show(monkeypatch):
    """Сквозная проверка: сводка находит пары именно того дня, который СЕЙЧАС считает
    расписание. Ловит расхождение календарей без привязки к конкретной дате."""
    from datetime import date
    from app.routers.web import schedule as sched
    from schedule.model import WEEKDAYS

    idx = date.today().weekday()
    if idx >= len(WEEKDAYS):
        return          #воскресенья в расписании колледжа нет — проверять нечего

    week = sched.schedule_web.current_week_parity()
    monkeypatch.setattr(sched.schedule_web, "get_group",
                        lambda name, category="", force=False, cached_only=False: {"weeks": {}})
    monkeypatch.setattr(sched, "_group_schedule", lambda db, g, c, cached_only=False: {"weeks": {
        week: {WEEKDAYS[idx]: [{"raw": "лек.Математика", "time": "09:00-10:35"}]},
    }})

    class _U:
        group_name, role, login, id = "К-24", "student", "bob", "stud:bob"

    class _Q:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return None

    class _DB:
        def query(self, *a, **kw):
            return _Q()

    count, _first = sched.today_digest(_DB(), _U())
    assert count == 1, (
        "сводка не нашла пару того дня, который показывает расписание — календари разошлись")


#──────────────────────────────────────────────────────────────────────────────────────
#ПОЧИНКА 21.09.2026: сводка не ходит в сеть и не теряет день из-за холодного кэша.
#
#`today_digest` считается на пути `GET /me/events`, который приложение опрашивает в
#фоне. `schedule_web.get_group` при промахе кэша идёт на ЧУЖОЙ портал с таймаутом 20 с,
#а кэш живёт 3 часа — то есть после ночи он протух у всех 106 групп, и каждый первый
#студент каждой группы занимал бы поток ровно в утренний час пик, на одном ядре.
#
#⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `cached_only=True` — краснеет первый тест; вернуть
#простановку метки при нулевой сводке — второй.
def test_the_digest_never_reaches_the_portal(monkeypatch):
    """Свойство: расписание для сводки читается ТОЛЬКО из кэша."""
    from app.routers.web import schedule as sched

    seen = {}

    def _spy(name, category="", force=False, cached_only=False):
        seen["cached_only"] = cached_only
        return None

    monkeypatch.setattr(sched.schedule_web, "get_group", _spy)

    class _U:
        group_name, role, login, id = "К-24", "student", "bob", "stud:bob"

    class _Q:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return None

        def all(self):
            #Настоящий `_group_schedule` зовёт `_apply_overrides`, а тот спрашивает
            #админские правки. Без этого метода тест падал бы на AttributeError, и
            #проверка «не ходит в сеть» не выполнялась бы вовсе.
            return []

    class _DB:
        def query(self, *a, **kw):
            return _Q()

    sched.today_digest(_DB(), _U())
    assert seen.get("cached_only") is True, (
        "сводка читает расписание с походом на портал — это до 20 с в потоке на каждого "
        "первого студента каждой группы, прямо на пути опроса уведомлений")


def test_a_cold_cache_does_not_burn_the_whole_day(client, monkeypatch):
    """Расписания ещё нет в кэше — сводка обязана попробовать снова, а не пропасть.

    Ноль значит две разные вещи: «пар сегодня нет» и «кэш холодный». Суточная метка в
    обоих случаях потеряла бы сводку у всей группы из-за одного неудачного момента.

    🔥 ПРОВЕРЯЕМ САМ СРОК, А НЕ «ПРИШЛА ЛИ СВОДКА ПОТОМ». Первая версия этого теста
    сбрасывала общее состояние между попытками — то есть снимала метку ЛЮБОГО срока и
    оставалась зелёной даже с суточной, ровно тот случай, ради которого у нас заведён
    обратный ход. Поймано им же 21.09.2026.
    """
    from app.routers import me as me_mod
    from app.routers.web import schedule as sched
    from app import shared_state

    admin = make_admin(client)
    sh = _student(client, admin, login="cold")

    marks = []
    real_set = shared_state.set
    monkeypatch.setattr(shared_state, "set",
                        lambda key, value, ttl=None: marks.append((key, ttl)) or real_set(key, value, ttl=ttl))

    #Кэш холодный: сводки нет, и день сжигать нельзя.
    monkeypatch.setattr(sched, "today_digest", lambda db, user, today=None: (0, ""))
    assert client.get("/me/events?filter=all", headers=sh).status_code == 200
    cold = [ttl for key, ttl in marks if key.startswith("digest:lessons:")]
    assert cold, "пустая сводка не оставила вообще никакой метки — каждый опрос считает заново"
    assert cold[-1] <= 3600, (
        f"пустая сводка помечена на {cold[-1]} с: один холодный момент гасит сводку всей "
        f"группе до завтра")
    assert cold[-1] == me_mod._DIGEST_RETRY_S

    #А настоящая сводка закрывает день целиком — иначе она придёт повторно.
    shared_state.reset_for_tests()
    marks.clear()
    monkeypatch.setattr(sched, "today_digest", lambda db, user, today=None: (2, "09:00"))
    assert client.get("/me/events?filter=all", headers=sh).status_code == 200
    real = [ttl for key, ttl in marks if key.startswith("digest:lessons:")]
    assert real and real[-1] >= 12 * 3600, (
        f"отправленная сводка помечена на {real} — она придёт ещё раз за тот же день")

    got = [e for e in client.get("/me/events?filter=all", headers=sh).json()["items"]
           if e.get("kind") == "lessons_today"]
    assert len(got) == 1


def test_a_cold_cache_never_becomes_a_schedule_made_of_overrides_only(monkeypatch):
    """Кэш пуст, но у группы есть админская правка — сводки быть НЕ ДОЛЖНО.

    `_apply_overrides` при отсутствии снимка собирает расписание ТОЛЬКО из правок (это
    верно для колледжа без портала). На пути сводки это означало бы «Сегодня пар: 1»
    вместо настоящих пяти — с виду настоящую сводку, после которой метка дня гасит
    правильную до завтра. Нашёл Полковник 21.09.2026.
    """
    from app.routers.web import schedule as sched

    monkeypatch.setattr(sched.schedule_web, "get_group",
                        lambda name, category="", force=False, cached_only=False: None)

    class _Ov:
        group_name, week, day, pair_no, subgroup = "К-24", 1, "Пнд", 3, 0
        action, subject, teacher, room, kind, deleted = "set", "Физика", "", "14", "лек", False

    class _Q:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return None

        def all(self):
            return [_Ov()]

    class _DB:
        def query(self, *a, **kw):
            return _Q()

    class _U:
        group_name, role, login, id = "К-24", "student", "bob", "stud:bob"

    assert sched.today_digest(_DB(), _U()) == (0, ""), (
        "при холодном кэше сводка собралась из одних админских правок — студент получит "
        "ложное число пар, а правильная сводка в этот день уже не уйдёт")


def test_the_week_parity_follows_the_same_day(monkeypatch):
    """Чётность недели обязана считаться от ТОГО ЖЕ дня, что и день недели.

    Иначе вызов с явной датой даёт пары одного календаря и неделю другого — смесь,
    выглядящую как настоящее расписание (нашёл Полковник)."""
    from datetime import datetime, timedelta
    from app.routers.web import schedule as sched

    asked = []
    real = sched.schedule_web.current_week_parity
    monkeypatch.setattr(sched.schedule_web, "current_week_parity",
                        lambda d=None: asked.append(d) or real(d))
    #Снимок непустой: иначе сработает ранний выход по холодному кэшу и до расчёта
    #недели дело не дойдёт вовсе — тест был бы зелёным, ничего не проверив.
    monkeypatch.setattr(sched.schedule_web, "get_group",
                        lambda name, category="", force=False, cached_only=False: {"weeks": {}})

    class _Q:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return None

        def all(self):
            return []

    class _DB:
        def query(self, *a, **kw):
            return _Q()

    class _U:
        group_name, role, login, id = "К-24", "student", "bob", "stud:bob"

    when = datetime(2026, 9, 21, 9, 0) + timedelta(days=7)
    sched.today_digest(_DB(), _U(), today=when)
    assert asked and asked[0] is not None and asked[0] == when.date(), (
        f"чётность недели спрошена не про тот день: {asked}")
