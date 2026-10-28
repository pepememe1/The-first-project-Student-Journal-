"""Сторож тревог: что считается тревогой, повторы, недоставленные письма, здоровье сайта.

Почта, journalctl и systemctl подменены: проверяем решения сторожа, а не машину."""
import json

import pytest

from app import alarm, alarm_watch, canary, nightly_report

#Ключ сгенерирован ssh-keygen для теста; отпечаток — из `ssh-keygen -lf`, а не нашей формулой.
STRANGER = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMm7ae5Ey3oUNnnRPwVdzrdwLKqOIbAXCNh13GxfEXvX "
            "stranger@example")
STRANGER_FP = "SHA256:DSmqlDkFzVHQTzRp60CwjvtzRP2gr/NqbrOKgtzaPHQ"
OURS_FP = "SHA256:ours0000000000000000000000000000000000000000"
IP = "203.0.113.77"


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(alarm, "STATE_DIR", str(tmp_path / "alarm"))


def _ssh(fp, method="publickey", user="root"):
    tail = ": ED25519 %s" % fp if method == "publickey" else ""
    return {"SYSLOG_IDENTIFIER": "sshd", "__REALTIME_TIMESTAMP": "1793110512000000",
            "MESSAGE": "Accepted %s for %s from %s port 51234 ssh2%s" % (method, user, IP, tail)}


def test_fingerprint_matches_ssh_keygen():
    assert alarm_watch.key_fingerprint(STRANGER) == (STRANGER_FP, "stranger@example")
    assert alarm_watch.key_fingerprint('command="x" ' + STRANGER)[0] == STRANGER_FP
    assert alarm_watch.key_fingerprint("# комментарий") == ("", "")


def test_our_key_is_silent_and_a_stranger_or_a_password_is_an_alarm():
    trusted = {OURS_FP}
    assert alarm_watch.classify(_ssh(OURS_FP), trusted) is None
    kind, title, lines, _key, _cd = alarm_watch.classify(_ssh(STRANGER_FP), trusted)
    assert kind == "ssh" and "чужим ключом" in title
    assert any(STRANGER_FP in x for x in lines)
    assert "по паролю" in alarm_watch.classify(_ssh("", method="password"), trusted)[1]


def test_the_address_never_reaches_the_letter():
    for entry in (_ssh(STRANGER_FP), _ssh("", method="password")):
        _kind, _title, lines, _key, _cd = alarm_watch.classify(entry, {OURS_FP})
        text = " ".join(lines)
        assert IP not in text
        assert canary.ip_fingerprint(IP) in text


def test_failed_watched_service_oom_console_and_accounts():
    def c(**e):
        return alarm_watch.classify(e, set())
    hit = c(SYSLOG_IDENTIFIER="systemd",
            MESSAGE="gradebook.service: Failed with result 'signal'.")
    assert hit[0] == "unit" and "gradebook" in hit[1]
    assert c(SYSLOG_IDENTIFIER="systemd",
             MESSAGE="fwupd-refresh.service: Failed with result 'exit-code'.") is None
    assert c(_TRANSPORT="kernel",
             MESSAGE="Out of memory: Killed process 4242 (uvicorn) total-vm:1kB")[0] == "oom"
    assert c(SYSLOG_IDENTIFIER="login",
             MESSAGE="pam_unix(login:session): session opened for user root(uid=0)")[0] == \
        "console"
    assert c(SYSLOG_IDENTIFIER="useradd", MESSAGE="new user: name=evil, UID=1001")[0] == \
        "account"
    assert c(SYSLOG_IDENTIFIER="CRON", MESSAGE="pam_unix(cron:session): session opened") is None


def test_honeytoken_line_printed_by_canary_is_recognised(client, capsys):
    #Тем же разбором, что на бою: строку печатает сама приманка, сторож её читает.
    canary.record_hit("POST", "/auth/login", IP, action="canary.honeytoken", level="error")
    line = [x for x in capsys.readouterr().out.splitlines()
            if x.startswith(canary.HONEYTOKEN_MARK)][-1]
    hit = alarm_watch.classify({"_SYSTEMD_UNIT": "gradebook.service", "MESSAGE": line}, set())
    assert hit[0] == "honeytoken"
    assert IP not in line


def test_repeat_is_suppressed_and_failed_mail_is_delivered_later():
    sent = []
    ok = alarm.raise_alarm("ssh", "Вход", ["a"], key="k", now=1000,
                           send=lambda *a: sent.append(a) or True)
    again = alarm.raise_alarm("ssh", "Вход", ["a"], key="k", now=1100,
                              send=lambda *a: sent.append(a) or True)
    assert ok and not again and len(sent) == 1

    assert not alarm.raise_alarm("unit", "Упала", ["b"], key="u", now=2000,
                                 send=lambda *a: False)
    assert alarm.read_state()["pending"]
    assert alarm.flush_pending(send=lambda *a: sent.append(a) or True) == 1
    st = alarm.read_state()
    assert not st["pending"]
    assert [h["sent"] for h in st["history"] if h["title"] == "Упала"] == [True]


def test_hourly_cap_stops_a_flood():
    n = sum(alarm.raise_alarm("x", "t%d" % i, [], key="k%d" % i, now=5000 + i,
                              send=lambda *a: True) for i in range(alarm.HOURLY_CAP + 5))
    assert n == alarm.HOURLY_CAP


