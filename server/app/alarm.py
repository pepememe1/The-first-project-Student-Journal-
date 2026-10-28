"""Мгновенные тревоги на почту: чужой вход на сервер, упавшая служба, правка ключей (27.10.2026).

Вечерняя сводка приходит раз в сутки, а о взломе или лежащем сайте узнавать в 17:00
поздно (просьба Ярослава: «как только кто-то зайдёт или сломает сервак — сразу письмо»).
События замечает сторож `alarm_watch` (служба gb-alarm), письмо уходит отсюда.

Граница ПДн та же, что у сводки: письмо хранится у почтового сервиса, поэтому адреса в
нём нет — только отпечаток (`canary.ip_fingerprint`), страна и провайдер. Полный адрес
остаётся в журнале ssh на самой машине.

Повтор одного события гасится на `COOLDOWN_S`, общий потолок — `HOURLY_CAP` писем в
час: сторож, увидевший тысячу строк подряд, не должен завалить ящик и получить бан SMTP.
Неотправленное письмо ждёт в `pending` и уходит при следующей попытке: одиночное событие
вроде чужого входа нельзя потерять из-за минутного сбоя почты.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta

import college_clock

STATE_DIR = os.environ.get("GRADEBOOK_ALARM_DIR", "/var/lib/gb-alarm")
COOLDOWN_S = 600
HOURLY_CAP = 20
HISTORY_KEEP = 100
PENDING_KEEP = 20
#Замок для потоков одного сторожа; между процессами (сторож и ручной `--test`) — flock.
_LOCK = threading.Lock()


def state_path() -> str:
    return os.path.join(STATE_DIR, "state.json")


def read_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    st.setdefault("sent", {})
    st.setdefault("history", [])
    st.setdefault("pending", [])
    return st


def _write_state(st: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False)
    os.replace(tmp, state_path())


@contextlib.contextmanager
def _locked():
    with _LOCK:
        os.makedirs(STATE_DIR, exist_ok=True)
        try:
            import fcntl
        except ImportError:      # Windows: тесты, один процесс
            yield
            return
        with open(os.path.join(STATE_DIR, ".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield


def update_state(fn) -> None:
    """Правка состояния под замком: прочитать, изменить, записать одним шагом."""
    with _locked():
        st = read_state()
        fn(st)
        _write_state(st)


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, college_clock.TZ).strftime("%d.%m %H:%M")


#Не всякое письмо сторожа — беда: о выкладке пишем отдельным значком, иначе тревоге
#«🚨» перестанут верить (28.10.2026).
NOTICE_KINDS = {"deploy": "📦"}


def compose(title: str, lines: list, ts: float, kind: str = "") -> tuple:
    """(тема, текст, html) письма-тревоги."""
    from . import mailer
    subject = "%s GradeBookAI · %s" % (NOTICE_KINDS.get(kind, "🚨"), title)
    when = "%s по времени колледжа" % _stamp(ts)
    text = "\n".join([title, when, ""] + list(lines) + [
        "", "Письмо отправил сторож тревог сервера (служба gb-alarm)."])
    html = mailer._brand_html(title, [when] + [_esc(x) for x in lines])
    return subject, text, html


def _esc(s: str) -> str:
    import html
    return html.escape(str(s))


def _send_mail(title: str, lines: list, ts: float, kind: str = "") -> bool:
    from . import config  # noqa: F401 — дочитывает server/.env (SMTP, получатели)
    from . import mailer
    from .nightly_report import recipients
    to = recipients()
    if not to or not mailer.configured():
        print("[alarm] почта не настроена — тревога не ушла: %s" % title, flush=True)
        return False
    subject, text, html = compose(title, lines, ts, kind)
    return all([mailer.send_email(addr, subject, text, html=html) for addr in to])


def raise_alarm(kind: str, title: str, lines: list, *, key: str = "",
                cooldown: int = COOLDOWN_S, now: float | None = None, send=None) -> bool:
    """Поднять тревогу. True — письмо ушло. Повтор и превышение потолка не шлются."""
    now = time.time() if now is None else now
    key = key or "%s:%s" % (kind, title)
    send = send or _send_mail
    entry = {"ts": now, "kind": kind, "title": title, "lines": list(lines)[:8], "sent": False}
    print("[alarm] %s — %s" % (title, "; ".join(map(str, lines))[:300]), flush=True)
    with _locked():
        st = read_state()
        recent = [h for h in st["history"] if h.get("sent") and now - h["ts"] < 3600]
        if now - float(st["sent"].get(key, 0)) < cooldown:
            entry["skipped"] = "повтор"
        elif len(recent) >= HOURLY_CAP:
            entry["skipped"] = "потолок писем в час"
        if "skipped" not in entry:
            #Ключ ставится ДО отправки: два потока с одним событием не пошлют два письма.
            st["sent"][key] = now
            _write_state(st)
    if "skipped" not in entry:
        entry["sent"] = bool(send(title, entry["lines"], now, kind))
    with _locked():
        st = read_state()
        st["history"] = (st["history"] + [entry])[-HISTORY_KEEP:]
        if "skipped" not in entry and not entry["sent"]:
            st["pending"] = (st["pending"] + [entry])[-PENDING_KEEP:]
        _write_state(st)
    return entry["sent"]


def flush_pending(send=None) -> int:
    """Дослать письма, не ушедшие из-за сбоя почты. Возвращает, сколько ушло."""
    send = send or _send_mail
    with _locked():
        pending = read_state()["pending"]
    if not pending:
        return 0
    done = {(e["ts"], e["title"]) for e in pending
            if send(e["title"] + " (с задержкой)", e["lines"], e["ts"], e.get("kind", ""))}

    def apply(st):
        #Фильтр, а не замена списка: пока слали, сторож мог добавить новое.
        st["pending"] = [e for e in st["pending"] if (e["ts"], e["title"]) not in done]
        for h in st["history"]:
            if (h["ts"], h["title"]) in done:
                h["sent"] = True
    if done:
        update_state(apply)
    return len(done)


def heartbeat(now: float | None = None) -> None:
    def apply(st):
        st["heartbeat"] = time.time() if now is None else now
    update_state(apply)


UPTIME_DAYS = 40


def record_uptime(result: str, now: float | None = None) -> None:
    """Итог минутной проверки: ok / fail / planned (рубильник, восстановление). Заодно —
    отметка «сторож жив»: одна запись файла в минуту вместо двух."""
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now, college_clock.TZ).strftime("%Y-%m-%d")

    def apply(st):
        up = st.setdefault("uptime", {})
        d = up.setdefault(day, {"ok": 0, "fail": 0, "planned": 0})
        d[result] = d.get(result, 0) + 1
        for old in sorted(up)[:-UPTIME_DAYS]:
            del up[old]
        st["heartbeat"] = now
    update_state(apply)


def availability(now: float, days: int = 30, st: dict | None = None) -> dict:
    """Доступность за `days` дней по минутным проверкам; плановые работы — не простой."""
    up = (st or read_state()).get("uptime") or {}
    #Вычитание у даты, а не у метки: на Windows fromtimestamp не берёт отрицательные числа.
    since = (datetime.fromtimestamp(now, college_clock.TZ)
             - timedelta(days=days)).strftime("%Y-%m-%d")
    days_in = {k: v for k, v in up.items() if k >= since}
    ok = sum(v.get("ok", 0) for v in days_in.values())
    fail = sum(v.get("fail", 0) for v in days_in.values())
    if not ok + fail:
        return {"known": False}
    return {"known": True, "pct": 100.0 * ok / (ok + fail), "down_min": fail,
            "planned_min": sum(v.get("planned", 0) for v in days_in.values()),
            "since": min(days_in), "days": len(days_in)}


def summary(now: float, hours: float = 24) -> dict:
    """Для вечерней сводки: тревоги за сутки и жив ли сторож."""
    if not os.path.exists(state_path()):
        return {"known": False}
    st = read_state()
    hb = st.get("heartbeat")
    return {"known": True,
            "heartbeat_age_min": round((now - hb) / 60, 1) if hb else None,
            "recent": [h for h in st["history"] if now - h["ts"] < hours * 3600],
            "pending": len(st["pending"]),
            "availability": availability(now, st=st)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Тревога GradeBookAI на почту")
    ap.add_argument("--test", action="store_true", help="прислать проверочное письмо")
    ap.add_argument("--title", help="своя тревога: заголовок")
    ap.add_argument("--line", action="append", default=[], help="строка письма (можно несколько)")
    ap.add_argument("--kind", default="manual", help="вид: manual — тревога, deploy — выкладка")
    args = ap.parse_args(argv)
    if args.test:
        ok = raise_alarm("test", "Проверка тревоги",
                         ["Так выглядит письмо, которое придёт сразу, если на сервер зайдёт "
                          "чужой или упадёт служба.", "Делать ничего не нужно."],
                         key="test:%d" % time.time(), cooldown=0)
    elif args.title:
        ok = raise_alarm(args.kind, args.title, args.line, cooldown=0)
    else:
        ap.print_help()
        return 2
    print("[alarm] письмо %s" % ("ушло" if ok else "НЕ ушло"))
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
