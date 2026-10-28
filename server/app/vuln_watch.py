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
Итог — `state.json`, его читает ночной отчёт (`nightly_report._security`).

Не трогает torch (колесо +cpu с отдельного индекса, только в отчёт) и пакеты без
исправления. Наружу уходят только имена и версии пакетов (docs/security/SUBPROCESSORS.md).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

OSV_BATCH = "https://api.osv.dev/v1/querybatch"
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


def alarm_new_kev(recent: list, alerted: list, raise_alarm=None) -> list:
    """Письмо сразу о дыре нашего стека, которую уже используют в атаках; одно на CVE."""
    if raise_alarm is None:
        from .alarm import raise_alarm
    done = list(alerted)
    for v in recent:
        if v["ours"] and v["cve"] not in done:
            raise_alarm("kev", "В атаках новая дыра: %s" % v["product"],
                        ["%s — %s (в списке CISA с %s)" % (v["cve"], v["name"], v["date"]),
                         "Исправления ОС и Caddy сторож ставит сам в течение часа, ядро "
                         "встаёт после ночной перезагрузки. Итог — в вечерней сводке."],
                        key="kev:%s" % v["cve"], cooldown=0)
            done.append(v["cve"])
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
    if feed and not dry:
        if "kev_alerted" not in state:
            #Первый запуск: уже известное за неделю — в сводку, а не пачкой писем разом.
            out["kev_alerted"] = [v["cve"] for v in recent if v["ours"]]
        else:
            out["kev_alerted"] = alarm_new_kev(recent, out["kev_alerted"])

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
        if plan and not dry:
            res = apply_python(plan, pkgs)
            history.append({"ts": now, "kind": "python", **res})
            if res["ok"]:
                fixed = set(plan)
                vulns = [v for v in vulns if v["package"] not in fixed]
        out["python"] = vulns

    if not dry:
        try:
            res = apply_os()
            out["os"] = res
            if res["installed"] or not res["ok"]:
                history.append({"ts": now, "kind": "os", "ok": res["ok"],
                                "detail": "; ".join(res["installed"]) or res["error"]})
        except Exception as e:      # noqa: BLE001
            out["errors"].append("обновление ОС: %s" % type(e).__name__)

    out["history"] = history[-HISTORY_MAX:]
    tmp = os.path.join(STATE_DIR, "state.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(STATE_DIR, "state.json"))
    open_vulns = [v for v in (out.get("python") or [])]
    print("vulnwatch: дыр %d (с исправлением %d, в атаках %d), действий за запуск %d, ошибок %d" % (
        len(open_vulns), sum(1 for v in open_vulns if v["fixed"]),
        sum(1 for v in open_vulns if v.get("kev")),
        sum(1 for h in out["history"] if h["ts"] == now), len(out["errors"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
