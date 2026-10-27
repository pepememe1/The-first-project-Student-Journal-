"""Ошибки интерфейса и время старта от клиентов (app/client_metrics.py, 23.10.2026).

Ручка открыта до входа, поэтому проверяем три вещи: личное в сводку не попадает, память не
растёт от потока отчётов, а сводку видит только админ.
"""
import json

import pytest

from app import client_metrics
from app.client_metrics import ERROR_LIMIT, metrics, scrub


@pytest.fixture(autouse=True)
def _fresh():
    metrics.reset()
    yield
    metrics.reset()


def _report(client, payload, **kw):
    return client.post("/app/client-report", content=json.dumps(payload),
                       headers={"Content-Type": "text/plain"}, **kw)


def test_report_is_accepted_before_login_and_lands_in_the_admin_snapshot(client):
    from conftest import make_admin
    r = _report(client, {"platform": "android", "version": "1.261022.1745", "errors": [{
        "name": "TypeError", "message": "Cannot read properties of undefined (reading 'x')",
        "frame": "assets/index-abc.js:1:2345", "route": "/teacher/journal"}]})
    assert r.status_code == 204
    assert client.get("/web/admin/server/metrics").status_code == 401
    snap = client.get("/web/admin/server/metrics", headers=make_admin(client)).json()["client"]
    assert snap["errors"][0]["count"] == 1
    assert snap["errors"][0]["route"] == "/teacher/journal"
    assert snap["errors"][0]["frame"] == "assets/index-abc.js:1:2345"


def test_personal_data_does_not_reach_the_snapshot(client):
    """Имя в кавычках, почта, номер зачётки и адрес страницы с параметрами — мимо сводки."""
    _report(client, {"platform": "web", "version": "1", "errors": [{
        "name": "Error", "message": "Нет студента 'Иванов Пётр' ivanov@mail.ru 2041577",
        "frame": "https://esstu-gradebook.ru/assets/a.js:1:2", "route": "/messages?peer=ivanov"}]})
    text = json.dumps(metrics.snapshot(), ensure_ascii=False)
    for leak in ("Иванов", "ivanov", "2041577", "esstu-gradebook.ru", "peer="):
        assert leak not in text, leak
    row = metrics.snapshot()["errors"][0]
    assert row["route"] == "?" and row["frame"] == ""


def test_scrub_matches_the_client_rule():
    #Тот же набор, что в web/tests/clientReport.test.mjs: правило чистки одно на обоих концах.
    assert scrub("reading 'Иванов'") == "reading …"
    assert scrub("x «Петров» y") == "x … y"
    assert scrub("mail a@b.ru now") == "mail … now"
    assert scrub("id 12345 at 7") == "id N at 7"
    assert scrub("a\nb") == "a\\nb"
    #Апостроф внутри слова — не кавычка (Полковник 23.10.2026: «Can…» вместо сообщения).
    assert scrub("Can't find variable: foo") == "Can't find variable: foo"
    assert scrub("Can't read 'Иванов'") == "Can't read …"


def test_long_silent_entries_give_way_when_the_summary_is_full():
    """Полковник 23.10.2026: десяток адресов по бюджету занимал все места навсегда, и
    настоящие ошибки после выкладки уходили в «<overflow>» до перезапуска."""
    for i in range(ERROR_LIMIT):
        metrics.ingest({"platform": "web", "errors": [{"name": f"Old{chr(65 + i % 26)}{i}"}]},
                       ip=f"10.1.{i // 200}.{i % 200}")
    for row in metrics._errors.values():
        row["last_unix"] -= 2 * 24 * 3600
    metrics.ingest({"platform": "android", "errors": [{"name": "TypeError", "message": "свежая"}]},
                   ip="198.51.100.9")
    #По самой таблице: сводка отдаёт 50 самых частых, а у всех здесь по одному.
    names = {k[2] for k in metrics._errors}
    assert "TypeError" in names and "<overflow>" not in names


def test_recent_entries_are_not_evicted():
    for i in range(ERROR_LIMIT):
        metrics.ingest({"platform": "web", "errors": [{"name": f"New{chr(65 + i % 26)}{i}"}]},
                       ip=f"10.2.{i // 200}.{i % 200}")
    metrics.ingest({"platform": "android", "errors": [{"name": "TypeError"}]}, ip="198.51.100.9")
    names = {k[2] for k in metrics._errors}
    assert "<overflow>" in names and "TypeError" not in names


def test_flood_of_distinct_errors_keeps_memory_bounded(client):
    #С разных адресов: бюджет одного адреса проверяет отдельный тест ниже.
    for i in range(ERROR_LIMIT + 50):
        metrics.ingest({"platform": "web", "version": "1",
                        "errors": [{"name": f"E{chr(65 + i % 26)}{i}", "message": "m"}]},
                       ip=f"10.0.{i // 200}.{i % 200}")
    snap = metrics.snapshot()
    assert snap["error_kinds"] <= ERROR_LIMIT + 1
    assert any(r["name"] == "<overflow>" and r["count"] == 50 for r in snap["errors"])


