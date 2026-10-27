"""Ошибки интерфейса и время старта, которые присылают сами клиенты: сайт, программа, телефон.

Зачем (разбор мобильной версии 23.10.2026). Необработанная ошибка Vue на телефоне студента
уходила в `console.error` и дальше никуда: ни доли сбоев, ни времени старта мы не знали, а
проверяли приложение на флагмане. Иностранный сервис сбора сбоев не берём (п. 5.6.1
политики ВСГУТУ, docs/security/SUBPROCESSORS.md) — копим у себя, как `request_metrics`
(ADR-0007).

Хранится только то, по чему ищут дефект, и ничего о человеке:
• ошибка — тип, сообщение без строк в кавычках, чисел и почтовых адресов, первый кадр стека
  нашего бандла, шаблон маршрута (`/teacher/journal`, без параметров и запроса), платформа,
  версия сборки;
• старт — миллисекунды до первого экрана, платформа, версия, память и ядра устройства в
  том огрублённом виде, в каком их отдаёт браузер.
Ни логина, ни адреса, ни текста страницы. Сообщение чистит и клиент, и сервер: ручка
открыта до входа (ошибка на экране входа — тоже ошибка), и верить присланному нельзя.

Память ограничена при любом потоке запросов: не больше ERROR_LIMIT разных ошибок и
STARTUP_SAMPLES замеров на платформу. Снимок — с запуска процесса, как у `request_metrics`;
его видит админ в разделе «Сервер».

Сводка — подсказка, а не доказательство: ручка открыта, и прислать можно что угодно.
Потолок защищает память, а бюджет новых видов ошибок на один адрес (NEW_KINDS_PER_IP в
час) не даёт одному клиенту занять все места и спрятать настоящие ошибки в «<overflow>»
(ревью 23.10.2026). Колледж выходит в сеть через один адрес, поэтому бюджет щедрый:
настоящих новых видов ошибок за час бывает единицы.
"""
import re
from collections import deque
from math import ceil
from threading import Lock
from time import time

from .events import one_line, record

ERROR_LIMIT = 200
STARTUP_SAMPLES = 512
ERRORS_PER_REPORT = 10
NEW_KINDS_PER_IP = 20
_BUDGET_WINDOW_S = 3600
_BUDGET_IPS = 5000
#Запись, которую не присылали дольше этого, уступает место новой, когда мест нет: иначе
#десяток адресов по бюджету занимал бы сводку до перезапуска (Полковник 23.10.2026).
_STALE_S = 24 * 3600
PLATFORMS = ("android", "web", "desktop")
#Старт дольше этого человек видит как «приложение зависло»: порог Android vitals для
#холодного старта — 5 с, но это до первого кадра, а мы меряем до готового экрана.
SLOW_START_MS = 3000

_TEXT_MAX = 160
#Апостроф внутри слова («Can't find variable») — не кавычка: иначе всё после него
#пропадало, и разные ошибки сливались в одну (Полковник 23.10.2026). Граница слова —
#явным классом, а не \w: в JS \w не знает кириллицы, а правило одно с клиентом.
_NOT_AFTER_WORD = r"(?<![A-Za-zА-Яа-яЁё0-9_])"
_QUOTED = re.compile(_NOT_AFTER_WORD + r"'[^']*'|\"[^\"]*\"|`[^`]*`|«[^»]*»")
#Кавычка, закрытие которой отрезала обрезка: всё после неё — тоже возможные данные.
_UNCLOSED = re.compile(_NOT_AFTER_WORD + r"['\"`«][^'\"`»]*$")
_EMAIL = re.compile(r"\S+@\S+")
_NUMBER = re.compile(r"\d{2,}")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
#Шаблон маршрута Vue Router: `/messages/:id`, `/:pathMatch(.*)*`.
_ROUTE = re.compile(r"^/[A-Za-z0-9/_:\-().*]{0,79}$")
_VERSION = re.compile(r"^[0-9A-Za-z.+\-]{1,32}$")
_FRAME = re.compile(r"^[\w./\-]{1,100}:\d{1,7}:\d{1,7}$")


def scrub(text) -> str:
    """Сообщение ошибки без того, что может оказаться данными человека.

    Строки в кавычках, почта и числа заменяются: «Cannot read properties of undefined
    (reading 'Иванов')» становится «Cannot read properties of undefined (reading …)».
    Одной строкой — сообщение уходит и в журнал событий (§4.37).

    Сначала обрезка, потом регулярки: `\\S+@\\S+` на длинной строке без пробелов и без «@»
    работает квадратично, и 16 КБ «aaaa…» держали цикл событий 0,3 с на одно сообщение
    (ревью 23.10.2026)."""
    s = one_line(text)[:_TEXT_MAX * 4]
    s = _QUOTED.sub("…", s)
    s = _UNCLOSED.sub("…", s)
    s = _EMAIL.sub("…", s)
    s = _NUMBER.sub("N", s)
    return s[:_TEXT_MAX]


def _pick(value, pattern, default):
    value = str(value or "")
    return value if pattern.match(value) else default


