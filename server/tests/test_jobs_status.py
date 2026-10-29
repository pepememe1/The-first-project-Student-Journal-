"""Вкладка «Автоматика»: снимок systemd, статусы задач и граница «смотреть, а не делать».

systemctl подменён: проверяем, как снимок читается и как из него выводится «успешно,
сбой, просрочена», а не машину."""
import json
import pathlib
import time

from conftest import make_admin, make_teacher

from app import alarm, alarm_watch, jobs_status

NOW = time.time()
H = 3600


def _systemd(timers: list, services: dict):
    """Подмена `run`: list-timers в JSON и show по службам, как отвечает systemd 255."""
    def run(cmd):
        if cmd[1] == "list-timers":
            return 0, json.dumps(timers)
        blocks = []
        for name in cmd[5:]:
            props = dict(services.get(name, {}), Id=name)
            blocks.append("\n".join("%s=%s" % kv for kv in props.items()))
        return 0, "\n\n".join(blocks) + "\n"
    return run


def _timer(name, last, nxt):
    return {"unit": name + ".timer", "activates": name + ".service",
            "last": int(last * 1e6) if last else 0, "next": int(nxt * 1e6)}


def _ran(started, finished, result="success", status="0"):
    return {"Result": result, "ExecMainStatus": status, "ActiveState": "inactive",
            "SubState": "dead", "ExecMainStartTimestamp": "@%d" % started if started else "",
            "ExecMainExitTimestamp": "@%d" % finished if finished else ""}


def test_snapshot_reads_timers_and_the_last_run_of_each_service():
    run = _systemd([_timer("gb-backup", NOW - 5 * H, NOW + 19 * H)],
                   {"gb-backup.service": dict(_ran(NOW - 5 * H, NOW - 5 * H + 2),
                                              Description="бэкап"),
                    "gb-alarm.service": {"ActiveState": "active", "SubState": "running",
                                         "ActiveEnterTimestamp": "@%d" % (NOW - 2 * H)}})
    snap = jobs_status.take_snapshot(run, None, NOW)
    u = snap["units"]["gb-backup"]
    assert u["result"] == "success" and u["exit"] == 0 and u["description"] == "бэкап"
    assert round(u["finished"] - u["started"]) == 2 and round(u["next"] - NOW) == 19 * H
    assert snap["daemon"]["active"] == "active"


def test_a_reboot_does_not_erase_the_last_run():
    """После перезагрузки systemd не помнит прошлый запуск — помнит снимок."""
    before = jobs_status.take_snapshot(
        _systemd([_timer("gb-backup", NOW - 5 * H, NOW + 19 * H)],
                 {"gb-backup.service": _ran(NOW - 5 * H, NOW - 5 * H + 2)}), None, NOW)
    after = jobs_status.take_snapshot(
        _systemd([_timer("gb-backup", NOW - 5 * H, NOW + 19 * H)],
                 {"gb-backup.service": _ran(None, None)}), before, NOW)
    assert after["units"]["gb-backup"]["started"] == before["units"]["gb-backup"]["started"]
    #Обратный ход: без прежнего снимка запуска нет — и честно «не помню».
    lost = jobs_status.take_snapshot(
        _systemd([_timer("gb-backup", 0, NOW + 19 * H)],
                 {"gb-backup.service": _ran(None, None)}), None, NOW)
    assert lost["units"]["gb-backup"]["started"] is None
    #Сбой зависимости тоже без времени старта — прежний успех его не прячет.
    dep = jobs_status.take_snapshot(
        _systemd([_timer("gb-backup", NOW - H, NOW + 19 * H)],
                 {"gb-backup.service": dict(_ran(None, None, result="dependency"),
                                            ActiveState="failed")}), before, NOW)
    assert dep["units"]["gb-backup"]["result"] == "dependency"


def test_a_failed_systemctl_does_not_overwrite_the_snapshot():
    import pytest
    with pytest.raises(RuntimeError):
        jobs_status.take_snapshot(lambda cmd: (1, ""), {"units": {"gb-backup": {}}}, NOW)


def _unit(started, result="success", **extra):
    return dict({"started": started, "finished": started + 3 if started else None,
                 "result": result, "exit": 0, "active": "inactive", "sub": "dead",
                 "next": NOW + H}, **extra)


