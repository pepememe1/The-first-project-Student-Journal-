"""Автоматика боевого сервера: какие задачи есть, когда отработали и успешно ли (29.10.2026).

Вкладка «Автоматика» в разделе «Сервер». Снимок состояния systemd пишет сторож тревог
(`alarm_watch`, раз в 5 минут): у него есть systemctl, а у журнала его быть не должно (§16).
Здесь только чтение — снимка и итогов, которые задачи пишут сами (копии, учения, обновление
ОС, сторож уязвимостей). Команд этот модуль не запускает: функция снимка получает `run`
от вызывающего.

Результат прошлого запуска systemd помнит только до перезагрузки, поэтому новый снимок
дополняет прежний: после ночной перезагрузки вкладка не должна писать «ещё не запускалась»
про задачу, которая отработала час назад.
"""
from __future__ import annotations

import json
import os
import time

SNAPSHOT_S = 300
#Снимок старше трёх проходов — сторож тревог не работает, и вкладка об этом говорит прямо.
STALE_S = 3 * SNAPSHOT_S + 60
DAEMON = "gb-alarm"

#Наши задачи по порядку важности. `period_h` — как часто задача обязана срабатывать: пропуск
#дольше полутора периодов (и часа запаса) — «просрочена»: таймер встал или машина лежала.
#Подписи и расписание — в словаре интерфейса (`adminJobs.*`), здесь только смысл.
JOBS = (
    {"id": "gb-backup", "period_h": 24},
    {"id": "gb-vulnwatch", "period_h": 1},
    {"id": "apt-daily-upgrade", "period_h": 24},
    {"id": "gb-report", "period_h": 24},
    {"id": "gb-drill", "period_h": 168},
    {"id": "gb-os-update", "period_h": 168},
    {"id": "gb-cleanup", "period_h": 168},
    {"id": "logrotate", "period_h": 24},
)
_SHOW_PROPS = ("Id,Description,Result,ExecMainStatus,ExecMainStartTimestamp,"
               "ExecMainExitTimestamp,ActiveState,SubState,ActiveEnterTimestamp")
_RUN_KEYS = ("result", "exit", "started", "finished")


def _path() -> str:
    from . import alarm      # каталог состояния у сторожа тревог один
    return os.path.join(alarm.STATE_DIR, "jobs.json")


def _unix(v) -> float | None:
    """«@1793203228» из `systemctl show --timestamp=unix`; пусто — systemd не помнит."""
    v = (v or "").strip()
    try:
        return float(v[1:]) if v.startswith("@") else None
    except ValueError:
        return None


def _usec(v) -> float | None:
    try:
        return int(v) / 1e6 if v else None
    except (TypeError, ValueError):
        return None


def parse_show(text: str) -> dict:
    """{Id: {свойство: значение}} из вывода `systemctl show` по нескольким юнитам."""
    out: dict = {}
    cur: dict = {}
    for line in (text or "").splitlines() + [""]:
        if not line.strip():
            if cur.get("Id"):
                out[cur["Id"]] = cur
            cur = {}
            continue
        key, sep, val = line.partition("=")
        if sep:
            cur[key] = val
    return out


def take_snapshot(run, prev: dict | None, now: float) -> dict:
    """Снимок таймеров и их служб; `run(cmd) -> (код, вывод)` даёт вызывающий."""
    code, out = run(["systemctl", "list-timers", "--all", "--output=json"])
    if code != 0 or not out.strip():
        #Пустой снимок поверх прежнего стёр бы память о запусках и показал «не установлена»;
        #без записи снимок устареет, и вкладка честно скажет «данные не обновлялись».
        raise RuntimeError("systemctl list-timers: код %d" % code)
    timers = json.loads(out)
    services = sorted({t["activates"] for t in timers if t.get("activates")}
                      | {DAEMON + ".service"})
    code, out = run(["systemctl", "show", "--timestamp=unix", "-p", _SHOW_PROPS] + services)
    shown = parse_show(out) if code == 0 else {}
    before = (prev or {}).get("units") or {}
    units: dict = {}
    for t in timers:
        svc = t.get("activates") or ""
        name = svc[:-len(".service")] if svc.endswith(".service") else t.get("unit", "")
        s = shown.get(svc, {})
        exit_code = s.get("ExecMainStatus", "")
        rec = {"timer": t.get("unit", ""), "service": svc, "description": s.get("Description", ""),
               "next": _usec(t.get("next")), "last_trigger": _usec(t.get("last")),
               "result": s.get("Result", ""),
               "exit": int(exit_code) if exit_code.lstrip("-").isdigit() else None,
               "started": _unix(s.get("ExecMainStartTimestamp")),
               "finished": _unix(s.get("ExecMainExitTimestamp")),
               "active": s.get("ActiveState", ""), "sub": s.get("SubState", "")}
        old = before.get(name) or {}
        #Только «systemd не помнит» (перезагрузка), а не «не запустилась»: сбой зависимости
        #тоже даёт пустое время старта, и прежний успех его бы спрятал.
        forgot = rec["result"] in ("", "success") and rec["active"] != "failed"
        if rec["started"] is None and old.get("started") and forgot:
            rec.update({k: old.get(k) for k in _RUN_KEYS})
        units[name] = rec
    d = shown.get(DAEMON + ".service", {})
    daemon = {"active": d.get("ActiveState", ""), "sub": d.get("SubState", ""),
              "since": _unix(d.get("ActiveEnterTimestamp"))}
    return {"ts": now, "units": units, "daemon": daemon}


