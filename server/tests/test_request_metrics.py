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
