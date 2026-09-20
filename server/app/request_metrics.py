"""Ограниченная статистика запросов без тел, адресов и параметров URL.

Снимок относится к одному процессу с момента запуска. Перцентили считаются по
последним SAMPLE_LIMIT запросам каждого маршрута, а счётчики — за весь запуск.
Это диагностика приложения, не измерение TLS и не замена нагрузочному стенду.
"""
from collections import deque
from math import ceil
from threading import Lock
from time import perf_counter, time
from uuid import uuid4


SAMPLE_LIMIT = 256
ROUTE_LIMIT = 512


class RequestMetrics:
    def __init__(self):
        self._lock = Lock()
        self._routes = {}
        self._active = 0
        self._started = time()

    def enter(self):
        with self._lock:
            self._active += 1

    def leave(self, route, method, status, duration, size, failed):
        # Метод приходит от клиента: произвольные методы не плодят новые корзины.
        method = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER"
        with self._lock:
            self._active -= 1
            key = (route, method)
            if key not in self._routes and len(self._routes) >= ROUTE_LIMIT:
                key = ("<overflow>", "OTHER")
            row = self._routes.setdefault(key, {
                "count": 0, "errors": 0, "response_bytes": 0,
                "duration_sum_ms": 0.0, "samples": deque(maxlen=SAMPLE_LIMIT),
                "statuses": {},
            })
            milliseconds = duration * 1000
            row["count"] += 1
            row["errors"] += int(failed or status >= 500)
            row["response_bytes"] += size
            row["duration_sum_ms"] += milliseconds
            row["samples"].append(milliseconds)
            group = str(status // 100) + "xx"
            row["statuses"][group] = row["statuses"].get(group, 0) + 1

    def snapshot(self):
        with self._lock:
            rows = []
            for (route, method), row in sorted(self._routes.items()):
                samples = sorted(row["samples"])
                rows.append({
                    "route": route, "method": method,
                    **{k: v for k, v in row.items() if k not in {"samples", "statuses"}},
                    "statuses": dict(row["statuses"]), "sample_count": len(samples),
                    **{f"p{p}_ms": samples[ceil(len(samples) * p / 100) - 1]
                       for p in (50, 95, 99)},
                })
            return {"scope": "process", "started_at_unix": self._started,
                    "active_requests": self._active, "sample_limit": SAMPLE_LIMIT,
                    "routes": rows}


metrics = RequestMetrics()


class RequestMetricsMiddleware:
    """ASGI-обёртка не буферизует загрузки и считает время до конца ответа.

Идентификатор генерируем сами: присланная клиентом строка может содержать ПДн.
Маршрут берём после роутинга; для раннего отказа сохраняем фиксированную метку.
"""
    def __init__(self, app, collector=None):
        self.app = app
        self.collector = collector if collector is not None else metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status, size, failed = 500, 0, False
        self.collector.enter()

        async def measured_send(message):
            nonlocal status, size
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = [
                    (k, v) for k, v in message.get("headers", [])
                    if k.lower() != b"x-request-id"
                ] + [(b"x-request-id", request_id.encode("ascii"))]
            elif message["type"] == "http.response.body":
                size += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        except BaseException:
            failed = True
            raise
        finally:
            route = getattr(scope.get("route"), "path", "<unmatched>")
            self.collector.leave(route, scope.get("method", "OTHER"), status,
                                 perf_counter() - started, size, failed)