def test_file_watch_names_the_new_key_and_never_copies_content(tmp_path):
    keys, passwd = tmp_path / "authorized_keys", tmp_path / "passwd"
    keys.write_text("", encoding="utf-8")
    passwd.write_text("root:x:0:0::/root:/bin/bash\n", encoding="utf-8")
    raised = []
    paths = (str(keys), str(passwd))
    assert alarm_watch.check_files(lambda *a, **k: raised.append(a), paths) == 0
    keys.write_text(STRANGER + "\n", encoding="utf-8")
    assert alarm_watch.check_files(lambda *a, **k: raised.append(a), paths) == 1
    lines = raised[-1][2]
    assert any(STRANGER_FP in x and "stranger@example" in x for x in lines)
    assert not any("AAAAC3Nza" in x for x in lines)


def test_passwd_diff_lists_new_users():
    lines = alarm_watch.describe_change("/etc/passwd", {"h": "1", "users": ["root"]},
                                        {"h": "2", "users": ["evil", "root"]})
    assert "Новый пользователь ОС: evil" in lines


class _Box:
    def __init__(self):
        self.app_ok, self.site_ok, self.hard, self.pause = True, True, False, False
        self.restarts, self.alarms, self.site_probes = [], [], 0

    def site(self):
        self.site_probes += 1
        return self.site_ok

    def health(self):
        return alarm_watch.Health(
            lambda: self.app_ok, self.site, restart=self.restarts.append,
            raise_alarm=lambda kind, title, lines, **k: self.alarms.append(title),
            hard_switch_on=lambda: self.hard, paused=lambda now: self.pause,
            disk_free_pct=lambda: 50.0)


def test_three_misses_restart_once_then_recovery_is_reported():
    box = _Box()
    h = box.health()
    box.app_ok = False
    for t in range(alarm_watch.FAILS_TO_GIVE_UP + 1):
        h.tick(60.0 * t)
    assert box.restarts == ["gradebook"]
    assert [a for a in box.alarms if "после перезапуска" in a]
    box.app_ok = True
    h.tick(10_000)
    assert box.alarms[-1] == "Журнал снова работает"


def test_one_miss_is_not_an_alarm_and_pause_or_hard_switch_hold_the_hand():
    box = _Box()
    h = box.health()
    box.app_ok = False
    h.tick(0)
    box.app_ok = True
    h.tick(60)
    assert not box.alarms and not box.restarts

    box.pause, box.app_ok = True, False
    for t in range(10):
        h.tick(60.0 * t)
    assert not box.restarts

    box.pause, box.app_ok, box.hard = False, True, True
    h.tick(0)
    assert box.site_probes == 1          # первый проход выше, до паузы
    box.hard, box.site_ok = False, False
    for t in range(alarm_watch.FAILS_TO_ACT):
        h.tick(60.0 * t)
    assert box.restarts == ["caddy"]


def test_silent_watch_is_an_alert_in_the_evening_letter():
    alarm.heartbeat(now=0)
    sec = {"alarms": alarm.summary(now=3600)}
    assert any("Сторож тревог молчит" in a for a in nightly_report.alerts({"security": sec}))
    alarm.heartbeat(now=3500)
    sec = {"alarms": alarm.summary(now=3600)}
    assert not any("молчит" in a for a in nightly_report.alerts({"security": sec}))


def test_state_file_is_valid_json_after_alarms():
    alarm.raise_alarm("x", "t", ["l"], key="k", now=1, send=lambda *a: True)
    with open(alarm.state_path(), encoding="utf-8") as fh:
        assert json.load(fh)["history"][0]["title"] == "t"


def test_every_minute_counts_towards_availability_and_planned_work_is_not_downtime():
    box = _Box()
    h = box.health()
    day = 1_793_000_000.0
    for i in range(6):
        assert alarm_watch.health_tick(h, day + 60 * i) == "ok"
    box.app_ok = False
    assert alarm_watch.health_tick(h, day + 400) == "fail"
    box.app_ok, box.site_ok = True, False
    assert alarm_watch.health_tick(h, day + 460) == "fail"
    box.site_ok, box.hard = True, True
    assert alarm_watch.health_tick(h, day + 520) == "planned"
    box.hard, box.pause = False, True
    assert alarm_watch.health_tick(h, day + 580) == "planned"

    av = alarm.availability(day + 600)
    assert (av["down_min"], av["planned_min"]) == (2, 2)
    assert av["pct"] == pytest.approx(75.0)
    #Минута сторожа — это и отметка «жив»: письмо не скажет «сторож молчит».
    assert alarm.summary(day + 600)["heartbeat_age_min"] < 1
    #Месяц — скользящий: сбой 40-дневной давности в проценты не попадает.
    alarm.record_uptime("fail", day - 40 * 86400)
    assert alarm.availability(day + 600)["down_min"] == 2


def test_availability_is_unknown_until_the_watch_has_counted_anything():
    assert alarm.availability(1_793_000_000.0) == {"known": False}
    alarm.record_uptime("planned", 1_793_000_000.0)
    assert alarm.availability(1_793_000_000.0) == {"known": False}


def test_the_letter_shows_the_month_availability():
    from app import report_mail
    day = 1_793_000_000.0
    for i in range(999):
        alarm.record_uptime("ok", day + i)
    alarm.record_uptime("fail", day + 1000)
    row = report_mail._uptime_row(alarm.summary(day + 1000)["availability"])
    assert "99,90 %" in row and "простой 1 мин" in row