def test_one_address_cannot_take_every_place_in_the_summary():
    """Ревью 23.10.2026: аноним занимал все 200 мест выдуманными ошибками, и настоящие
    после выкладки уходили в безымянный «<overflow>» без записи в журнал."""
    for i in range(client_metrics.NEW_KINDS_PER_IP + 10):
        metrics.ingest({"platform": "web", "version": "1",
                        "errors": [{"name": f"Fake{chr(65 + i % 26)}{i}", "message": "m"}]},
                       ip="203.0.113.7")
    metrics.ingest({"platform": "android", "version": "1",
                    "errors": [{"name": "TypeError", "message": "настоящая"}]}, ip="198.51.100.1")
    snap = metrics.snapshot()
    names = {r["name"] for r in snap["errors"]}
    assert "TypeError" in names
    assert sum(1 for n in names if n.startswith("Fake")) == client_metrics.NEW_KINDS_PER_IP
    assert any(r["name"] == "<overflow>" and r["count"] == 10 for r in snap["errors"])


def test_known_error_still_counts_after_the_budget_is_spent():
    for i in range(client_metrics.NEW_KINDS_PER_IP):
        metrics.ingest({"platform": "web", "errors": [{"name": f"K{chr(65 + i)}"}]}, ip="a")
    metrics.ingest({"platform": "web", "errors": [{"name": "KA"}]}, ip="a")
    row = [r for r in metrics.snapshot()["errors"] if r["name"] == "KA"][0]
    assert row["count"] == 2


def test_long_message_without_spaces_is_cleaned_fast():
    """Ревью 23.10.2026: `\\S+@\\S+` на 16 КБ «aaaa…» шёл 0,3 с, а ручка — `async def`
    на единственном процессе: десяток таких отчётов держал весь сервер."""
    import time
    t = time.perf_counter()
    for _ in range(10):
        scrub("a" * 16_000)
    assert time.perf_counter() - t < 0.2


def test_quote_cut_by_the_limit_does_not_leak_the_name():
    text = "x" * 150 + " 'Иванов Пётр " + "y" * 800 + "'"
    assert "Иванов" not in scrub(text)


def test_deep_json_and_infinite_number_do_not_crash_the_open_endpoint(client):
    """Полковник 23.10.2026: RecursionError и OverflowError давали 500, а каждый 500 — запись
    в общем журнале событий, которым аноним вытеснял записи защиты."""
    from app import events
    events.reset()
    deep = client.post("/app/client-report", content=b"[" * 5000 + b"]" * 5000)
    assert deep.status_code == 400
    r = _report(client, {"platform": "web", "startup": {"ms": float("inf")}})
    assert r.status_code == 204
    r = client.post("/app/client-report", content=b'{"startup": {"ms": 1e999}}')
    assert r.status_code == 204
    assert metrics.snapshot()["startup"] == {}
    assert not [e for e in events.recent()["events"] if e["kind"] == "server_error"]


def test_router_templates_with_brackets_are_kept():
    metrics.ingest({"platform": "web", "errors": [{"name": "E", "route": "/:pathMatch(.*)*"}]})
    assert metrics.snapshot()["errors"][0]["route"] == "/:pathMatch(.*)*"


def test_one_report_carries_at_most_ten_errors():
    metrics.ingest({"platform": "web", "version": "1",
                    "errors": [{"name": f"E{chr(65 + i)}", "message": "m"} for i in range(25)]})
    assert metrics.snapshot()["error_kinds"] == client_metrics.ERRORS_PER_REPORT


def test_oversized_body_is_refused_without_reading_it_all(client):
    big = {"platform": "web", "errors": [{"message": "x" * 40_000}]}
    assert _report(client, big).status_code == 413
    assert metrics.snapshot()["error_kinds"] == 0


def test_garbage_is_refused_or_ignored(client):
    assert client.post("/app/client-report", content=b"not json").status_code == 400
    assert _report(client, ["list"]).status_code == 204
    assert _report(client, {"platform": "<script>", "errors": "x", "startup": {"ms": "abc"}}).status_code == 204
    snap = metrics.snapshot()
    assert snap["error_kinds"] == 0 and snap["startup"] == {}


def test_startup_percentiles_slow_share_and_weak_devices():
    for ms, mem in [(800, 8), (900, 8), (1000, 8), (4000, 2), (5000, 2), (999_999, 2), (0, 2)]:
        metrics.ingest({"platform": "android", "version": "1", "startup": {"ms": ms, "mem": mem}})
    s = metrics.snapshot()["startup"]["android"]
    #999 999 и 0 — мусор, не замер.
    assert s["n"] == 5
    assert s["p50_ms"] == 1000 and s["p95_ms"] == 5000
    assert s["slow_share"] == 0.4
    lo, hi = s["slow_share_ci"]
    assert lo < 0.4 < hi
    assert s["weak_devices"] == {"n": 2, "p75_ms": 5000}


def test_first_occurrence_goes_to_the_event_journal_once():
    from app import events
    events.reset()
    for _ in range(3):
        metrics.ingest({"platform": "android", "version": "1",
                        "errors": [{"name": "TypeError", "message": "boom", "route": "/student"}]})
    found = [e for e in events.recent()["events"] if e["kind"] == "client-error"]
    assert len(found) == 1
    assert "android 1 /student: TypeError: boom" in found[0]["message"]
