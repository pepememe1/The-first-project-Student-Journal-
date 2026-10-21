"""Прогноз места и нагрузка процесса на странице «Сервер» (исследование 20.10.2026)."""
import os

from conftest import make_admin

from app import hostinfo


def _snapshots(tmp_path, sizes):
    auto = tmp_path / "auto"
    auto.mkdir()
    day = 86400
    for i, size in enumerate(sizes):
        f = auto / f"gradebook_2026100{i}_000000.db"
        f.write_bytes(b"\0" * size)
        os.utime(f, (1_800_000_000 + i * day, 1_800_000_000 + i * day))
    return str(tmp_path)


def test_forecast_uses_holt_slope_and_counts_the_backups(tmp_path):
    """База растёт на 1000 байт в сутки; с 14 копиями диск уходит на 15 000 в сутки,
    и 150 000 свободных байт — это 10 суток, а не 150."""
    root = _snapshots(tmp_path, [10_000, 11_000, 12_000, 13_000, 14_000])
    fc = hostinfo.db_growth_forecast(root, free_bytes=150_000)
    assert fc["snapshots"] == 5
    assert abs(fc["db_growth_per_day"] - 1000) <= 1
    assert abs(fc["days_left"] - 10) <= 1


def test_forecast_needs_three_snapshots_and_no_growth_means_no_deadline(tmp_path):
    assert hostinfo.db_growth_forecast(_snapshots(tmp_path, [10, 20]), 1000) is None
    other = tmp_path / "flat"
    other.mkdir()
    fc = hostinfo.db_growth_forecast(_snapshots(other, [500, 500, 500]), 1000)
    assert fc["days_left"] is None


def test_metrics_endpoint_finally_returns_the_request_snapshot(client):
    """Обратный ход «обещания без вызывающего»: сборщик собирал с 20.09.2026, а ручка
    снимок не отдавала. Теперь отдаёт — вместе с законом Литтла и загрузкой ρ."""
    admin = make_admin(client)
    body = client.get("/web/admin/server/metrics", headers=admin).json()
    load = body["requests"]["load"]
    assert {"requests_per_s", "mean_in_flight", "cpu_utilization", "queue_factor"} <= set(load)
    assert "forecast" in body