def write_snapshot(run, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    snap = take_snapshot(run, read_snapshot(), now)
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, ensure_ascii=False)
    os.replace(tmp, _path())
    return snap


def read_snapshot() -> dict:
    try:
        with open(_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _last(u: dict, detail: dict | None):
    #Запуск руками мимо systemd (учения 28.10) systemd не помнит, а итог задачи — помнит.
    return u.get("started") or u.get("last_trigger") or (detail or {}).get("ts")


def _status(u: dict, period_h, detail: dict | None, now: float) -> str:
    if u.get("active") == "activating" or u.get("sub") in ("start", "running"):
        return "running"
    last = _last(u, detail)
    if not last:
        return "never"
    #Итог, который задача пишет сама, строже кода выхода: обновление ОС выходит с нулём и
    #при сбое apt, а пишет его в last.json.
    if u.get("result") not in ("", "success") or (detail or {}).get("ok") is False:
        return "failed"
    if period_h and now - last > period_h * 3600 * 1.5 + 3600:
        return "overdue"
    return "ok"


def _job(job_id: str, group: str, u: dict | None, period_h, detail: dict | None,
         now: float) -> dict:
    if u is None:
        return {"id": job_id, "group": group, "status": "missing", "detail": detail or {}}
    started, finished = u.get("started"), u.get("finished")
    return {"id": job_id, "group": group, "status": _status(u, period_h, detail, now),
            "last": _last(u, detail), "next": u.get("next"),
            "duration_s": round(finished - started, 1)
            if started and finished and finished >= started else None,
            "result": u.get("result") or "", "exit": u.get("exit"),
            "description": u.get("description") or "", "detail": detail or {}}


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def details() -> dict:
    """Итоги, которые задачи пишут сами, — теми же дверями, что читает вечерняя сводка."""
    from . import nightly_report, vuln_watch
    out: dict = {}
    vw = vuln_watch.read_state()
    if vw:
        ours = [v for v in vw.get("kev_week") or [] if v.get("ours")]
        out["gb-vulnwatch"] = {
            "holes": len(vw.get("python") or []), "errors": len(vw.get("errors") or []),
            "kev_ours": len(ours),
            "kev_hit": sum(1 for v in ours if v.get("verdict") in ("exposed", "nofix"))}
    bk = nightly_report._backup_state()
    if bk.get("known") and bk.get("count"):
        out["gb-backup"] = {"count": bk["count"], "size_mb": bk.get("size_mb")}
    drill = _read_json(nightly_report.OPS_FILES["drill"])
    if drill:
        out["gb-drill"] = {k: drill.get(k)
                           for k in ("ts", "ok", "boot_s", "users", "grades", "chain")}
    osu = _read_json(nightly_report.OPS_FILES["os_update"])
    if osu:
        out["gb-os-update"] = {k: osu.get(k) for k in ("ts", "ok", "count", "reboot", "error")}
    off = _read_json(nightly_report.OPS_FILES["offsite"])
    if off:
        out["offsite"] = {"ts": off.get("ts"), "name": off.get("name")}
    return out


def overview(now: float | None = None, snapshot: dict | None = None,
             detail: dict | None = None) -> dict:
    """Ответ вкладки: наши задачи по порядку, сторож тревог, копия на ПК, задачи Ubuntu."""
    from .nightly_report import OFFSITE_MAX_AGE_D
    now = time.time() if now is None else now
    snap = read_snapshot() if snapshot is None else snapshot
    if not snap:
        return {"known": False}
    det = details() if detail is None else detail
    units = snap.get("units") or {}
    jobs = [_job(j["id"], "ours", units.get(j["id"]), j["period_h"], det.get(j["id"]), now)
            for j in JOBS]
    d = snap.get("daemon") or {}
    jobs.append({"id": DAEMON, "group": "ours", "kind": "daemon",
                 "status": "ok" if d.get("active") == "active" else "failed",
                 "since": d.get("since"), "detail": {}})
    #Копию с сервера забирает ПК администратора (`offsite_pull`), когда он включён:
    #таймера на сервере нет, есть только отметка о последнем приезде.
    off = det.get("offsite") or {}
    off_ts = off.get("ts")
    jobs.append({"id": "offsite", "group": "ours", "kind": "external",
                 "status": "never" if not off_ts else
                 ("overdue" if now - off_ts > OFFSITE_MAX_AGE_D * 86400 else "ok"),
                 "last": off_ts, "detail": {"name": off.get("name")}})
    known = {j["id"] for j in JOBS}
    system = [_job(name, "system", u, None, None, now)
              for name, u in sorted(units.items()) if name not in known]
    return {"known": True, "checked_at": snap.get("ts"),
            "stale": now - float(snap.get("ts") or 0) > STALE_S,
            "jobs": jobs, "system": system}
