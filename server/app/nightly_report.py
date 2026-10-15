"""Вечерняя сводка на почту: активность за сутки, приманки и состояние машины (04.10.2026).

    python -m app.nightly_report                 # собрать и отправить (так зовёт таймер)
    python -m app.nightly_report --dry out.html  # только собрать письмо в файл
    python -m app.nightly_report --to a@b.ru     # другой получатель (проверка)

Запускает `deploy/report/gb-report.timer` в 17:00 по Иркутску. Отправка — тем же
`mailer`, что письма регистрации и восстановления пароля; получатели — из
`GRADEBOOK_REPORT_EMAIL` в `server/.env` (через запятую), НЕ из кода: репозиторий
публичный, а личный адрес в нём — это ПДн в открытом доступе.

━━ ЧЕГО В ПИСЬМЕ НЕТ И ПОЧЕМУ ━━
🔒 Только агрегированные числа. Ни IP-адресов, ни логинов, ни ФИО: письмо читается в
Gmail, то есть лежит у Google LLC — иностранного лица, и любая строка с ПДн была бы
трансграничной передачей, запрещённой п. 5.6.1 политики ВСГУТУ. То же правило, что у
сводки в Telegram (`GB-Claude-TG/daily_report.py`). Атакующие показаны страной,
провайдером, инструментом и ОТПЕЧАТКОМ (`h:…`); адрес — в разделе «Приманки», по ссылке.

⚠️ Всё, что пришло от атакующего (путь, User-Agent), экранируется: письмо — HTML, и путь
вида `/<script>` иначе стал бы разметкой в нашем же отчёте.

⚠️ Сбор устойчив к сбою любой части: не ответил iptoasn.com, нет `systemctl` (Windows в
тестах), не читается журнал — пункт помечается «не проверено», а письмо уходит. Сводка,
которая не пришла из-за одной недоступной цифры, хуже сводки с честным прочерком.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

#Пояс колледжа — одна дверь `college_clock` (там же, почему смещение фиксированное).
import college_clock  # noqa: E402
TZ_OFFSET_MIN = college_clock.UTC_OFFSET_H * 60
_TZ = college_clock.TZ

#Пороги «требует внимания». Каждый — про потерю данных или доступности, а не косметику.
DISK_MIN_FREE_PCT = 15          #ниже — бэкап начнёт пропускать снимки (нужно 1.5× базы)
MEM_MIN_AVAIL_MB = 120          #ниже — torch Silero уводит машину в своп
BACKUP_MAX_AGE_H = 30           #копия раз в сутки; больше 30 ч — пропущена
CERT_MIN_DAYS = 14              #Caddy продлевает за 30 дней; 14 — значит, продление встало

def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _local_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, _TZ).strftime("%Y-%m-%d")


def _run(cmd: list, timeout: int = 15) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:      # noqa: BLE001 — нет команды (Windows в тестах) = «не проверено»
        return ""


# ── СБОР ─────────────────────────────────────────────────────────────────────────────
def _count_action(db, action: str, lo: float, hi: float) -> int:
    from .models import AuditEvent
    return (db.query(AuditEvent).filter(AuditEvent.action == action,
                                        AuditEvent.created_ts >= lo,
                                        AuditEvent.created_ts < hi).count())


def _activity(db, since: float, now: float) -> dict:
    from .models import AuditEvent, Grade, Group, Lesson, Message, User
    out: dict = {}
    logins = (db.query(AuditEvent.actor, AuditEvent.role, AuditEvent.created_ts)
                .filter(AuditEvent.action == "login.ok", AuditEvent.created_ts >= since).all())
    out["logins_ok"] = len(logins)
    #Число РАЗНЫХ людей, а не их логины: имена в письмо не идут (см. шапку).
    out["logins_people"] = len({r[0] for r in logins})
    roles: dict = {}
    hours: dict = {}
    for _actor, role, ts in logins:
        roles[role or "?"] = roles.get(role or "?", 0) + 1
        h = datetime.fromtimestamp(ts, _TZ).hour
        hours[h] = hours.get(h, 0) + 1
    out["roles"] = roles
    out["peak_hour"] = max(hours, key=hours.get) if hours else None
    out["logins_fail"] = _count_action(db, "login.fail", since, now + 1)
    out["mfa_failed"] = _count_action(db, "mfa.failed", since, now + 1)
    iso, prev_iso = _iso(since), _iso(since - 86400)
    out["grades"] = (db.query(Grade).filter(Grade.updated_at >= iso,
                                            Grade.deleted == False).count())  # noqa: E712
    out["lessons"] = (db.query(Lesson).filter(Lesson.updated_at >= iso,
                                              Lesson.deleted == False).count())  # noqa: E712
    out["messages"] = (db.query(Message).filter(Message.created_at >= iso,
                                                Message.deleted_at == "").count())
    #Вчерашние сутки — для стрелок «к вчера». ⚠️ Оценки сравниваются по `updated_at`:
    #правка вчерашней оценки сегодня переносит её в «сегодня», и вчерашнее число по
    #построению чуть занижено. Для стрелки направления это приемлемо, для отчёта — нет,
    #поэтому вчерашние числа в письме подписаны только стрелкой, а не цифрой «было».
    out["prev"] = {
        "logins_ok": _count_action(db, "login.ok", since - 86400, since),
        "logins_fail": _count_action(db, "login.fail", since - 86400, since),
        "grades": (db.query(Grade).filter(Grade.updated_at >= prev_iso, Grade.updated_at < iso,
                                          Grade.deleted == False).count()),  # noqa: E712
        "messages": (db.query(Message).filter(Message.created_at >= prev_iso,
                                              Message.created_at < iso,
                                              Message.deleted_at == "").count()),
    }
    people = db.query(User).filter(User.deleted == False)  # noqa: E712
    out["students"] = people.filter(User.role == "student").count()
    out["teachers"] = people.filter(User.role == "teacher").count()
    out["parents"] = people.filter(User.role == "parent").count()
    out["groups"] = db.query(Group).filter(Group.deleted == False).count()  # noqa: E712
    #Неделя по дням — одним запросом, а не семью: на одноядерной машине сводка не должна
    #мешать журналу.
    out["week"] = _week(db, ("login.ok",), now)
    return out


def _week(db, actions: tuple, now: float) -> list:
    from .models import AuditEvent
    per_day: dict = {}
    for (ts,) in (db.query(AuditEvent.created_ts)
                    .filter(AuditEvent.action.in_(actions),
                            AuditEvent.created_ts >= now - 7 * 86400).all()):
        d = _local_day(ts)
        per_day[d] = per_day.get(d, 0) + 1
    return [{"date": _local_day(now - i * 86400),
             "n": per_day.get(_local_day(now - i * 86400), 0)} for i in range(6, -1, -1)]


_CANARY_ACTIONS = ("canary.hit", "canary.honeytoken")


def _honeypot(db, since: float, now: float) -> dict:
    from . import honeypot
    from .models import AuditEvent, HoneypotHit
    rows = (db.query(HoneypotHit).filter(HoneypotHit.created_ts >= since)
              .order_by(HoneypotHit.created_ts.desc()).all())
    count = lambda key, n=6: honeypot._top(_counter(rows, key), n)      # noqa: E731
    all_sources = honeypot.sources_of(rows, limit=1000)
    audit_q = db.query(AuditEvent).filter(AuditEvent.action.in_(_CANARY_ACTIONS))
    tools = {}
    for h in rows:
        key = (h.tool or "?", h.tool_kind or "")
        tools[key] = tools.get(key, 0) + 1
    providers = {}
    for h in rows:
        if h.asn:
            key = (h.as_name or "AS%d" % h.asn, h.asn, h.country or "")
            providers[key] = providers.get(key, 0) + 1
    return {
        "hits": len(rows),
        "audit_hits": audit_q.filter(AuditEvent.created_ts >= since).count(),
        "prev_audit_hits": audit_q.filter(AuditEvent.created_ts >= since - 86400,
                                          AuditEvent.created_ts < since).count(),
        "sources": len({h.fingerprint for h in rows}),
        "countries": len({h.country for h in rows if h.country}),
        "honeytoken": sum(1 for h in rows if h.kind == "honeytoken"),
        "automated": sum(1 for h in rows if h.automated),
        "banned_now": sum(1 for s in all_sources if s["ban_left"] > 0),
        "after_ban": sum(s["after_ban"]["n"] for s in all_sources),
        "top_countries": count(lambda h: h.country or ""),
        "top_tools": [{"tool": k[0], "kind": k[1], "n": v}
                      for k, v in honeypot._top(tools, 6)],
        "top_paths": count(lambda h: h.path or "", 7),
        "top_providers": [{"name": k[0], "asn": k[1], "country": k[2], "n": v}
                          for k, v in honeypot._top(providers, 6)],
        #Отпечаток, а НЕ адрес: см. шапку модуля.
        "top_sources": [{"fp": s["fingerprint"], "hits": s["hits"], "country": s["country"],
                         "provider": s["as_name"], "tool": s["tool"],
                         "paths": s["paths"][:3], "after_ban": s["after_ban"]["n"]}
                        for s in all_sources[:5]],
        "week": _week(db, _CANARY_ACTIONS, now),
    }


def _counter(rows, key) -> dict:
    out: dict = {}
    for h in rows:
        k = key(h)
        if k:
            out[k] = out.get(k, 0) + 1
    return out


def _backup_state() -> dict:
    folder = os.environ.get("GRADEBOOK_BACKUP_DIR") or "/root/gb-backups"
    auto = os.path.join(folder, "auto")
    if os.path.isdir(auto):
        folder = auto
    try:
        files = [os.path.join(folder, f) for f in os.listdir(folder)
                 if f.endswith((".db", ".tar.gz", ".zst", ".enc"))]
    except OSError:
        return {"known": False}
    if not files:
        return {"known": True, "count": 0}
    latest = max(files, key=os.path.getmtime)
    st = {"known": True, "count": len(files),
          "age_h": round((time.time() - os.path.getmtime(latest)) / 3600, 1),
          "size_mb": round(os.path.getsize(latest) / 2 ** 20, 1)}
    #Последняя строка журнала копий: скрипт ПРОПУСКАЕТ снимок при нехватке места и пишет
    #FAIL — молчание файла копий само по себе ничего не доказывает.
    try:
        with open("/var/log/gb-backup.log", encoding="utf-8", errors="replace") as fh:
            tail = [ln.strip() for ln in fh.readlines()[-5:] if ln.strip()]
        st["last_log"] = tail[-1][:160] if tail else ""
    except OSError:
        st["last_log"] = ""
    return st


def _cert_days(host: str) -> int | None:
    import socket
    import ssl
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                not_after = tls.getpeercert()["notAfter"]
        exp = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        return (exp - datetime.now(timezone.utc)).days
    except Exception:      # noqa: BLE001
        return None


def _site_health(url: str) -> dict:
    import urllib.request
    started = time.monotonic()
    #Только http(s): адрес приходит из настройки `SITE_URL`, а `urlopen` умеет и
    #`file://` — опечатка в настройке не должна превращать проверку сайта в чтение файла.
    if not str(url).lower().startswith(("https://", "http://")):
        return {"code": 0, "ms": 0, "error": "BadScheme"}
    try:
        #SAST B310: схема проверена строкой выше.
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=10) as r:  # nosec B310
            return {"code": r.status, "ms": int((time.monotonic() - started) * 1000)}
    except Exception as e:      # noqa: BLE001
        code = getattr(e, "code", 0)
        return {"code": code or 0, "ms": int((time.monotonic() - started) * 1000),
                "error": type(e).__name__}


def _ssh_state(hours: int = 24) -> dict:
    """Попытки входа по SSH за сутки и что держит fail2ban. Адресов не берём."""
    out: dict = {}
    log = _run(["journalctl", "-u", "ssh", "-u", "sshd", "--since", "%d hours ago" % hours,
                "--no-pager", "-o", "cat"], timeout=30)
    if log:
        lines = log.splitlines()
        out["failed"] = sum(1 for ln in lines
                            if "Failed password" in ln or "Invalid user" in ln)
        out["accepted"] = sum(1 for ln in lines if "Accepted publickey" in ln
                              or "Accepted password" in ln)
    f2b = _run(["fail2ban-client", "status", "sshd"])
    for ln in f2b.splitlines():
        if "Currently banned" in ln:
            out["f2b_banned"] = int(ln.rsplit(":", 1)[-1].strip() or 0)
        elif "Total banned" in ln:
            out["f2b_total"] = int(ln.rsplit(":", 1)[-1].strip() or 0)
    return out


def _server(db) -> dict:
    from . import config, hostinfo, ipgeo
    from .audit import verify_chain
    from .db import DATABASE_URL, DB_KEY
    out = hostinfo.summary(os.environ.get("GRADEBOOK_DEPLOY_ROOT") or os.getcwd())
    db_path = DATABASE_URL.split("///", 1)[-1] if "///" in DATABASE_URL else ""
    try:
        out["db_mb"] = round(os.path.getsize(db_path) / 2 ** 20, 1) if db_path else None
    except OSError:
        out["db_mb"] = None
    out["db_encrypted"] = bool(DB_KEY)
    try:
        out["audit_chain"] = verify_chain(db, limit=2000).get("status", "?")
    except Exception as e:      # noqa: BLE001
        out["audit_chain"] = "не проверено (%s)" % type(e).__name__
    out["services"] = {name: (_run(["systemctl", "is-active", name]).strip() or "?")
                       for name in ("gradebook", "caddy", "fail2ban", "gb-backup.timer")}
    out["backup"] = _backup_state()
    out["site"] = _site_health(config.SITE_URL or "https://esstu-gradebook.ru")
    host = (config.SITE_URL or "").split("://", 1)[-1].split("/", 1)[0].split(":")[0]
    out["cert_days"] = _cert_days(host) if host and host not in ("localhost", "127.0.0.1") else None
    out["reboot_required"] = os.path.exists("/var/run/reboot-required")
    out["ssh"] = _ssh_state()
    out["ipgeo"] = ipgeo.status()
    return out


def collect(db, now: float | None = None) -> dict:
    """Все цифры сводки за последние сутки. Каждая часть независима (см. шапку)."""
    now = now or time.time()
    since = now - 86400
    data: dict = {"now": now, "since": since}
    for name, fn in (("activity", lambda: _activity(db, since, now)),
                     ("honeypot", lambda: _honeypot(db, since, now)),
                     ("server", lambda: _server(db))):
        try:
            data[name] = fn()
        except Exception as e:      # noqa: BLE001
            db.rollback()
            data[name] = {"error": "%s: %s" % (type(e).__name__, e)}
    data["alerts"] = alerts(data)
    return data


def alerts(d: dict) -> list:
    """Что требует внимания. Пусто — «всё в порядке» в теме письма."""
    out = []
    s, hp = d.get("server") or {}, d.get("honeypot") or {}
    for part in ("activity", "honeypot", "server"):
        if (d.get(part) or {}).get("error"):
            out.append("Не собрался раздел «%s»: %s" % (part, d[part]["error"]))
    disk = s.get("disk") or {}
    if disk.get("total"):
        free_pct = 100.0 * disk.get("free", 0) / disk["total"]
        if free_pct < DISK_MIN_FREE_PCT:
            out.append("На диске свободно %.0f%% — резервные копии начнут пропускаться"
                       % free_pct)
    mem = s.get("memory") or {}
    if mem.get("available") and mem["available"] / 2 ** 20 < MEM_MIN_AVAIL_MB:
        out.append("Свободной памяти %d МБ — машина близка к своп-у"
                   % (mem["available"] / 2 ** 20))
    b = s.get("backup") or {}
    if b.get("known") and not b.get("count"):
        out.append("Резервных копий нет")
    elif b.get("age_h") is not None and b["age_h"] > BACKUP_MAX_AGE_H:
        out.append("Последней резервной копии %.0f ч — ночная копия пропущена" % b["age_h"])
    if "FAIL" in (b.get("last_log") or ""):
        out.append("Журнал копий заканчивается ошибкой: %s" % b["last_log"])
    chain = s.get("audit_chain")
    if chain and chain not in ("ok", "legacy", "empty"):
        out.append("Журнал безопасности: %s" % chain)
    site = s.get("site") or {}
    if site and site.get("code") != 200:
        out.append("Сайт не ответил на /health (код %s)" % site.get("code"))
    if s.get("cert_days") is not None and s["cert_days"] < CERT_MIN_DAYS:
        out.append("Сертификат HTTPS истекает через %d дн. — продление встало" % s["cert_days"])
    for name, state in (s.get("services") or {}).items():
        if state not in ("active", "?"):
            out.append("Служба %s: %s" % (name, state))
    if s.get("reboot_required"):
        out.append("Система просит перезагрузку после обновлений")
    if hp.get("honeytoken"):
        out.append("🍯 Вход под учёткой-приманкой (%d) — значит, утёк дамп базы или файл "
                   "окружения" % hp["honeytoken"])
    return out


# ── ПИСЬМО — в `report_mail.py` (оформление отдельно от сбора цифр) ─────────────


def recipients() -> list:
    raw = os.environ.get("GRADEBOOK_REPORT_EMAIL", "")
    return [x.strip() for x in raw.replace(";", ",").split(",") if "@" in x]


def _dump_inline(html_path: str, inline: list) -> None:
    """Для `--dry`: картинки рядом с файлом, а `cid:` в копии письма — на них.
    Иначе предпросмотр в браузере показывал бы пустые места вместо Вектора и графиков."""
    folder = os.path.dirname(os.path.abspath(html_path))
    with open(html_path, encoding="utf-8") as fh:
        page = fh.read()
    for cid, data, subtype in inline:
        name = "%s.%s" % (cid, subtype)
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(data)
        page = page.replace("cid:%s" % cid, name)
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(page)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Вечерняя сводка GradeBookAI на почту")
    ap.add_argument("--dry", metavar="FILE", help="собрать письмо в файл и ничего не слать")
    ap.add_argument("--to", help="получатель вместо GRADEBOOK_REPORT_EMAIL")
    ap.add_argument("--no-geo-update", action="store_true",
                    help="не обновлять базу стран перед сводкой")
    args = ap.parse_args(argv)
    from . import config  # noqa: F401 — дочитывает server/.env (SMTP, получатели)
    from . import ipgeo, mailer, report_mail
    from .db import SessionLocal
    if not args.no_geo_update and not args.dry:
        print("[report] база стран:", ipgeo.ensure_fresh())
    db = SessionLocal()
    try:
        data = collect(db)
    finally:
        db.close()
    page, inline = report_mail.render_html(data)
    if args.dry:
        with open(args.dry, "w", encoding="utf-8") as fh:
            fh.write(page)
        _dump_inline(args.dry, inline)
        print("[report] письмо собрано:", args.dry, "| тема:", report_mail.subject(data))
        return 0
    to = [args.to] if args.to else recipients()
    if not to:
        print("[report] получатель не задан: GRADEBOOK_REPORT_EMAIL в server/.env")
        return 2
    if not mailer.configured():
        print("[report] почта не настроена (GRADEBOOK_SMTP_*) — отправлять нечем")
        return 3
    sent = 0
    for addr in to:
        if mailer.send_email(addr, report_mail.subject(data), report_mail.render_text(data),
                             html=page, inline=inline):
            sent += 1
    #Ненулевой код — чтобы `systemctl status gb-report` показал провал, а не «успешно».
    print("[report] отправлено %d из %d" % (sent, len(to)))
    return 0 if sent == len(to) else 4


if __name__ == "__main__":
    sys.exit(main())
