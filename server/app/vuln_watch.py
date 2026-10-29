"""Сторож уязвимостей боевого сервера: сам находит известные дыры в нашем стеке и ставит исправление.

Зачем (27.10.2026). PHP2Shell атаковали за четыре дня до публикации, а у нас неделю жил
certifi со скомпрометированными центрами сертификации: venv не обновляет никто —
unattended-upgrades ставит только пакеты ОС, а CI проверяет файл зависимостей, а не то,
что на самом деле стоит на бою.

Раз в час (`deploy/vulnwatch/gb-vulnwatch.timer`):
  1. Пакеты Python боевого venv сверяются с OSV (туда сходятся PyPA, GitHub Advisory и
     другие базы). Для дыры с выпущенным исправлением ставится НАИМЕНЬШАЯ исправленная
     версия, затем `pip check`, перезапуск службы и ожидание /health. Не поднялось —
     откат на прежние версии и второй перезапуск.
  2. Пакеты ОС и Caddy: обновления безопасности и Caddy сразу, без перезагрузки (её делает ночной
     прогон в 02:00 по Иркутску). Источники — те же, что ночью: обновления безопасности
     Ubuntu и репозиторий Caddy (`deploy/maintenance/52gradebook-unattended`).
  3. Найденное сверяется со списком CISA KEV: «уже используют в атаках» — первой строкой.
     Дыра нашего стека из этого списка получает вердикт по НАШЕЙ машине уже после
     обновлений (`kev_verdict`): письмо сразу — только если задевает, ждёт перезагрузки или
     проверить не удалось; «не задевает» уходит в вечернюю сводку.
Итог — `state.json`, его читает ночной отчёт (`nightly_report._security`).

Не трогает torch (колесо +cpu с отдельного индекса, только в отчёт) и пакеты без
исправления. Наружу уходят только имена и версии пакетов (docs/security/SUBPROCESSORS.md).
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

OSV_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_QUERY = "https://api.osv.dev/v1/query"
OSV_VULN = "https://api.osv.dev/v1/vulns/"
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
STATE_DIR = os.environ.get("GB_VULNWATCH_DIR", "/var/lib/gb-vulnwatch")
SERVICE = "gradebook"
HEALTH = "http://127.0.0.1:8000/health"
#torch ставится со своего индекса (+cpu) и весит сотни мегабайт: автоматом не трогаем.
HOLD = {"torch"}
KEV_TTL_S = 12 * 3600
HISTORY_MAX = 60


def canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name or "").lower()


def _vkey(v: str):
    """Ключ сравнения версий: PEP 440 через packaging (он есть в любом venv с pip)."""
    try:
        from packaging.version import Version
    except ImportError:      # pragma: no cover — packaging внутри pip есть всегда
        from pip._vendor.packaging.version import Version
    return Version(v)


def _http_json(url: str, payload=None, timeout: int = 30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "GradeBookAI-vulnwatch", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # nosec B310: адреса — константы выше
        return json.loads(r.read().decode("utf-8"))


def installed() -> dict:
    """{имя: версия} пакетов того venv, которым запущен сторож."""
    from importlib import metadata
    out = {}
    for d in metadata.distributions():
        name = d.metadata.get("Name") or ""
        if name:
            out[canon(name)] = d.version
    return out


def min_fix(vuln: dict, package: str, current: str) -> str | None:
    """Наименьшая исправленная версия выше текущей по записи OSV; None — исправления нет."""
    cur, fixes = _vkey(current), []
    for aff in vuln.get("affected") or []:
        pkg = aff.get("package") or {}
        if canon(pkg.get("name", "")) != canon(package) or pkg.get("ecosystem") != "PyPI":
            continue
        for rng in aff.get("ranges") or []:
            for ev in rng.get("events") or []:
                fixed = ev.get("fixed")
                if not fixed:
                    continue
                try:
                    if _vkey(fixed) > cur:
                        fixes.append(fixed)
                except Exception:      # noqa: BLE001 — кривая версия в базе не валит обход
                    continue
    return min(fixes, key=_vkey) if fixes else None


def find_python_vulns(pkgs: dict, fetch=_http_json) -> list:
    """Уязвимости установленных пакетов: [{package, version, id, aliases, summary, fixed}]."""
    names = sorted(pkgs)
    queries = [{"package": {"name": n, "ecosystem": "PyPI"}, "version": pkgs[n]} for n in names]
    found, details = [], {}
    for i in range(0, len(queries), 500):
        res = fetch(OSV_BATCH, {"queries": queries[i:i + 500]}).get("results") or []
        for name, r in zip(names[i:i + 500], res, strict=False):
            for v in r.get("vulns") or []:
                vid = v.get("id")
                if vid not in details:
                    details[vid] = fetch(OSV_VULN + vid)
                d = details[vid]
                found.append({"package": name, "version": pkgs[name], "id": vid,
                              "aliases": d.get("aliases") or [],
                              "summary": (d.get("summary") or d.get("details") or "")[:200],
                              "fixed": min_fix(d, name, pkgs[name])})
    return found


#Что из нашего стека может появиться в списке CISA KEV: сверка по «производитель продукт».
#Python-пакеты сверяются точно через OSV, этот список — про ОС и серверные программы.
STACK = ("linux kernel", "ubuntu", "openssh", "openssl", "glibc", "sudo", "systemd",
         "python", "caddy", "sqlite", "curl", "xz", "polkit", "apparmor", "fail2ban",
         "pillow", "cryptography", "starlette", "fastapi", "uvicorn")
KEV_FIELDS = ("cveID", "vendorProject", "product", "vulnerabilityName", "dateAdded")


def kev_feed(fetch=_http_json) -> list:
    """Список CISA «уже используют в атаках» (нужные поля); кэш на 12 часов."""
    path = os.path.join(STATE_DIR, "kev.json")
    try:
        if time.time() - os.path.getmtime(path) < KEV_TTL_S:
            with open(path, encoding="utf-8") as fh:
                cached = json.load(fh)
            #Прежний кэш — голый список CVE; такой перекачиваем, иначе неделя без дат.
            if cached and isinstance(cached[0], dict):
                return cached
    except (OSError, ValueError, IndexError):
        pass
    feed = [{k: v.get(k) or "" for k in KEV_FIELDS}
            for v in fetch(KEV_URL, timeout=60).get("vulnerabilities") or [] if v.get("cveID")]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(feed, fh, ensure_ascii=False)
    return feed


def kev_ids(fetch=_http_json) -> set:
    return {v["cveID"] for v in kev_feed(fetch)}


def in_stack(entry: dict) -> bool:
    name = ("%s %s" % (entry.get("vendorProject"), entry.get("product"))).lower()
    return any(s in name for s in STACK)


def kev_recent(feed: list, now: float, days: int = 7) -> list:
    """Что CISA добавила за `days` дней: свежие эксплойты мира и задевают ли они нас."""
    since = time.strftime("%Y-%m-%d", time.gmtime(now - days * 86400))
    out = [{"cve": v["cveID"], "name": v.get("vulnerabilityName") or "",
            "product": ("%s %s" % (v.get("vendorProject"), v.get("product"))).strip(),
            "date": v.get("dateAdded") or "", "ours": in_stack(v)}
           for v in feed if (v.get("dateAdded") or "") >= since]
    out.sort(key=lambda x: x["date"], reverse=True)
    out.sort(key=lambda x: not x["ours"])          # наш стек — первым, внутри — свежие сверху
    return out


def _kev_key(v: dict) -> str:
    return "%s:%s" % (v["cve"], v.get("verdict") or "unknown")


def alarm_new_kev(recent: list, alerted: list, raise_alarm=None) -> list:
    """Письмо сразу о дыре нашего стека из списка CISA, если она нас задевает.

    Одно письмо на пару «CVE — вердикт»: дыра без исправления напишет ещё раз, когда
    исправление встанет и останется дождаться перезагрузки. «Не задевает» письма не даёт —
    только строку в вечерней сводке (29.10.2026: письмо о закрытой дыре читалось как «мы
    уязвимы»)."""
    if raise_alarm is None:
        from .alarm import raise_alarm
    done = list(alerted)
    for v in recent:
        key = _kev_key(v)
        if not v["ours"] or key in done:
            continue
        if (v.get("verdict") or "unknown") in ALERT_VERDICTS:
            title, lines = kev_letter(v)
            raise_alarm("kev", title, lines, key="kev:" + key, cooldown=0)
        done.append(key)
    return done[-300:]


def plan_upgrades(vulns: list) -> dict:
    """{пакет: версия} — по каждому пакету исправление, закрывающее ВСЕ его дыры."""
    plan: dict = {}
    for v in vulns:
        if v["fixed"] and v["package"] not in HOLD:
            cur = plan.get(v["package"])
            if cur is None or _vkey(v["fixed"]) > _vkey(cur):
                plan[v["package"]] = v["fixed"]
    return plan


def _run(cmd: list, timeout: int = 600) -> tuple:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def _healthy(wait_s: int = 60) -> bool:
    deadline = time.time() + wait_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH, timeout=5) as r:      # nosec B310: своя петля
                if r.status == 200:
                    return True
        except Exception:      # noqa: BLE001 — служба ещё поднимается
            pass
        time.sleep(2)
    return False


def apply_python(plan: dict, current: dict, run=_run, healthy=_healthy) -> dict:
    """Ставит план, проверяет и перезапускает; при любом сбое — откат. Итог для истории."""
    pip = [sys.executable, "-m", "pip", "--disable-pip-version-check", "-q", "install"]
    want = ["%s==%s" % (p, v) for p, v in sorted(plan.items())]
    back = ["%s==%s" % (p, current[p]) for p in sorted(plan)]
    detail = ", ".join("%s %s → %s" % (p, current[p], v) for p, v in sorted(plan.items()))

    def rollback(why: str) -> dict:
        run(pip + back)
        run(["systemctl", "restart", SERVICE], timeout=120)
        return {"ok": False, "detail": "%s; откат: %s" % (detail, why)}

    code, out = run(pip + want)
    if code != 0:
        return rollback("pip не поставил (%s)" % out.splitlines()[-1:])
    code, out = run([sys.executable, "-m", "pip", "check"])
    if code != 0:
        return rollback("конфликт зависимостей: %s" % (out.splitlines() or [""])[0])
    run(["systemctl", "restart", SERVICE], timeout=120)
    if not healthy():
        return rollback("служба не ответила на /health после перезапуска")
    return {"ok": True, "detail": detail}


def security_upgradable(apt_list: str) -> list:
    """Пакеты из раздела безопасности Ubuntu и Caddy в выводе `apt list --upgradable`.

    Строка вида «openssh-server/noble-updates,noble-security 1:9.6p1… amd64 [upgradable…]»;
    у Caddy раздел свой — «caddy/any-version». Обычные noble-updates не трогаем: они меняют
    поведение, а не закрывают дыры (deploy/maintenance/52gradebook-unattended)."""
    out = set()
    for line in apt_list.splitlines():
        name, sep, rest = line.partition("/")
        if not sep or " " in name:
            continue
        suite = rest.split(" ", 1)[0]
        if "-security" in suite or name == "caddy":
            out.add(name)
    return sorted(out)


def apply_os(run=_run) -> dict:
    """Обновления безопасности ОС и Caddy сразу, без перезагрузки. Итог — что поставилось.

    Не `unattended-upgrade`: перезагрузку ему днём не отключить (опции `-o` у него нет, а
    52gradebook-unattended велит перезагружаться сразу). Перезагрузку делает ночной прогон."""
    q = ["dpkg-query", "-W", "-f=${Package} ${Version}\n"]
    before = dict(line.split(" ", 1) for line in run(q)[1].splitlines() if " " in line)
    run(["apt-get", "update", "-qq"], timeout=300)
    pkgs = security_upgradable(run(["apt", "list", "--upgradable"])[1])
    code, out = 0, ""
    if pkgs:
        code, out = run(["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "-q",
                         "--only-upgrade", "-o", "Dpkg::Options::=--force-confdef",
                         "-o", "Dpkg::Options::=--force-confold"] + pkgs, timeout=1800)
    after = dict(line.split(" ", 1) for line in run(q)[1].splitlines() if " " in line)
    changed = sorted("%s %s → %s" % (p, before.get(p, "—"), v)
                     for p, v in after.items() if before.get(p) != v)
    return {"ok": code == 0, "installed": changed,
            "error": "" if code == 0 else (out.splitlines() or [""])[-1][:200]}


#Вердикт по дыре из списка CISA: задевает ли она нашу машину, а не только «наш ли это
#продукт». Данные — запись Ubuntu в OSV (UBUNTU-CVE-…): исходный пакет и версия исправления
#для нашего выпуска, те же, по которым Ubuntu выпускает обновления. Версии сравнивает сам
#dpkg — тем же разбором, каким их сравнивает apt.
VERDICT_ORDER = ("exposed", "nofix", "unknown", "reboot", "safe")      # от худшего к лучшему
ALERT_VERDICTS = ("exposed", "nofix", "unknown", "reboot")
VERDICT_TEXT = {
    "exposed": "задевает: исправление вышло, но на сервере его нет",
    "nofix": "задевает: исправления пока нет",
    "unknown": "проверить автоматически не удалось",
    "reboot": "исправление стоит, заработает после ночной перезагрузки",
    "safe": "нас не задевает",
}
PYPI_STACK = ("pillow", "cryptography", "starlette", "fastapi", "uvicorn")
CADDY_GO = "github.com/caddyserver/caddy/v2"
_KERNEL_BIN = re.compile(r"^linux-(image|modules)(-unsigned)?-\d")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def deb_inventory(run=_run, read=_read, kernel_release: str | None = None) -> dict:
    """Пакеты ОС по исходным пакетам и работающее ядро.

    Для ядра опасно то, что работает: рядом с новым лежит старое 6.8.0-85, но оно не
    загружено, а только что поставленное без перезагрузки ещё не защищает."""
    rel = re.search(r'^VERSION_ID="?([0-9.]+)', read("/etc/os-release"), re.M)
    q = ["dpkg-query", "-W",
         "-f=${db:Status-Abbrev}|${Package}|${source:Package}|${source:Version}\n"]
    sources: dict = {}
    binaries: dict = {}
    kernel_sources = set()
    for line in run(q)[1].splitlines():
        parts = line.split("|")
        if len(parts) != 4 or not parts[0].startswith("ii"):
            continue
        _, pkg, src, ver = parts
        if _KERNEL_BIN.match(pkg):
            #Подписанный образ собирается из `linux-signed[-…]`, а дыры Ubuntu ведёт по `linux[-…]`.
            src = re.sub(r"^linux-signed(?=-|$)", "linux", src)
            kernel_sources.add(src)
        sources.setdefault(src, set()).add(ver)
        binaries[pkg] = (src, ver)
    uname = kernel_release or platform.release()
    sig = read("/proc/version_signature").split()      # «Ubuntu 6.8.0-147.147-generic 6.8.12»
    kver = sig[1].rsplit("-", 1)[0] if len(sig) > 1 else ""
    ksrc = ""
    for name in ("linux-modules-" + uname, "linux-image-" + uname):
        if name in binaries:
            ksrc, kver = binaries[name][0], kver or binaries[name][1]
            break
    return {"release": rel.group(1) if rel else "",
            "sources": {s: sorted(v) for s, v in sources.items()},
            "kernel_sources": sorted(kernel_sources),
            "kernel": {"source": ksrc, "version": kver}}


def deb_lt(a: str, b: str, run=_run) -> bool:
    """a < b по правилам dpkg; кривая версия — ValueError, вердикт тогда «не удалось»."""
    code, out = run(["dpkg", "--compare-versions", a, "lt", b], timeout=30)
    if code not in (0, 1):
        raise ValueError(out or "dpkg --compare-versions: код %d" % code)
    return code == 0


def _fixed_in(aff: dict) -> str | None:
    return next((ev["fixed"] for rng in aff.get("ranges") or []
                 for ev in rng.get("events") or [] if ev.get("fixed")), None)


def _worst(found: list) -> str:
    return min((f[0] for f in found), key=VERDICT_ORDER.index)


def ubuntu_verdict(record: dict, inv: dict, lt) -> tuple:
    """(вердикт, причины) по записи Ubuntu для нашего выпуска; чужих пакетов не считаем."""
    if not inv.get("release") or not inv.get("sources"):
        return "unknown", ["не прочитался список пакетов ОС"]
    eco = "Ubuntu:%s:LTS" % inv["release"]
    kernel = inv.get("kernel") or {}
    found = []
    for aff in record.get("affected") or []:
        pkg = aff.get("package") or {}
        src = pkg.get("name") or ""
        if pkg.get("ecosystem") != eco or src not in inv["sources"]:
            continue
        fix, have = _fixed_in(aff), inv["sources"][src]
        if src in inv.get("kernel_sources", ()):
            if not kernel.get("source"):
                found.append(("unknown", "не определён пакет работающего ядра"))
                continue
            if src != kernel.get("source"):
                continue                         # ядро этой ветки лежит на диске, но не загружено
            cur = kernel.get("version") or "?"
            if fix and not lt(cur, fix):
                found.append(("safe", "работает ядро %s, исправлено в %s" % (cur, fix)))
            elif fix and any(not lt(v, fix) for v in have):
                found.append(("reboot", "работает ядро %s, исправленное %s уже установлено" % (
                    cur, next(v for v in have if not lt(v, fix)))))
            elif fix:
                found.append(("exposed", "работает ядро %s, исправлено в %s" % (cur, fix)))
            else:
                found.append(("nofix", "работает ядро %s, у Ubuntu %s исправления нет"
                              % (cur, inv["release"])))
            continue
        old = [v for v in have if not fix or lt(v, fix)]
        if fix and not old:
            found.append(("safe", "%s %s, исправлено в %s" % (src, "/".join(have), fix)))
        elif fix:
            found.append(("exposed", "%s %s, исправлено в %s" % (src, "/".join(old), fix)))
        else:
            found.append(("nofix", "%s %s, у Ubuntu %s исправления нет"
                          % (src, "/".join(old), inv["release"])))
    if not found:
        return "safe", ["по данным Ubuntu затронутых пакетов на сервере нет"]
    return _worst(found), [why for _, why in found]


def pypi_verdict(cve: str, product: str, pkgs: dict, python_vulns) -> tuple | None:
    """Пакеты Python сверяются тем же ответом OSV, что и весь venv; None — это не они."""
    names = [p for p in PYPI_STACK if p in product.lower() and p in pkgs]
    if not names:
        return None
    if python_vulns is None:
        return "unknown", ["OSV не ответил по пакетам Python"]
    hits = [v for v in python_vulns
            if v["package"] in names and cve in (v.get("aliases") or []) + [v["id"]]]
    if not hits:
        return "safe", ["%s %s — наша версия не задета" % (n, pkgs[n]) for n in names]
    found = [("exposed", "%s %s, исправлено в %s" % (v["package"], v["version"], v["fixed"]))
             if v.get("fixed") else
             ("nofix", "%s %s, исправления пока нет" % (v["package"], v["version"])) for v in hits]
    return _worst(found), [why for _, why in found]


def caddy_verdict(cve: str, inv: dict, fetch) -> tuple | None:
    """Caddy стоит из своего репозитория, а не из Ubuntu: сверка по его модулю Go в OSV."""
    have = (inv.get("sources") or {}).get("caddy")
    if not have:
        return None
    ver = have[-1]
    res = fetch(OSV_QUERY, {"package": {"name": CADDY_GO, "ecosystem": "Go"}, "version": ver})
    hits = [v for v in res.get("vulns") or []
            if cve == v.get("id") or cve in (v.get("aliases") or [])]
    if not hits:
        return "safe", ["Caddy %s — наша версия не задета" % ver]
    fix = next((_fixed_in(a) for v in hits for a in v.get("affected") or []
                if (a.get("package") or {}).get("name") == CADDY_GO and _fixed_in(a)), None)
    if fix:
        return "exposed", ["Caddy %s, исправлено в %s" % (ver, fix)]
    return "nofix", ["Caddy %s, исправления пока нет" % ver]


def _osv_ubuntu(cve: str, fetch) -> dict | None:
    """Запись Ubuntu о CVE в OSV; None — Ubuntu такую дыру не ведёт."""
    try:
        return fetch(OSV_VULN + "UBUNTU-" + cve)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def kev_verdict(entry: dict, inv: dict | None, pkgs: dict, python_vulns,
                fetch=_http_json, lt=None) -> dict:
    """{"verdict", "why"} — задевает ли нашу машину дыра нашего стека из списка CISA."""
    cve, product = entry["cve"], entry.get("product") or ""
    found = []
    try:
        record = _osv_ubuntu(cve, fetch)
        if record is not None:
            found.append(ubuntu_verdict(record, inv or {}, lt or deb_lt))
        py = pypi_verdict(cve, product, pkgs, python_vulns)
        if py:
            found.append(py)
        if "caddy" in product.lower():
            cd = caddy_verdict(cve, inv or {}, fetch)
            if cd:
                found.append(cd)
    except Exception as e:      # noqa: BLE001 — один сбой проверки не валит весь запуск
        return {"verdict": "unknown", "why": ["проверка не прошла: %s" % type(e).__name__]}
    if not found:
        return {"verdict": "unknown",
                "why": ["ни у Ubuntu, ни в OSV нет данных об этой дыре для наших пакетов"]}
    return {"verdict": _worst(found), "why": [w for _, ws in found for w in ws][:4]}


def verdict_line(v: dict) -> str:
    """«нас не задевает (работает ядро …, исправлено в …)» — одна строка для письма и сводки."""
    verdict = v.get("verdict") or "unknown"
    why = "; ".join(v.get("why") or [])
    return VERDICT_TEXT[verdict] + (" (%s)" % why if why else "")


def kev_letter(v: dict) -> tuple:
    """Заголовок и строки письма: что за дыра, задевает ли нас и что сделать."""
    verdict = v.get("verdict") or "unknown"
    todo = {
        "exposed": "Сторож ставит обновления безопасности каждый час вне пар (08:30–18:30 по "
                   "Улан-Удэ — только проверка). Закрыть сразу: ssh gb systemctl start "
                   "gb-os-update — поставит всё и перезагрузит сервер, если нужно (около "
                   "минуты простоя, не в часы пар).",
        "nofix": "Как только исправление выйдет, сторож поставит его в течение часа и "
                 "напишет снова. Как защититься до тех пор: https://ubuntu.com/security/"
                 + v["cve"],
        "unknown": "Проверь руками: https://ubuntu.com/security/" + v["cve"],
        "reboot": "Сервер перезагрузится сам ночью, в 02:00 по Улан-Удэ. Закрыть сразу: "
                  "ssh gb systemctl reboot (около полуминуты простоя, не в часы пар).",
    }[verdict]
    return ("В атаках дыра %s: %s" % (v["product"], VERDICT_TEXT[verdict]),
            ["%s — %s (в списке CISA с %s)" % (v["cve"], v["name"], v["date"])]
            + (v.get("why") or [])[:3] + [todo])


#Часы пар по Улан-Удэ: сторож ничего не ставит — pip перезапускает журнал, apt и
#needrestart — журнал и Caddy, а простой посреди пары дороже нескольких часов ожидания
#исправления (решение Ярослава 29.10.2026). Отложенное ставит первый запуск после пар.
CLASS_DAYS = range(0, 6)                      # пн–сб
CLASS_HOURS = ((8, 30), (18, 30))


def in_class_hours(at=None) -> bool:
    import college_clock
    d = at or college_clock.now()
    start, end = CLASS_HOURS
    return d.weekday() in CLASS_DAYS and start <= (d.hour, d.minute) < end


def _load_state() -> dict:
    try:
        with open(os.path.join(STATE_DIR, "state.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def read_state() -> dict:
    """Для ночного отчёта: последнее состояние сторожа или {} — сторож не запускался."""
    return _load_state()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry" in argv
    #`--now` — поставить и в часы пар: решение человека, а не таймера.
    hold = in_class_hours() and "--now" not in argv
    os.makedirs(STATE_DIR, exist_ok=True)
    state = _load_state()
    history = state.get("history") or []
    now = time.time()
    out: dict = {"checked_at": now, "errors": []}

    try:
        feed = kev_feed()
    except Exception as e:      # noqa: BLE001 — без KEV проверка всё равно полезна
        feed = []
        out["errors"].append("список CISA KEV не скачался: %s" % type(e).__name__)
    kev = {v["cveID"] for v in feed}
    recent = kev_recent(feed, now)
    out["kev_total"] = len(feed)
    out["kev_week"] = recent[:40]
    out["kev_alerted"] = state.get("kev_alerted") or []

    pkgs = installed()
    out["checked_python"] = len(pkgs)
    try:
        vulns = find_python_vulns(pkgs)
    except Exception as e:      # noqa: BLE001
        vulns = None
        out["errors"].append("OSV не ответил: %s" % type(e).__name__)
    if vulns is not None:
        for v in vulns:
            v["kev"] = any(a in kev for a in v["aliases"] + [v["id"]])
        plan = plan_upgrades(vulns)
        if plan and not dry and not hold:
            res = apply_python(plan, pkgs)
            history.append({"ts": now, "kind": "python", **res})
            if res["ok"]:
                fixed = set(plan)
                vulns = [v for v in vulns if v["package"] not in fixed]
        out["python"] = vulns

    out["deferred"] = hold
    if not dry and not hold:
        try:
            res = apply_os()
            out["os"] = res
            if res["installed"] or not res["ok"]:
                history.append({"ts": now, "kind": "os", "ok": res["ok"],
                                "detail": "; ".join(res["installed"]) or res["error"]})
        except Exception as e:      # noqa: BLE001
            out["errors"].append("обновление ОС: %s" % type(e).__name__)

    #Вердикт — после обновлений: письмо должно говорить о машине, какой она стала, а не
    #о той, что была до этого запуска.
    ours = [v for v in recent if v["ours"]]
    if ours:
        try:
            inv = deb_inventory()
        except Exception as e:      # noqa: BLE001 — без списка пакетов вердикт «не удалось»
            inv = None
            out["errors"].append("список пакетов ОС: %s" % type(e).__name__)
        for v in ours:
            v.update(kev_verdict(v, inv, pkgs, vulns))
    if feed and not dry:
        if "kev_alerted" not in state:
            #Первый запуск: уже известное за неделю — в сводку, а не пачкой писем разом.
            out["kev_alerted"] = [_kev_key(v) for v in ours]
        else:
            out["kev_alerted"] = alarm_new_kev(recent, out["kev_alerted"])

    out["history"] = history[-HISTORY_MAX:]
    tmp = os.path.join(STATE_DIR, "state.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(STATE_DIR, "state.json"))
    open_vulns = [v for v in (out.get("python") or [])]
    print("vulnwatch: дыр %d (с исправлением %d, в атаках %d), действий за запуск %d, ошибок %d, "
          "CISA за неделю по нашему стеку %d (задевает %d)" % (
              len(open_vulns), sum(1 for v in open_vulns if v["fixed"]),
              sum(1 for v in open_vulns if v.get("kev")),
              sum(1 for h in out["history"] if h["ts"] == now), len(out["errors"]),
              len(ours), sum(1 for v in ours if v.get("verdict") in ("exposed", "nofix"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
