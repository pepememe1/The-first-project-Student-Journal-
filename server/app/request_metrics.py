"""Ограниченная статистика запросов без тел, адресов и параметров URL.

Снимок относится к одному процессу с момента запуска. Перцентили считаются по
последним SAMPLE_LIMIT запросам каждого маршрута, а счётчики — за весь запуск.
Это диагностика приложения, не измерение TLS и не замена нагрузочному стенду.

С 20.10.2026 (исследование «Высшая математика в журнале») снимок ещё и говорит, НАСКОЛЬКО
его цифрам можно верить и насколько сервер близок к пределу:
• у p95/p99 — интервал, в котором лежит настоящий квантиль (`estimators.quantile_rank_interval`):
  p99 по 256 замерам — по сути третье сверху значение, и как точное число он врёт;
• закон Литтла (Джон Литтл, 1961): L = λ·W — среднее число запросов в работе равно
  частоте запросов, умноженной на среднее время ответа. Не зависит ни от распределения
  прихода, ни от распределения обслуживания — поэтому годится без допущений;
• загрузка процесса ρ — процессорное время процесса к прошедшему (одно ядро: GIL и ОДИН
  uvicorn), и множитель очереди 1/(1 − ρ) из модели M/M/1 (Агнер Эрланг, 1909; запись
  Дэвида Кендалла, 1953). Смысл — нелинейность: при ρ = 0.8 ожидание в очереди впятеро
  больше чистой работы, при 0.9 — вдесятеро. «90 % загрузки чуть хуже 80 %» — неверно,
  и это числовой ответ на вопрос «когда нужен второй процесс» (PLAN-MULTIWORKER).

С 21.10.2026 — ещё и ВРЕМЯ БАЗЫ внутри запроса (разбор Ярослава: «сначала установить, что
именно является узким местом»). Слушатель SQLAlchemy копит время каждого SQL-запроса в
переменную контекста, которую ставит обёртка запроса; пул потоков FastAPI копирует контекст
вместе со ссылкой на тот же счётчик, поэтому время доезжает и из обычных `def`-ручек. По
маршруту — доля базы во времени ответа и число SQL-запросов на HTTP-запрос: высокая доля
значит «смотреть индексы и запросы», низкая — «время уходит в Python». Ожидание замка
записи SQLite входит в это время (оно случается внутри `execute`). Текст запросов не
хранится — только время и число.
"""
from contextvars import ContextVar
from collections import deque
from math import ceil
from threading import Lock
from time import perf_counter, process_time, time
from uuid import uuid4


SAMPLE_LIMIT = 256
ROUTE_LIMIT = 512
#Загрузка выше этой — предупреждение: дальше задержка растёт не линейно, а как 1/(1 − ρ).
RHO_WARN = 0.7
#Окно короче минуты загрузку не показывает: сразу после первого запроса в окне микросекунды,
#и точные часы Linux дают ~100 % от одного прохода цикла. На Windows это прятал шаг часов
#процесса в 15 мс — тест краснел только в CI (28.10.2026).
RHO_MIN_WINDOW_S = 60

#[мс базы, число SQL-запросов] текущего HTTP-запроса; None — вне запроса (старт, фон).
_db_time: ContextVar = ContextVar("gb_request_db_time", default=None)


