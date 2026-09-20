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

    monkeypatch.setattr(sched, "_group_schedule", lambda db, g, c: {"weeks": {
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
    monkeypatch.setattr(sched, "_group_schedule", lambda db, g, c: called.append(g) or {})

    class _U:
        group_name, role, login, id = "", "student", "bob", "stud:bob"

    assert sched.today_digest(object(), _U()) == (0, "")
    assert not called, "полезли за расписанием, хотя группы у человека нет"