def _status(job_id, unit, detail=None):
    snap = {"ts": NOW, "units": {job_id: unit} if unit else {},
            "daemon": {"active": "active"}}
    jobs = jobs_status.overview(NOW, snap, {job_id: detail} if detail else {})["jobs"]
    return next(j["status"] for j in jobs if j["id"] == job_id)


def test_status_says_ok_failed_overdue_never_missing_running():
    assert _status("gb-backup", _unit(NOW - 5 * H)) == "ok"
    assert _status("gb-backup", _unit(NOW - 5 * H, result="exit-code")) == "failed"
    #Сутки и полтора с часом запаса — таймер встал.
    assert _status("gb-backup", _unit(NOW - 38 * H)) == "overdue"
    assert _status("gb-backup", _unit(NOW - 30 * H)) == "ok"
    assert _status("gb-drill", _unit(None, last_trigger=None)) == "never"
    assert _status("gb-drill", None) == "missing"
    assert _status("gb-backup", _unit(NOW - 60, active="activating", sub="start")) == "running"


def test_the_job_own_result_beats_a_zero_exit_code():
    """Обновление ОС выходит с нулём и при сбое apt — сбой виден по его last.json."""
    unit = _unit(NOW - 5 * H)
    assert _status("gb-os-update", unit, {"ok": False, "error": "apt"}) == "failed"
    assert _status("gb-os-update", unit, {"ok": True}) == "ok"
    #Запуск руками мимо systemd: время берётся из итога задачи.
    assert _status("gb-drill", _unit(None, last_trigger=None), {"ok": True, "ts": NOW - H}) == "ok"


def test_the_watch_itself_the_offsite_copy_and_a_stale_snapshot_are_reported():
    snap = {"ts": NOW - 2 * H, "units": {"fstrim": _unit(NOW - 50 * H)},
            "daemon": {"active": "failed"}}
    body = jobs_status.overview(NOW, snap, {"offsite": {"ts": NOW - 8 * 86400, "name": "x.db"}})
    by_id = {j["id"]: j for j in body["jobs"]}
    assert body["stale"] is True, "снимок двухчасовой давности — сторож тревог не пишет его"
    assert by_id["gb-alarm"]["status"] == "failed" and by_id["offsite"]["status"] == "overdue"
    #Задачи Ubuntu — отдельной группой и без «просрочена»: их расписание не наше.
    assert [(s["id"], s["status"]) for s in body["system"]] == [("fstrim", "ok")]
    assert jobs_status.overview(NOW, {}, {}) == {"known": False}


def test_the_watch_really_starts_the_snapshot_loop(monkeypatch):
    """Обещание без вызывающего: снимок обязан писаться потоком сторожа тревог."""
    started = []

    class _Thread:
        def __init__(self, target, args=(), daemon=None):
            started.append(args)

        def start(self):
            pass

        def is_alive(self):
            return False
    monkeypatch.setattr(alarm_watch.threading, "Thread", _Thread)
    monkeypatch.setattr(alarm_watch, "read_trusted", lambda: ["ключ"])
    assert alarm_watch.main() == 1
    assert any(a[:2] == ("задачи", alarm_watch.jobs_tick) for a in started)


def test_the_module_and_the_route_cannot_execute_anything():
    src = (pathlib.Path(jobs_status.__file__)).read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "popen", "eval(", "exec("):
        assert forbidden not in src, "вкладка просмотра научилась запускать «%s»" % forbidden


def test_jobs_require_admin_and_read_the_snapshot(client, monkeypatch, tmp_path):
    monkeypatch.setattr(alarm, "STATE_DIR", str(tmp_path))
    admin = make_admin(client)
    teach = make_teacher(client, admin)
    assert client.get("/web/admin/server/jobs").status_code == 401
    assert client.get("/web/admin/server/jobs", headers=teach).status_code == 403
    assert client.get("/web/admin/server/jobs", headers=admin).json() == {"known": False}
    run = _systemd([_timer("gb-backup", NOW - 5 * H, NOW + 19 * H)],
                   {"gb-backup.service": _ran(NOW - 5 * H, NOW - 5 * H + 2)})
    jobs_status.write_snapshot(run, NOW)
    body = client.get("/web/admin/server/jobs", headers=admin).json()
    backup = next(j for j in body["jobs"] if j["id"] == "gb-backup")
    assert body["known"] and backup["status"] == "ok" and backup["duration_s"] == 2