def _before_sql(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("gb_sql_started", []).append(perf_counter())


def _after_sql(conn, cursor, statement, parameters, context, executemany):
    stack = conn.info.get("gb_sql_started")
    if not stack:
        return
    elapsed = perf_counter() - stack.pop()
    acc = _db_time.get()
    if acc is not None:
        acc[0] += elapsed * 1000
        acc[1] += 1


def install_sql_timing() -> None:
    """Повесить слушатель на ВСЕ движки (и пересозданные `db.rebind`). Идемпотентно."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    if not event.contains(Engine, "before_cursor_execute", _before_sql):
        event.listen(Engine, "before_cursor_execute", _before_sql)
        event.listen(Engine, "after_cursor_execute", _after_sql)


class RequestMetrics:
    def __init__(self):
        self._lock = Lock()
        self._routes = {}
        self._active = 0
        self._started = time()
        self._cpu_started = process_time()
        #Отсчёт загрузки — с ПЕРВОГО запроса, а не с импорта модуля: старт службы (миграции,
        #индексы, прогрев) съедает секунды процессора, и сразу после выкладки страница
        #«Сервер» показывала бы ядро занятым на 100 % (живая проверка 21.10.2026).
        self._clock_from_first_request = True

    def enter(self):
        with self._lock:
            if self._clock_from_first_request:
                self._clock_from_first_request = False
                self._started, self._cpu_started = time(), process_time()
            self._active += 1

    def leave(self, route, method, status, duration, size, failed, db=None):
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
                "statuses": {}, "db_sum_ms": 0.0, "db_queries": 0,
            })
            milliseconds = duration * 1000
            row["count"] += 1
            row["errors"] += int(failed or status >= 500)
            row["response_bytes"] += size
            row["duration_sum_ms"] += milliseconds
            row["samples"].append(milliseconds)
            if db:
                row["db_sum_ms"] += db[0]
                row["db_queries"] += db[1]
            group = str(status // 100) + "xx"
            row["statuses"][group] = row["statuses"].get(group, 0) + 1

    def snapshot(self):
        #Корневой модуль формул: к моменту снимка его путь уже положил webdata
        #(его импортируют роутеры), поэтому импорт ленивый — на импорте этого модуля
        #`main.py` ещё не знает корня репозитория.
        import estimators
        with self._lock:
            rows = []
            requests, duration_ms, db_ms = 0, 0.0, 0.0
            for (route, method), row in sorted(self._routes.items()):
                samples = sorted(row["samples"])
                requests += row["count"]
                duration_ms += row["duration_sum_ms"]
                db_ms += row["db_sum_ms"]
                ci = {}
                for p in (95, 99):
                    lo, hi = estimators.quantile_rank_interval(len(samples), p / 100)
                    ci[f"p{p}_ci_ms"] = [samples[lo], samples[hi]] if samples else None
                rows.append({
                    "route": route, "method": method,
                    **{k: v for k, v in row.items() if k not in {"samples", "statuses"}},
                    "statuses": dict(row["statuses"]), "sample_count": len(samples),
                    #Доля базы во времени ответа и SQL-запросов на один HTTP-запрос.
                    "db_share": round(row["db_sum_ms"] / row["duration_sum_ms"], 3)
                    if row["duration_sum_ms"] else None,
                    "db_queries_per_request": round(row["db_queries"] / row["count"], 2)
                    if row["count"] else None,
                    **{f"p{p}_ms": samples[ceil(len(samples) * p / 100) - 1]
                       for p in (50, 95, 99)},
                    **ci,
                })
            wall = max(time() - self._started, 1e-9)
            rho = (min(1.0, max(0.0, (process_time() - self._cpu_started) / wall))
                   if wall >= RHO_MIN_WINDOW_S else None)
            arrival = requests / wall
            mean_s = (duration_ms / requests / 1000) if requests else 0.0
            return {"scope": "process", "started_at_unix": self._started,
                    "active_requests": self._active, "sample_limit": SAMPLE_LIMIT,
                    "load": {
                        "requests_per_s": round(arrival, 4),
                        "mean_response_ms": round(mean_s * 1000, 2),
                        #Закон Литтла: сколько запросов в среднем одновременно в работе.
                        "mean_in_flight": round(arrival * mean_s, 4),
                        "cpu_utilization": round(rho, 4) if rho is not None else None,
                        #M/M/1: во сколько раз ожидание длиннее чистой работы при такой загрузке.
                        "queue_factor": round(1 / (1 - rho), 2)
                        if rho is not None and rho < 0.999 else None,
                        "warn": rho is not None and rho > RHO_WARN,
                        "db_share": round(db_ms / duration_ms, 3) if duration_ms else None,
                    },
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
        db = [0.0, 0]
        token = _db_time.set(db)
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
            _db_time.reset(token)
            route = getattr(scope.get("route"), "path", "<unmatched>")
            self.collector.leave(route, scope.get("method", "OTHER"), status,
                                 perf_counter() - started, size, failed, db)
