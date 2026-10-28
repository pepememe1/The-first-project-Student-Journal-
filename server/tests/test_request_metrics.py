"""Измеряем живой ASGI-путь и проверяем отсутствие чувствительных данных."""
import asyncio
import json
import re

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.request_metrics import RequestMetrics, RequestMetricsMiddleware, SAMPLE_LIMIT


def make_app():
    collector = RequestMetrics()
    app = FastAPI()
    app.add_middleware(RequestMetricsMiddleware, collector=collector)

    @app.get("/items/{person}")
    def item(person: str):
        return {"person": person}

    @app.get("/stream")
    def stream():
        return StreamingResponse(iter([b"one", b"two"]))

    @app.get("/broken")
    def broken():
        raise RuntimeError("private failure")

    return app, collector


def test_live_requests_use_template_and_server_generated_id():
    app, collector = make_app()
    with TestClient(app) as client:
        response = client.get("/items/private-name?token=private-token",
                              headers={"X-Request-ID": "private-header"})
        second = client.get("/items/another-name")
    assert response.status_code == 200
    assert re.fullmatch("[0-9a-f]{32}", response.headers["x-request-id"])
    assert second.headers["x-request-id"] != response.headers["x-request-id"]
    data = collector.snapshot()
    assert data["active_requests"] == 0
    row = data["routes"][0]
    assert row["route"] == "/items/{person}"
    assert row["count"] == 2
    assert row["response_bytes"] == len(response.content) + len(second.content)
    assert "private" not in json.dumps(data)
    assert "another-name" not in json.dumps(data)


def test_stream_and_exception_are_counted_without_changing_behavior():
    app, collector = make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/stream").content == b"onetwo"
        assert client.get("/broken").status_code == 500
    rows = {row["route"]: row for row in collector.snapshot()["routes"]}
    assert rows["/stream"]["response_bytes"] == 6
    assert rows["/broken"]["errors"] == 1
    assert collector.snapshot()["active_requests"] == 0
    assert "private" not in json.dumps(collector.snapshot())


def test_samples_are_bounded_and_percentiles_use_real_observations():
    collector = RequestMetrics()
    for n in range(SAMPLE_LIMIT * 2):
        collector.enter()
        collector.leave("/sample", "GET", 200, n / 1000, 2, False)
    row = collector.snapshot()["routes"][0]
    assert row["count"] == SAMPLE_LIMIT * 2
    assert row["sample_count"] == SAMPLE_LIMIT
    assert row["p50_ms"] == 383
    assert row["p95_ms"] == 499
    assert row["p99_ms"] == 509


def test_unmatched_paths_and_methods_do_not_create_unbounded_buckets():
    app, collector = make_app()
    with TestClient(app) as client:
        for n in range(20):
            assert client.request(f"CUSTOM{n}", f"/private-{n}").status_code == 404
    rows = collector.snapshot()["routes"]
    assert len(rows) == 1
    assert rows[0]["route"] == "<unmatched>"
    assert rows[0]["method"] == "OTHER"


def test_cancellation_clears_active_counter_and_propagates():
    collector = RequestMetrics()

    async def cancelled(scope, receive, send):
        raise asyncio.CancelledError()

    async def unused():
        pass

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(RequestMetricsMiddleware(cancelled, collector)(
            {"type": "http", "method": "GET"}, unused, unused))
    assert collector.snapshot()["active_requests"] == 0
    assert collector.snapshot()["routes"][0]["errors"] == 1


def test_product_wires_collector_and_protects_snapshot(client):
    from app.request_metrics import metrics
    before = sum(r["count"] for r in metrics.snapshot()["routes"])
    response = client.get("/health")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert sum(r["count"] for r in metrics.snapshot()["routes"]) > before
    assert client.get("/web/admin/server/metrics").status_code == 401


def test_database_time_is_counted_inside_the_request(client):
    """Время SQL внутри HTTP-запроса доезжает до снимка — и из `def`-ручек, которые FastAPI
    уводит в пул потоков (21.10.2026). Без слушателя доля базы была бы нулём, и вопрос «где
    узкое место» решался бы гаданием."""
    from conftest import make_admin
    from app.request_metrics import metrics
    admin = make_admin(client)
    assert client.get("/web/admin/server/metrics", headers=admin).status_code == 200
    row = [r for r in metrics.snapshot()["routes"] if r["route"] == "/web/admin/users"
           or r["route"] == "/auth/bootstrap-admin"]
    assert row and row[0]["db_queries_per_request"] > 0, row
    assert 0 < row[0]["db_share"] <= 1, row
    #Текста запросов в снимке нет — только время и число.
    assert "SELECT" not in str(metrics.snapshot())


# ── Точность и загрузка (исследование 20.10.2026) ─────────────────────────────────────
def test_p99_is_reported_with_its_honest_interval():
    from app.request_metrics import RequestMetrics
    m = RequestMetrics()
    for i in range(256):
        m.enter()
        m.leave("/x", "GET", 200, (i + 1) / 1000, 0, False)
    row = m.snapshot()["routes"][0]
    lo, hi = row["p99_ci_ms"]
    assert lo <= row["p99_ms"] <= hi
    assert hi - lo >= 5, "p99 по 256 замерам — диапазон, а не точка"


def test_startup_cpu_does_not_count_as_load():
    """Живая проверка 21.10.2026: сразу после старта ρ показывала ~100 % — в счёт шёл
    процессор, съеденный миграциями и прогревом ДО первого запроса."""
    from app.request_metrics import RequestMetrics
    m = RequestMetrics()
    m._started -= 10             # «старт службы»: десять секунд…
    m._cpu_started -= 10         # …все на процессоре
    m.enter()
    m.leave("/z", "GET", 200, 0.001, 0, False)
    #Окно в микросекунды — загрузки ещё нет, а не 100 %: на точных часах Linux один проход
    #цикла и был бы «100 %», Windows прятала это шагом часов в 15 мс.
    load = m.snapshot()["load"]
    assert load["cpu_utilization"] is None and load["warn"] is False
    m._started -= 120            # прошло две минуты, процессор почти не трудился
    assert m.snapshot()["load"]["cpu_utilization"] < 0.5


def test_littles_law_and_queue_factor():
    """L = λ·W и множитель 1/(1 − ρ) отдаются в снимке; ρ ограничена [0, 1]."""
    from app.request_metrics import RequestMetrics
    m = RequestMetrics()
    m.enter()                    # отсчёт загрузки начинается с первого запроса
    m.leave("/y", "GET", 200, 0.2, 0, False)
    m._started -= 100            # сто секунд работы
    m._cpu_started -= 80         # из них 80 с процессорного времени
    for _ in range(49):
        m.enter()
        m.leave("/y", "GET", 200, 0.2, 0, False)
    load = m.snapshot()["load"]
    assert abs(load["requests_per_s"] - 0.5) < 0.01
    assert abs(load["mean_in_flight"] - 0.1) < 0.005          # 0.5 запроса/с × 0.2 с
    assert 0.79 < load["cpu_utilization"] <= 0.81
    assert 4.5 < load["queue_factor"] < 5.5                    # 1 / (1 − 0.8) = 5
    assert load["warn"] is True
