"""test_college_time.py — «сегодня» на сервере = сегодня В КОЛЛЕДЖЕ (Улан-Удэ, UTC+8).

До 15.10.2026 сервер брал число и день недели с часов МАШИНЫ, а боевой VPS живёт по
Москве: с 00:00 до 05:00 по Улан-Удэ расписание, виджет, Вектор и сводка дня отвечали
за вчера, отчёт куратора, заведённый до 08:00, отрезал сегодняшние занятия, а
напоминание «завтра в 10:00» уезжало на восемь часов. Тесты были зелёными, потому что
продукт и тест брали одни часы.

Здесь часы колледжа подставляются (`college_clock._utcnow`), поэтому проверки не зависят
от пояса машины, на которой идёт прогон. Каждый случай стоит в окне, где МОСКВА и UTC
показывают другое число, чем Улан-Удэ, — иначе тест был бы зелёным и до починки.

⚠️ ОБРАТНЫЙ ХОД проверен 15.10.2026: возврат `date.today()` в `current_week_parity`,
UTC-«сейчас» в разборе напоминаний и среза `iso[:10]` у отчёта куратора красит
соответствующие тесты.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

import app  # noqa: F401 — кладёт корень репозитория в путь импорта
import college_clock


def _freeze(monkeypatch, utc: datetime):
    monkeypatch.setattr(college_clock, "_utcnow", lambda: utc)


# 16.10.2026 00:30 в Улан-Удэ = 15.10 16:30 UTC = 15.10 19:30 МСК.
MIDNIGHT_IRK = datetime(2026, 10, 15, 16, 30, tzinfo=timezone.utc)


def test_parity_follows_the_college_day_not_the_machine(monkeypatch):
    """Ночь с воскресенья на понедельник: в Улан-Удэ уже понедельник новой недели."""
    from app import schedule_web
    sunday_utc = datetime(2026, 10, 18, 16, 30, tzinfo=timezone.utc)   #пн 19.10 00:30 Иркутск
    _freeze(monkeypatch, sunday_utc)
    assert college_clock.today() == date(2026, 10, 19)
    assert schedule_web.current_week_parity() == schedule_web.current_week_parity(date(2026, 10, 19))
    #Неделя действительно сменилась — иначе проверка была бы зелёной при любой дате.
    assert (schedule_web.current_week_parity(date(2026, 10, 19))
            != schedule_web.current_week_parity(date(2026, 10, 18)))


def test_public_week_reports_the_college_date(client, monkeypatch):
    _freeze(monkeypatch, MIDNIGHT_IRK)
    r = client.get("/public/week")
    assert r.status_code == 200, r.text
    assert r.json()["date"] == "2026-10-16", r.json()


#Год — заведомо не текущий (сторож `tests/test_no_calendar_bound_tests.py`): часы здесь
#заморожены, и проверяется граница суток, а не «какой сейчас год».
@pytest.mark.parametrize("utc, term", [
    (datetime(2030, 8, 31, 16, 30, tzinfo=timezone.utc), ("2030/2031", 1)),   #1 сен 00:30 Иркутск
    (datetime(2030, 8, 31, 15, 30, tzinfo=timezone.utc), ("2029/2030", 2)),   #31 авг 23:30 Иркутск
])
def test_new_academic_year_starts_at_college_midnight(monkeypatch, utc, term):
    from app import db
    _freeze(monkeypatch, utc)
    assert db.default_term() == term


def test_curator_report_cutoff_is_the_college_date():
    """Отчёт заведён в 07:30 по Улан-Удэ (23:30 UTC накануне): граница — сегодняшнее число."""
    from app.routers.messenger._common import _iso_to_ddmmyyyy
    assert _iso_to_ddmmyyyy("2026-10-15T23:30:00+00:00") == "16.10.2026"
    assert _iso_to_ddmmyyyy("2026-10-15T23:30:00Z") == "16.10.2026"
    assert _iso_to_ddmmyyyy("мусор") == ""


def test_exports_are_stamped_with_college_time(monkeypatch):
    _freeze(monkeypatch, MIDNIGHT_IRK)
    assert college_clock.stamp("%d.%m.%Y %H:%M") == "16.10.2026 00:30"


# ── Напоминания ─────────────────────────────────────────────────────────────────────
def _setup_chat(client):
    from conftest import make_admin
    admin = make_admin(client)
    for login, sur, name in (("ivanova", "Иванова", "Мария"), ("petrov", "Петров", "Пётр")):
        r = client.post("/web/admin/students", json={
            "login": login, "surname": sur, "name": name, "group": "ИС-21",
            "password": "studpass1"}, headers=admin)
        assert r.status_code == 200, r.text

    def headers(login):
        r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}

    h1 = headers("ivanova")
    peer = next(s["id"] for s in client.get("/web/admin/students", headers=admin).json()["students"]
                if s.get("login") == "petrov")
    r = client.post(f"/web/messenger/chats/direct/{peer}", headers=h1)
    assert r.status_code == 200, r.text
    return h1, r.json()["conversation_id"]


def _say(client, h, conv, text):
    r = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": text}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# 16.10.2026 07:30 в Улан-Удэ = 15.10 23:30 UTC: по UTC «завтра» — это ещё 16-е.
MORNING_IRK = datetime(2026, 10, 15, 23, 30, tzinfo=timezone.utc)


def test_reminder_suggestion_is_ten_in_the_morning_tomorrow_in_ulan_ude(client, monkeypatch):
    h, conv = _setup_chat(client)
    mid = _say(client, h, conv, "напомни завтра в 10:00 про отчёт")
    _freeze(monkeypatch, MORNING_IRK)
    r = client.get(f"/web/messenger/messages/{mid}/reminder-suggest", headers=h)
    assert r.status_code == 200, r.text
    when = datetime.fromisoformat(r.json()["when"])
    assert when.astimezone(college_clock.TZ).strftime("%d.%m %H:%M") == "17.10 10:00", r.json()


def test_reminder_from_text_is_stored_in_utc(client, monkeypatch):
    """Без явного времени сервер берёт разобранное — и кладёт его в UTC, иначе строковое
    сравнение в `_fire_due_reminders` сработало бы не вовремя."""
    h, conv = _setup_chat(client)
    mid = _say(client, h, conv, "12 мая в 10:00 защита")
    _freeze(monkeypatch, MORNING_IRK)
    r = client.post(f"/web/messenger/messages/{mid}/reminder", json={}, headers=h)
    assert r.status_code == 200, r.text
    rows = client.get("/web/messenger/reminders", headers=h).json()["reminders"]
    assert [x["remind_at"] for x in rows] == ["2027-05-12T02:00:00+00:00"], rows


def test_reminder_sent_with_an_offset_still_fires_on_time(client):
    """Клиент прислал время со смещением «+08:00» и уже прошедшее — оно обязано
    сработать. До 15.10.2026 метка ложилась как есть, и строка «…T22:59+08:00»
    сравнивалась с UTC-«сейчас» как более поздняя: напоминание молчало до вечера."""
    h, conv = _setup_chat(client)
    mid = _say(client, h, conv, "созвон")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).astimezone(college_clock.TZ)
    r = client.post(f"/web/messenger/messages/{mid}/reminder",
                    json={"when": past.isoformat()}, headers=h)
    assert r.status_code == 200, r.text
    items = client.get("/me/events?filter=all&limit=100", headers=h).json()["items"]
    assert [i for i in items if i["kind"] == "reminder"], items


def test_naive_reminder_time_means_college_time(client):
    """Время без зоны — это то, что человек видит на часах колледжа, а не UTC."""
    h, conv = _setup_chat(client)
    mid = _say(client, h, conv, "экзамен")
    r = client.post(f"/web/messenger/messages/{mid}/reminder",
                    json={"when": "2030-01-10T09:00:00"}, headers=h)
    assert r.status_code == 200, r.text
    rows = client.get("/web/messenger/reminders", headers=h).json()["reminders"]
    assert [x["remind_at"] for x in rows] == ["2030-01-10T01:00:00+00:00"], rows
