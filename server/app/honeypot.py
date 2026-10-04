"""Приманки: ПОДРОБНОСТИ о том, кто стучался, — для раздела «Приманки» и вечерней сводки.

`canary.py` решает, ЧТО считать приманкой, и пишет факт в бессрочный журнал
безопасности (только отпечаток адреса). Этот модуль отвечает на вопрос «кто это был»:
адрес, страна и провайдер, каким инструментом, с какими заголовками, что пробовал после
бана. Требование Ярослава 04.10.2026 — «всю возможную инфу о злоумышленнике».

━━ ГРАНИЦА ПДн, КОТОРУЮ НЕЛЬЗЯ ПЕРЕСТУПАТЬ ━━
🔒 Сырой адрес — персональные данные, когда его можно связать с человеком. Поэтому:
  • в бессрочный `audit_events` он по-прежнему НЕ попадает (требование 05.09.2026 в силе);
  • подробности лежат в `honeypot_hits` СО СРОКОМ (`retention.purge_honeypot`, 90 дней);
  • страна и провайдер — из ЛОКАЛЬНОЙ базы (`ipgeo`), адрес никуда не отправляется;
  • пароль, cookie и `Authorization` не сохраняются никогда (`safe_headers`).
  Основание — п. 7 ч. 1 ст. 6 152-ФЗ (защита законных интересов оператора), описано в
  `web/public/privacy.html` §9.1.

━━ ПОЧЕМУ СНИМОК ЗАПРОСА ОТДЕЛЁН ОТ ЗАПИСИ ━━
⚠️ `snapshot` зовётся в цикле событий (middleware объявлен `async def`) и обязан быть
дешёвым: только чтение заголовков. Всё, что трогает диск — база, поиск страны, — живёт в
`record` и идёт через пул потоков. Одно ядро и один процесс: блокирующий вызов в цикле
событий останавливает журнал всему колледжу (инвариант, купленный дефектом `vector_stt`).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("gradebook.honeypot")

#Сколько живут подробности. Не «вечно» — это бессрочное хранение ПДн; не неделю — атаку
#часто разбирают позже, чем она случилась (тот же довод, что у бессрочного журнала, но
#здесь ценой ограниченного срока). Меняется окружением, как остальные сроки `retention`.
HONEYPOT_DAYS = int(os.environ.get("GRADEBOOK_HONEYPOT_KEEP_DAYS", "90"))

#━━ ЧТО НЕ СОХРАНЯЕМ НИКОГДА ━━
#Секреты: к приманке законный человек не приходит, но заголовок мог унести чужой токен,
#а `Authorization` у honeytoken-входа может нести настоящие учётные данные из дампа.
_SECRET_HEADERS = {"cookie", "authorization", "proxy-authorization", "x-api-key",
                   "x-auth-token", "x-csrf-token"}
#Что добавил НАШ прокси, а не клиент. В отпечаток инструмента не входит (одинаково у
#всех), из показа убираем только дубль адреса — `X-Forwarded-For` оставляем: левая его
#часть пишется клиентом, и подделанный XFF — признак намерения обойти ограничители.
_PROXY_HEADERS = {"x-real-ip", "x-forwarded-proto", "x-forwarded-host", "via",
                  "x-forwarded-for", "host", "content-length", "connection"}
_MAX_HEADERS = 40
_MAX_VALUE = 300

#━━ ИНСТРУМЕНТЫ ━━
#Порядок значим: проверяется сверху вниз, первое совпадение выигрывает. Узкие признаки —
#раньше широких («dirbuster» раньше «dirb», конкретные боты раньше слова «bot»).
_TOOLS = (
    #сканеры уязвимостей и перебор каталогов
    ("sqlmap", "sqlmap", "scanner"), ("nikto", "Nikto", "scanner"),
    ("nuclei", "Nuclei", "scanner"), ("wpscan", "WPScan", "scanner"),
    ("nmap", "Nmap", "scanner"), ("masscan", "masscan", "scanner"),
    ("zgrab", "ZGrab", "scanner"), ("zmap", "ZMap", "scanner"),
    ("gobuster", "Gobuster", "scanner"), ("fuzz faster u fool", "ffuf", "scanner"),
    ("ffuf", "ffuf", "scanner"), ("feroxbuster", "feroxbuster", "scanner"),
    ("dirbuster", "DirBuster", "scanner"), ("wfuzz", "wfuzz", "scanner"),
    ("acunetix", "Acunetix", "scanner"), ("nessus", "Nessus", "scanner"),
    ("openvas", "OpenVAS", "scanner"), ("qualys", "Qualys", "scanner"),
    ("burp", "Burp Suite", "scanner"), ("jaeles", "Jaeles", "scanner"),
    ("l9explore", "LeakIX", "scanner"), ("leakix", "LeakIX", "scanner"),
    ("censysinspect", "Censys", "scanner"), ("expanse", "Palo Alto Expanse", "scanner"),
    ("internet-measurement", "InternetMeasurement", "scanner"),
    ("internetmeasurement", "InternetMeasurement", "scanner"),
    ("gitfinder", "GitFinder", "scanner"), ("netcraft", "Netcraft", "scanner"),
    ("shodan", "Shodan", "scanner"), ("binaryedge", "BinaryEdge", "scanner"),
    ("criminalip", "Criminal IP", "scanner"), ("onyphe", "Onyphe", "scanner"),
    #скрипты и библиотеки — человек за ними есть, браузера нет
    ("curl/", "curl", "script"), ("libcurl", "libcurl", "script"),
    ("wget/", "Wget", "script"), ("python-requests", "python-requests", "script"),
    ("python-httpx", "python-httpx", "script"), ("python-urllib", "Python urllib", "script"),
    ("aiohttp", "aiohttp", "script"), ("go-http-client", "Go http-client", "script"),
    ("okhttp", "OkHttp", "script"), ("java/", "Java", "script"),
    ("libwww-perl", "Perl LWP", "script"), ("node-fetch", "node-fetch", "script"),
    ("axios/", "axios", "script"), ("undici", "Node undici", "script"),
    ("postmanruntime", "Postman", "script"), ("apache-httpclient", "Apache HttpClient", "script"),
    ("scrapy", "Scrapy", "script"), ("headlesschrome", "Headless Chrome", "script"),
    ("phantomjs", "PhantomJS", "script"), ("puppeteer", "Puppeteer", "script"),
    ("playwright", "Playwright", "script"), ("selenium", "Selenium", "script"),
    ("ruby", "Ruby", "script"),
    #поисковые и прочие роботы
    ("googlebot", "Googlebot", "bot"), ("bingbot", "Bingbot", "bot"),
    ("yandexbot", "YandexBot", "bot"), ("ahrefsbot", "AhrefsBot", "bot"),
    ("semrushbot", "SemrushBot", "bot"), ("mj12bot", "MJ12bot", "bot"),
    ("dotbot", "DotBot", "bot"), ("petalbot", "PetalBot", "bot"),
    ("baiduspider", "Baiduspider", "bot"), ("applebot", "Applebot", "bot"),
    ("duckduckbot", "DuckDuckBot", "bot"), ("gptbot", "GPTBot", "bot"),
    ("claudebot", "ClaudeBot", "bot"), ("bytespider", "Bytespider", "bot"),
    ("facebookexternalhit", "Facebook", "bot"), ("telegrambot", "TelegramBot", "bot"),
    #Общие признаки робота — УЗКИЕ: голое «bot» совпало бы с телефонами Cubot.
    ("bot/", "робот", "bot"), ("bot;", "робот", "bot"), ("spider", "робот", "bot"),
    ("crawler", "робот", "bot"), ("+http", "робот", "bot"),
    #наше же приложение — на приманку оно не пойдёт, но различать надо
    ("capacitorupdater", "приложение GradeBookAI", "ours"),
)

_BROWSERS = (
    (re.compile(r"edg(?:a|e|ios)?/(\d+)"), "Edge"),
    (re.compile(r"opr/(\d+)"), "Opera"),
    (re.compile(r"yabrowser/(\d+)"), "Яндекс Браузер"),
    (re.compile(r"firefox/(\d+)"), "Firefox"),
    (re.compile(r"(?:chrome|crios)/(\d+)"), "Chrome"),
    (re.compile(r"version/(\d+)[\d.]*\s.*safari/"), "Safari"),
)
#Современные версии на 2026 год. Сильно старая версия в «браузерном» UA — излюбленная
#маскировка сканеров (Chrome/81 в 2026 году у живого человека не бывает).
_STALE_MAJOR = {"Chrome": 110, "Edge": 110, "Firefox": 110, "Opera": 95, "Safari": 15}

_OS = (
    (re.compile(r"windows nt 10\.0"), "Windows 10/11"),
    (re.compile(r"windows nt 6\.3"), "Windows 8.1"),
    (re.compile(r"windows nt 6\.1"), "Windows 7"),
    (re.compile(r"windows"), "Windows"),
    (re.compile(r"android (\d+)"), "Android {}"),
    (re.compile(r"iphone os (\d+)"), "iOS {}"),
    (re.compile(r"ipad"), "iPadOS"),
    (re.compile(r"mac os x"), "macOS"),
    (re.compile(r"cros"), "ChromeOS"),
    (re.compile(r"linux"), "Linux"),
)


def classify(ua: str, headers: dict | None = None) -> dict:
    """{tool, tool_kind, browser, os_name, automated: [причины]} по User-Agent и заголовкам.

    ⚠️ «Браузер» в User-Agent ничего не доказывает: строку пишет клиент. Поэтому рядом
    с названием идут ПРИЗНАКИ АВТОМАТИКИ — настоящий браузер шлёт `Accept-Language` и
    `Sec-Fetch-*`, а сканер, подделавший строку Chrome, обычно забывает про них."""
    headers = headers or {}
    low = (ua or "").strip().lower()
    out = {"tool": "", "tool_kind": "", "browser": "", "os_name": "", "automated": []}
    if not low:
        out.update(tool="без User-Agent", tool_kind="empty")
        out["automated"].append("нет User-Agent")
        return out
    for needle, name, kind in _TOOLS:
        if needle in low:
            out.update(tool=name, tool_kind=kind)
            break
    for rx, name in _BROWSERS:
        m = rx.search(low)
        if m:
            out["browser"] = "%s %s" % (name, m.group(1))
            if not out["tool"]:
                out.update(tool="браузер %s" % name, tool_kind="browser")
            major = int(m.group(1))
            if major < _STALE_MAJOR.get(name, 0):
                out["automated"].append("устаревший %s %d — типичная маскировка сканера"
                                        % (name, major))
            break
    for rx, name in _OS:
        m = rx.search(low)
        if m:
            out["os_name"] = name.format(*m.groups()) if m.groups() else name
            break
    if not out["tool"]:
        out.update(tool=(ua or "")[:40], tool_kind="other")
    if out["tool_kind"] in ("scanner", "script"):
        out["automated"].append("инструмент: %s" % out["tool"])
    if out["tool_kind"] == "browser":
        if not headers.get("accept-language"):
            out["automated"].append("браузерный User-Agent без Accept-Language")
        if not any(k.startswith("sec-fetch-") for k in headers):
            out["automated"].append("нет заголовков Sec-Fetch-* (настоящий браузер их шлёт)")
    host = (headers.get("host") or "").split(":")[0].strip("[]")
    try:
        ipaddress.ip_address(host)
        out["automated"].append("обращение по IP, а не по имени сайта — массовый обход")
    except ValueError:
        pass
    return out


def safe_headers(items) -> dict:
    """Заголовки для показа: без секретов, с ограничением длины и числа.

    Cookie не сохраняем, но ОТМЕЧАЕМ её наличие: сканер с cookie — это уже не холодный
    обход, а кто-то, кто был на сайте раньше."""
    out: dict = {}
    for k, v in items:
        k = (k or "").lower()
        if not k or k == "x-real-ip":
            continue
        if k in _SECRET_HEADERS:
            out[k] = "<есть, %d байт — не сохраняется>" % len(v or "")
            continue
        if len(out) >= _MAX_HEADERS:
            break
        out[k] = (v or "")[:_MAX_VALUE]
    return out


def client_fingerprint(headers: dict) -> str:
    """Отпечаток ИНСТРУМЕНТА (не адреса): одинаков у одного сканера с разных машин.

    Порядок заголовков не берём: наш прокси (Caddy, Go) пересобирает их в другом порядке,
    и отпечаток мерил бы прокси, а не клиента. Берём набор имён и значения, которые
    задаёт сам инструмент."""
    names = sorted(k for k in headers if k not in _PROXY_HEADERS)
    parts = [headers.get(k, "") for k in ("user-agent", "accept", "accept-language",
                                          "accept-encoding")]
    raw = "|".join(parts) + "|" + ",".join(names)
    return "c:" + hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:12]


def snapshot(request, *, ip: str, kind: str = "path", banned: bool = False,
             trusted: bool = False, login: str = "") -> dict:
    """Всё о запросе, что можно взять без диска. Дёшево — зовётся в цикле событий."""
    try:
        items = list(request.headers.items())
    except Exception:      # noqa: BLE001
        items = []
    hdrs = safe_headers(items)
    ua = hdrs.get("user-agent", "")
    info = classify(ua, hdrs)
    return {
        "kind": kind, "ip": (ip or "")[:64], "method": (request.method or "")[:10],
        "path": (request.url.path or "")[:300], "query": (request.url.query or "")[:500],
        "host": hdrs.get("host", "")[:120], "user_agent": ua[:400],
        "tool": info["tool"][:60], "tool_kind": info["tool_kind"],
        "browser": info["browser"][:60], "os_name": info["os_name"][:60],
        "automated": "; ".join(info["automated"])[:500],
        "client_fp": client_fingerprint(hdrs), "headers": hdrs,
        "banned": bool(banned), "trusted": bool(trusted), "login": (login or "")[:80],
    }


def record(snap: dict) -> None:
    """Записать срабатывание: факт — в бессрочный журнал, подробности — в таблицу со сроком.

    ⚠️ СИНХРОННАЯ: звать через `run_in_threadpool` из `async def` (или прямо из обычной
    `def`-ручки — FastAPI уже увёл её в пул). Две записи независимы: сбой одной не имеет
    права отменить другую — журнал безопасности важнее подробностей."""
    from . import canary
    honey = snap.get("kind") == "honeytoken"
    try:
        canary.record_hit(snap.get("method", ""), snap.get("path", ""), snap.get("ip", ""),
                          action="canary.honeytoken" if honey else "canary.hit",
                          level="error" if honey else "warn")
    except Exception:      # noqa: BLE001
        log.exception("[honeypot] срабатывание не записалось в журнал безопасности")
    try:
        _store(snap)
    except Exception:      # noqa: BLE001
        #Детектор, который молча теряет подробности, — тот самый «тихий отказ». Громко.
        log.exception("[honeypot] подробности срабатывания не сохранились")


def _store(snap: dict) -> None:
    from . import canary, ipgeo
    from .db import SessionLocal
    from .models import HoneypotHit
    geo = ipgeo.lookup(snap.get("ip", ""))
    now = time.time()
    db = SessionLocal()
    try:
        db.add(HoneypotHit(
            created_ts=int(now),
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            kind=snap.get("kind", "path"), ip=snap.get("ip", ""),
            fingerprint=canary.ip_fingerprint(snap.get("ip", "")),
            client_fp=snap.get("client_fp", ""), method=snap.get("method", ""),
            path=snap.get("path", ""), query=snap.get("query", ""),
            host=snap.get("host", ""), user_agent=snap.get("user_agent", ""),
            tool=snap.get("tool", ""), tool_kind=snap.get("tool_kind", ""),
            browser=snap.get("browser", ""), os_name=snap.get("os_name", ""),
            automated=snap.get("automated", ""),
            country=geo.get("country", ""), asn=int(geo.get("asn") or 0),
            as_name=geo.get("as_name", ""),
            headers=json.dumps(snap.get("headers") or {}, ensure_ascii=False)[:4000],
            login=snap.get("login", ""), banned=bool(snap.get("banned")),
            trusted=bool(snap.get("trusted"))))
        db.commit()
    finally:
        db.close()


#━━ ЧТО ПРОБОВАЛ ПОСЛЕ БАНА ━━
#Забаненный адрес получает 429 раньше любой проверки, и в журнал больше не попадает —
#а именно эти запросы показывают, ЧТО он искал. Пишем их не в базу (сотни строк на один
#сканер — это лог доступа, а не журнал), а в общее состояние со сроком бана: счётчик и
#несколько последних путей.
#⚠️ `shared_state.update`, а не словарь модуля: при нескольких процессах словарь показал
#бы администратору 1/N картины (тот же класс, что у живой консоли `events`).
_BLK = "hp:blk:"
_BLK_PATHS = 12


def note_blocked(ip: str, method: str, path: str) -> None:
    """Отметить запрос забаненного адреса. Дёшево; ничего не бросает."""
    if not ip:
        return
    from . import canary, shared_state
    entry = "%s %s" % ((method or "")[:8], (path or "")[:120])

    def _bump(cur):
        cur = dict(cur or {})
        cur["n"] = int(cur.get("n") or 0) + 1
        cur["last"] = int(time.time())
        paths = [p for p in (cur.get("paths") or []) if p != entry]
        paths.append(entry)
        cur["paths"] = paths[-_BLK_PATHS:]
        return cur
    try:
        shared_state.update(_BLK + ip, _bump, ttl=canary.BAN_SECONDS)
    except Exception:      # noqa: BLE001 — подробность, а не защита: бан уже сработал
        pass


def blocked_info(ip: str) -> dict:
    from . import shared_state
    try:
        cur = shared_state.get(_BLK + (ip or "")) or {}
    except Exception:      # noqa: BLE001
        cur = {}
    return {"n": int(cur.get("n") or 0), "paths": list(cur.get("paths") or []),
            "last": int(cur.get("last") or 0)}


#━━ ВЫБОРКИ ДЛЯ РАЗДЕЛА И СВОДКИ ━━
def _row(h) -> dict:
    try:
        headers = json.loads(h.headers or "{}")
    except ValueError:
        headers = {}
    return {"id": h.id, "ts": h.ts, "created_ts": h.created_ts, "kind": h.kind,
            "ip": h.ip, "fingerprint": h.fingerprint, "client_fp": h.client_fp,
            "method": h.method, "path": h.path, "query": h.query, "host": h.host,
            "user_agent": h.user_agent, "tool": h.tool, "tool_kind": h.tool_kind,
            "browser": h.browser, "os_name": h.os_name,
            "automated": [x for x in (h.automated or "").split("; ") if x],
            "country": h.country, "asn": h.asn, "as_name": h.as_name,
            "headers": headers, "login": h.login, "banned": bool(h.banned),
            "trusted": bool(h.trusted)}


def _hits_since(db, since_ts: int):
    from .models import HoneypotHit
    return (db.query(HoneypotHit).filter(HoneypotHit.created_ts >= since_ts)
              .order_by(HoneypotHit.created_ts.desc()).all())


def _top(counter: dict, n: int = 10) -> list:
    return sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n]


def _local_day(ts: int, tz_minutes: int) -> str:
    return (datetime.fromtimestamp(ts, timezone.utc)
            + timedelta(minutes=tz_minutes)).strftime("%Y-%m-%d")


def sources_of(rows, *, limit: int = 100) -> list:
    """Источники (по отпечатку адреса): кто, сколько, чем, что пробовал."""
    from . import throttle
    by: dict = {}
    for h in rows:                       #свежие сверху — первая строка источника и есть
        s = by.get(h.fingerprint)        #его последнее появление
        if s is None:
            s = by[h.fingerprint] = {
                "fingerprint": h.fingerprint, "ip": h.ip, "country": h.country,
                "asn": h.asn, "as_name": h.as_name, "tool": h.tool,
                "tool_kind": h.tool_kind, "browser": h.browser, "os_name": h.os_name,
                "client_fp": h.client_fp, "last": h.created_ts, "first": h.created_ts,
                "hits": 0, "paths": [], "kinds": [], "trusted": bool(h.trusted),
                "automated": [x for x in (h.automated or "").split("; ") if x]}
        s["hits"] += 1
        s["first"] = min(s["first"], h.created_ts)
        p = "%s %s" % (h.method, h.path)
        if p not in s["paths"] and len(s["paths"]) < 15:
            s["paths"].append(p)
        if h.kind not in s["kinds"]:
            s["kinds"].append(h.kind)
    out = sorted(by.values(), key=lambda s: -s["last"])[:limit]
    for s in out:
        s["ban_left"] = throttle.seconds_until_unbanned(s["ip"]) if s["ip"] else 0
        s["after_ban"] = blocked_info(s["ip"])
    return out


def summary(db, *, days: int = 30, tz_minutes: int = 480) -> dict:
    """Всё для верхней части раздела: итоги, график по дням, топы и источники."""
    from . import ipgeo
    from .models import AuditEvent, HoneypotHit
    now = int(time.time())
    since = now - days * 86400
    rows = _hits_since(db, since)
    countries, tools, paths, providers, per_day = {}, {}, {}, {}, {}
    for h in rows:
        if h.country:
            countries[h.country] = countries.get(h.country, 0) + 1
        tools[(h.tool, h.tool_kind)] = tools.get((h.tool, h.tool_kind), 0) + 1
        paths[h.path] = paths.get(h.path, 0) + 1
        if h.asn:
            key = (h.asn, h.as_name, h.country)
            providers[key] = providers.get(key, 0) + 1
        d = _local_day(h.created_ts, tz_minutes)
        per_day[d] = per_day.get(d, 0) + 1
    series = []
    for i in range(days - 1, -1, -1):
        d = _local_day(now - i * 86400, tz_minutes)
        series.append({"date": d, "hits": per_day.get(d, 0)})
    sources = sources_of(rows)
    #Журнал безопасности знает о срабатываниях с 06.09.2026, подробности — с 04.10.2026.
    #Показываем оба числа, а не одно: иначе история до подробностей выглядела бы как
    #«атак не было».
    audit_total = (db.query(AuditEvent)
                     .filter(AuditEvent.action.in_(("canary.hit", "canary.honeytoken")),
                             AuditEvent.created_ts >= since).count())
    first = db.query(HoneypotHit.created_ts).order_by(HoneypotHit.created_ts).first()
    return {
        "days": days, "retention_days": HONEYPOT_DAYS,
        "detail_since": int(first[0]) if first else 0,
        "totals": {
            "hits": len(rows), "audit_hits": audit_total,
            "sources": len({h.fingerprint for h in rows}),
            "countries": len(countries),
            "honeytoken": sum(1 for h in rows if h.kind == "honeytoken"),
            "trusted": sum(1 for h in rows if h.trusted),
            "banned_now": sum(1 for s in sources if s["ban_left"] > 0),
            "automated": sum(1 for h in rows if h.automated),
        },
        "series": series,
        "top_countries": [{"country": k, "n": v} for k, v in _top(countries)],
        "top_tools": [{"tool": k[0], "kind": k[1], "n": v} for k, v in _top(tools)],
        "top_paths": [{"path": k, "n": v} for k, v in _top(paths)],
        "top_providers": [{"asn": k[0], "name": k[1], "country": k[2], "n": v}
                          for k, v in _top(providers)],
        "sources": sources,
        "geo": ipgeo.status(),
    }


def list_hits(db, *, days: int = 30, q: str = "", limit: int = 200, offset: int = 0) -> dict:
    """Отдельные срабатывания со всеми полями. Поиск — по адресу, пути, инструменту,
    стране, провайдеру, User-Agent и отпечаткам (в Python: регистронезависимо и по
    кириллице, чего SQLite без ICU не умеет)."""
    rows = _hits_since(db, int(time.time()) - days * 86400)
    needle = (q or "").strip().lower()
    if needle:
        rows = [h for h in rows if needle in " ".join(
            (h.ip, h.path, h.query, h.tool, h.country, h.as_name, h.user_agent,
             h.fingerprint, h.client_fp, h.browser, h.os_name)).lower()]
    total = len(rows)
    page = rows[offset:offset + limit]
    return {"total": total, "hits": [_row(h) for h in page]}


def source(db, fingerprint: str) -> dict:
    """Карточка одного источника: все его срабатывания за срок хранения."""
    from .models import HoneypotHit
    rows = (db.query(HoneypotHit).filter(HoneypotHit.fingerprint == fingerprint)
              .order_by(HoneypotHit.created_ts.desc()).limit(500).all())
    if not rows:
        return {"found": False}
    agg = sources_of(rows, limit=1)[0]
    #Тот же инструмент с других адресов — частый случай облачных сканеров: десяток
    #машин одного заказчика. Показываем, чтобы не разбирать их как десять разных атак.
    siblings = sorted({h.fingerprint for h in db.query(HoneypotHit)
                       .filter(HoneypotHit.client_fp == agg["client_fp"],
                               HoneypotHit.fingerprint != fingerprint).limit(200).all()})
    return {"found": True, "source": agg, "hits": [_row(h) for h in rows],
            "same_tool_sources": siblings[:30]}