def _platform(value) -> str:
    return value if value in PLATFORMS else "other"


def _percentile(samples, p):
    return samples[ceil(len(samples) * p / 100) - 1] if samples else None


class ClientMetrics:
    def __init__(self):
        self._lock = Lock()
        self._errors = {}
        self._starts = {}
        self._budget = {}
        self._started = time()

    def ingest(self, data, ip: str = "") -> None:
        """Принять отчёт клиента. Кривые поля не роняют приём, а заменяются заглушкой.

        `ip` нужен только бюджету новых видов ошибок и в сводку не попадает."""
        if not isinstance(data, dict):
            return
        platform = _platform(data.get("platform"))
        version = _pick(data.get("version"), _VERSION, "?")
        errors = data.get("errors")
        if isinstance(errors, list):
            for e in errors[:ERRORS_PER_REPORT]:
                if isinstance(e, dict):
                    self._add_error(platform, version, e, ip)
        start = data.get("startup")
        if isinstance(start, dict):
            self._add_start(platform, version, start)

    def _spend_new_kind(self, ip, now) -> bool:
        """Может ли адрес завести ещё один вид ошибки в этом часу. Зовётся под замком."""
        if len(self._budget) >= _BUDGET_IPS:
            self._budget.clear()
        start, used = self._budget.get(ip, (now, 0))
        if now - start >= _BUDGET_WINDOW_S:
            start, used = now, 0
        ok = used < NEW_KINDS_PER_IP
        self._budget[ip] = (start, used + int(ok))
        return ok

    def _evict_stale(self, now) -> None:
        """Освободить место давно молчащей записью. Зовётся под замком."""
        old = min((k for k in self._errors if k[2] != "<overflow>"),
                  key=lambda k: self._errors[k]["last_unix"], default=None)
        if old is not None and now - self._errors[old]["last_unix"] > _STALE_S:
            del self._errors[old]

    def _add_error(self, platform, version, e, ip=""):
        key = (platform, version, _pick(e.get("name"), _NAME, "Error"), scrub(e.get("message")),
               _pick(e.get("frame"), _FRAME, ""), _pick(e.get("route"), _ROUTE, "?"))
        now = time()
        with self._lock:
            if key not in self._errors and len(self._errors) >= ERROR_LIMIT:
                self._evict_stale(now)
            if key not in self._errors and (len(self._errors) >= ERROR_LIMIT
                                            or not self._spend_new_kind(ip, now)):
                key = (platform, "?", "<overflow>", "", "", "?")
            row = self._errors.get(key)
            new = row is None
            if new:
                row = self._errors[key] = {"count": 0, "first_unix": now}
            row["count"] += 1
            row["last_unix"] = now
        if new and key[2] != "<overflow>":
            #Первое появление — в журнал событий, чтобы новая ошибка после выкладки была
            #видна сразу, а не только в сводке. Повторы журнал не засоряют.
            record("warn", "client-error",
                   f"{platform} {version} {key[5]}: {key[2]}: {key[3]} @ {key[4]}")

    def _add_start(self, platform, version, s):
        try:
            ms = int(s.get("ms"))
        except (TypeError, ValueError, OverflowError):
            #OverflowError — `1e999` разбирается в бесконечность, и int() на ней падает.
            return
        if not 0 < ms <= 120_000:
            return
        mem = s.get("mem")
        mem = mem if isinstance(mem, (int, float)) and 0 < mem <= 64 else None
        with self._lock:
            self._starts.setdefault(platform, deque(maxlen=STARTUP_SAMPLES)).append(
                (ms, mem, version))

    def snapshot(self) -> dict:
        import estimators
        with self._lock:
            errors = sorted(
                ({"platform": k[0], "version": k[1], "name": k[2], "message": k[3],
                  "frame": k[4], "route": k[5], **v} for k, v in self._errors.items()),
                key=lambda r: -r["count"])
            starts = {p: list(d) for p, d in self._starts.items()}
        startup = {}
        for platform, rows in sorted(starts.items()):
            ms = sorted(r[0] for r in rows)
            slow = sum(1 for m in ms if m >= SLOW_START_MS)
            lo, hi = estimators.wilson_interval(slow, len(ms))
            #Слабое железо отдельно: на нём и видна разница, которую флагман прячет.
            weak = sorted(r[0] for r in rows if r[1] is not None and r[1] <= 4)
            startup[platform] = {
                "n": len(ms), **{f"p{p}_ms": _percentile(ms, p) for p in (50, 75, 95)},
                "slow_ms": SLOW_START_MS, "slow_share": round(slow / len(ms), 4) if ms else None,
                "slow_share_ci": [round(lo, 4), round(hi, 4)] if ms else None,
                "weak_devices": {"n": len(weak), "p75_ms": _percentile(weak, 75)},
            }
        return {"scope": "process", "started_at_unix": self._started,
                "error_kinds": len(errors), "errors": errors[:50], "startup": startup}

    def reset(self) -> None:
        with self._lock:
            self._errors.clear()
            self._starts.clear()
            self._budget.clear()


metrics = ClientMetrics()
