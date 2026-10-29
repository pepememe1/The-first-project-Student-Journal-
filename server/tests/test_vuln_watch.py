"""Сторож уязвимостей: выбор исправления, откат при сбое, строки ночного отчёта.

Сеть и systemd подменены: проверяем решения сторожа, а не OSV и не машину."""
import json
import re
import time

from app import nightly_report, vuln_watch

VULN = {"id": "PYSEC-1", "aliases": ["CVE-2026-1"], "summary": "дыра",
        "affected": [
            {"package": {"name": "Pillow", "ecosystem": "PyPI"},
             "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "12.3.1"}]},
                        {"type": "ECOSYSTEM", "events": [{"introduced": "13.0.0"}, {"fixed": "13.0.2"}]},
                        {"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "11.0.0"}]}]},
            {"package": {"name": "pillow", "ecosystem": "Debian"},
             "ranges": [{"events": [{"fixed": "12.3.0.1"}]}]}]}


def test_the_smallest_fix_above_the_installed_version_is_chosen():
    #11.0.0 ниже установленной, Debian — чужая экосистема: обе ветки не в счёт.
    assert vuln_watch.min_fix(VULN, "pillow", "12.3.0") == "12.3.1"
    assert vuln_watch.min_fix(VULN, "pillow", "13.0.2") is None


def test_plan_closes_every_hole_of_a_package_and_skips_held_and_unfixable():
    def fetch(url, payload=None, timeout=30):
        if payload is not None:
            return {"results": [{"vulns": [{"id": "PYSEC-1"}, {"id": "PYSEC-2"}]},
                                {"vulns": [{"id": "PYSEC-3"}]}, {"vulns": [{"id": "PYSEC-4"}]}]}
        vid = url.rsplit("/", 1)[-1]
        fixes = {"PYSEC-1": ("pillow", "12.3.1"), "PYSEC-2": ("pillow", "13.0.0"),
                 "PYSEC-3": ("python-jose", None), "PYSEC-4": ("torch", "9.9")}
        name, fixed = fixes[vid]
        events = [{"introduced": "0"}] + ([{"fixed": fixed}] if fixed else [])
        return {"id": vid, "affected": [{"package": {"name": name, "ecosystem": "PyPI"},
                                         "ranges": [{"events": events}]}]}
    found = vuln_watch.find_python_vulns(
        {"pillow": "12.3.0", "python-jose": "3.5.0", "torch": "2.13.0"}, fetch=fetch)
    assert len(found) == 4
    assert vuln_watch.plan_upgrades(found) == {"pillow": "13.0.0"}


class _Machine:
    def __init__(self, pip_check_ok=True):
        self.calls, self.pip_check_ok = [], pip_check_ok

    def run(self, cmd, timeout=600):
        self.calls.append(cmd)
        if cmd[-2:] == ["pip", "check"]:
            return (0, "") if self.pip_check_ok else (1, "pyopenssl 26.3.0 has requirement cryptography<50")
        return 0, ""


def test_a_service_that_does_not_come_back_is_rolled_back():
    m = _Machine()
    res = vuln_watch.apply_python({"cryptography": "50.0.0"}, {"cryptography": "49.0.0"},
                                  run=m.run, healthy=lambda: False)
    assert not res["ok"] and "откат" in res["detail"]
    assert any("cryptography==49.0.0" in c for c in m.calls), "прежняя версия не вернулась"


def test_a_dependency_conflict_is_rolled_back_before_restart():
    m = _Machine(pip_check_ok=False)
    res = vuln_watch.apply_python({"cryptography": "50.0.0"}, {"cryptography": "49.0.0"},
                                  run=m.run, healthy=lambda: True)
    assert not res["ok"] and "конфликт" in res["detail"]
    restarts = [c for c in m.calls if c[:2] == ["systemctl", "restart"]]
    assert len(restarts) == 1, "перезапуск до отката означал бы службу на сломанных пакетах"


def test_a_healthy_upgrade_is_kept():
    m = _Machine()
    res = vuln_watch.apply_python({"certifi": "2026.10.19"}, {"certifi": "2026.6.17"},
                                  run=m.run, healthy=lambda: True)
    assert res["ok"] and "certifi 2026.6.17 → 2026.10.19" in res["detail"]
    assert not any("certifi==2026.6.17" in c for c in m.calls)


def test_only_security_updates_and_caddy_are_installed_by_day():
    listing = "\n".join((
        "Listing...",
        "openssh-server/noble-updates,noble-security 1:9.6p1-3ubuntu13.21 amd64 [upgradable from: 1:9.6p1-3ubuntu13.20]",
        "tmux/noble-updates 3.4-1ubuntu0.2 amd64 [upgradable from: 3.4-1ubuntu0.1]",
        "caddy/any-version 2.11.8 amd64 [upgradable from: 2.11.7]"))
    assert vuln_watch.security_upgradable(listing) == ["caddy", "openssh-server"]
    calls = []

    def run(cmd, timeout=600):
        calls.append(cmd)
        return 0, listing if cmd[:2] == ["apt", "list"] else ""
    res = vuln_watch.apply_os(run=run)
    install = [c for c in calls if "install" in c]
    assert res["ok"] and install and install[0][-2:] == ["caddy", "openssh-server"]
    assert not any("unattended-upgrade" in c or "reboot" in " ".join(c) for c in calls)


def test_the_evening_report_names_exploited_holes_and_failed_patches():
    d = {"security": {"known": True, "age_h": 0.5, "hold": ["torch"], "errors": [],
                      "open": [{"package": "starlette", "version": "1.0.0", "id": "GHSA-x",
                                "fixed": "1.0.1", "kev": True}],
                      "actions": [{"ok": False, "kind": "python", "detail": "starlette 1.0.0 → 1.0.1; откат"}]}}
    text = "\n".join(nightly_report.alerts(d))
    assert "CISA KEV" in text and "Автообновление не прошло" in text
    #Обратный ход: сторож ни разу не запускался (машина разработки) — тревоги нет.
    assert nightly_report.alerts({"security": {"known": False}}) == []


def test_a_failed_patch_fixed_by_a_later_run_is_not_an_alert():
    def alerts(actions):
        d = {"security": {"known": True, "age_h": 0.5, "hold": [], "errors": [], "open": [],
                          "actions": actions}}
        return [a for a in nightly_report.alerts(d) if "Автообновление" in a]
    fail = {"ok": False, "kind": "os", "detail": "error", "ts": 100}
    good = {"ok": True, "kind": "os", "detail": "libbrotli1", "ts": 200}
    assert alerts([fail, good]) == []
    assert len(alerts([good, dict(fail, ts=300)])) == 1
    #Удачный запуск другого вида сбой не гасит.
    assert len(alerts([fail, dict(good, kind="python")])) == 1


def test_the_letter_shows_what_the_watch_patched(monkeypatch):
    import time
    from app import report_mail
    now = time.time()
    monkeypatch.setattr(vuln_watch, "read_state", lambda: {
        "checked_at": now - 600, "errors": [],
        "python": [{"package": "ecdsa", "version": "0.19.2", "id": "PYSEC-2026-1325",
                    "fixed": None, "kev": False, "aliases": [], "summary": ""}],
        "history": [{"ts": now - 300, "kind": "python", "ok": True,
                     "detail": "certifi 2026.6.17 → 2026.10.19"},
                    {"ts": now - 3 * 86400, "kind": "os", "ok": True, "detail": "старое"}]})
    sec = nightly_report._security(now)
    assert [h["detail"] for h in sec["actions"]] == ["certifi 2026.6.17 → 2026.10.19"]
    block = report_mail._security_block(sec)
    assert "certifi 2026.6.17 → 2026.10.19" in block and "исправления пока нет" in block
    assert "certifi" in report_mail.render_text({"now": now, "security": sec})


_FEED = [
    {"cveID": "CVE-2026-1", "vendorProject": "OpenBSD", "product": "OpenSSH",
     "vulnerabilityName": "OpenSSH RCE", "dateAdded": "2026-10-26"},
    {"cveID": "CVE-2026-2", "vendorProject": "Microsoft", "product": "Exchange",
     "vulnerabilityName": "Exchange RCE", "dateAdded": "2026-10-27"},
    {"cveID": "CVE-2025-3", "vendorProject": "Caddy", "product": "Caddy",
     "vulnerabilityName": "старая", "dateAdded": "2025-01-01"},
]
_NOW = 1_793_200_000.0       # 28.10.2026 (UTC)


def test_world_exploits_of_the_week_put_our_stack_first():
    recent = vuln_watch.kev_recent(_FEED, _NOW)
    assert [v["cve"] for v in recent] == ["CVE-2026-1", "CVE-2026-2"]
    assert [v["ours"] for v in recent] == [True, False]
    assert not vuln_watch.in_stack({"vendorProject": "Microsoft", "product": "Exchange"})


def test_a_letter_only_for_a_hole_that_hits_us_and_again_when_its_state_changes():
    sent = []

    def alarm(*a, **k):
        sent.append(k["key"])
    recent = vuln_watch.kev_recent(_FEED, _NOW)
    recent[0].update(verdict="safe", why=["openssh 1:9.6p1-3ubuntu13.20, исправлено в 1:9.6p1-3ubuntu13.5"])
    done = vuln_watch.alarm_new_kev(recent, [], alarm)
    assert sent == [], "закрытая у нас дыра не повод для письма сразу"
    #Обратный ход: та же дыра, но исправления нет — письмо; повтор того же вердикта — нет.
    recent[0]["verdict"] = "nofix"
    done = vuln_watch.alarm_new_kev(recent, done, alarm)
    done = vuln_watch.alarm_new_kev(recent, done, alarm)
    assert sent == ["kev:CVE-2026-1:nofix"]
    recent[0]["verdict"] = "reboot"
    vuln_watch.alarm_new_kev(recent, done, alarm)
    assert sent[-1] == "kev:CVE-2026-1:reboot"
    #Без вердикта (проверка не дошла) — «не удалось», а это письмо.
    assert vuln_watch.alarm_new_kev([dict(recent[0], verdict=None)], [], alarm) \
        == ["CVE-2026-1:unknown"]


def test_the_letter_counts_checked_packages_and_world_exploits():
    from app import report_mail
    week = vuln_watch.kev_recent(_FEED, _NOW)
    week[0].update(verdict="safe", why=["openssh 1:9.6p1-3ubuntu13.20, исправлено в 1:9.6p1-3ubuntu13.5"])
    sec = {"known": True, "open": [], "actions": [], "checked_python": 87, "kev_total": 1500,
           "kev_week": week}
    block = report_mail._security_block(sec)
    assert "проверено 87" in block and "наш стек: 1" in block and "задевает: 0" in block
    assert "CVE-2026-1" in block and "нас не задевает" in block and "13.5" in block
    text = report_mail.render_text({"now": _NOW, "security": sec})
    assert "проверено: 87" in text and "наш стек: 1" in text and "нас не задевает" in text


#Ключ сравнения для тестов: числа по порядку. Настоящий сторож спрашивает dpkg.
def _lt(a, b):
    def key(s):
        return [int(x) for x in re.findall(r"\d+", s)]
    return key(a) < key(b)


_INV = {"release": "24.04",
        "sources": {"linux": ["6.8.0-147.147", "6.8.0-85.85"], "linux-meta": ["6.8.0-147.147"],
                    "openssl": ["3.0.13-0ubuntu3.16"], "caddy": ["2.11.7"]},
        "kernel_sources": ["linux"],
        "kernel": {"source": "linux", "version": "6.8.0-147.147"}}


def _ubuntu(*affected):
    return {"id": "UBUNTU-CVE-2026-46300", "affected": [
        {"package": {"name": name, "ecosystem": eco},
         "ranges": [{"type": "ECOSYSTEM",
                     "events": [{"introduced": "0"}] + ([{"fixed": fix}] if fix else [])}]}
        for name, eco, fix in affected]}


def test_a_kernel_hole_is_judged_by_the_running_kernel():
    rec = _ubuntu(("linux", "Ubuntu:24.04:LTS", "6.8.0-124.124"),
                  ("linux", "Ubuntu:22.04:LTS", "5.15.0-200.210"),
                  ("linux-aws", "Ubuntu:24.04:LTS", "6.8.0-1057.60"))
    verdict, why = vuln_watch.ubuntu_verdict(rec, _INV, _lt)
    #Старое ядро 6.8.0-85 лежит на диске, но не загружено, — оно вердикт не портит.
    assert verdict == "safe" and why == ["работает ядро 6.8.0-147.147, исправлено в 6.8.0-124.124"]
    old = dict(_INV, kernel={"source": "linux", "version": "6.8.0-85.85"})
    assert vuln_watch.ubuntu_verdict(rec, old, _lt)[0] == "reboot"
    alone = dict(old, sources=dict(_INV["sources"], linux=["6.8.0-85.85"]))
    assert vuln_watch.ubuntu_verdict(rec, alone, _lt)[0] == "exposed"
    assert vuln_watch.ubuntu_verdict(_ubuntu(("linux", "Ubuntu:24.04:LTS", None)), _INV, _lt)[0] \
        == "nofix"


def test_an_os_package_hole_counts_only_packages_we_have():
    rec = _ubuntu(("openssl", "Ubuntu:24.04:LTS", "3.0.13-0ubuntu3.20"),
                  ("nginx", "Ubuntu:24.04:LTS", None))
    verdict, why = vuln_watch.ubuntu_verdict(rec, _INV, _lt)
    assert verdict == "exposed" and "openssl 3.0.13-0ubuntu3.16" in why[0]
    assert vuln_watch.ubuntu_verdict(_ubuntu(("nginx", "Ubuntu:24.04:LTS", None)), _INV, _lt) \
        == ("safe", ["по данным Ubuntu затронутых пакетов на сервере нет"])
    #Список пакетов не прочитался — это «не удалось», а не «не задевает».
    assert vuln_watch.ubuntu_verdict(rec, {}, _lt)[0] == "unknown"


def test_inventory_reads_installed_sources_and_the_running_kernel():
    listing = "\n".join((
        "ii |linux-image-6.8.0-147-generic|linux-signed|6.8.0-147.147",
        "ii |linux-modules-6.8.0-147-generic|linux|6.8.0-147.147",
        "ii |linux-image-6.8.0-85-generic|linux-signed|6.8.0-85.85",
        "un |linux-modules-extra-6.8.0-147-generic|linux-modules-extra-6.8.0-147-generic|",
        "ii |libssl3t64|openssl|3.0.13-0ubuntu3.16"))
    files = {"/etc/os-release": 'NAME="Ubuntu"\nVERSION_ID="24.04"\n',
             "/proc/version_signature": "Ubuntu 6.8.0-147.147-generic 6.8.12\n"}
    inv = vuln_watch.deb_inventory(run=lambda cmd, timeout=600: (0, listing),
                                   read=lambda p: files.get(p, ""),
                                   kernel_release="6.8.0-147-generic")
    assert inv["release"] == "24.04" and inv["kernel"] == {"source": "linux",
                                                           "version": "6.8.0-147.147"}
    assert inv["sources"]["linux"] == ["6.8.0-147.147", "6.8.0-85.85"]
    assert "linux-signed" not in inv["sources"] and inv["kernel_sources"] == ["linux"]
    assert "linux-modules-extra-6.8.0-147-generic" not in inv["sources"], "не установлен"


def test_python_and_caddy_exploits_are_checked_by_their_own_registries():
    pkgs = {"pillow": "12.3.0"}
    entry = {"cve": "CVE-2026-1", "product": "Python Pillow"}
    assert vuln_watch.pypi_verdict("CVE-2026-1", entry["product"], pkgs, [])[0] == "safe"
    hole = {"package": "pillow", "version": "12.3.0", "id": "GHSA-x", "aliases": ["CVE-2026-1"],
            "fixed": "12.3.1"}
    assert vuln_watch.pypi_verdict("CVE-2026-1", entry["product"], pkgs, [hole])[0] == "exposed"
    assert vuln_watch.pypi_verdict("CVE-2026-1", entry["product"], pkgs, None)[0] == "unknown"

    asked = []

    def fetch(url, payload=None, timeout=30):
        asked.append(payload)
        return {"vulns": [{"id": "GHSA-c", "aliases": ["CVE-2026-9"], "affected": [
            {"package": {"name": vuln_watch.CADDY_GO, "ecosystem": "Go"},
             "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.11.8"}]}]}]}]}
    assert vuln_watch.caddy_verdict("CVE-2026-9", _INV, fetch) \
        == ("exposed", ["Caddy 2.11.7, исправлено в 2.11.8"])
    assert vuln_watch.caddy_verdict("CVE-2026-8", _INV, fetch)[0] == "safe"
    assert asked[0]["version"] == "2.11.7"


def test_no_data_or_a_failed_check_is_unknown_not_safe():
    import urllib.error

    def missing(url, payload=None, timeout=30):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    def broken(url, payload=None, timeout=30):
        raise TimeoutError
    entry = {"cve": "CVE-2026-46300", "product": "Linux Kernel"}
    assert vuln_watch.kev_verdict(entry, _INV, {}, [], fetch=missing, lt=_lt)["verdict"] == "unknown"
    assert vuln_watch.kev_verdict(entry, _INV, {}, [], fetch=broken, lt=_lt)["verdict"] == "unknown"
    rec = _ubuntu(("linux", "Ubuntu:24.04:LTS", "6.8.0-124.124"))
    res = vuln_watch.kev_verdict(entry, _INV, {}, [], fetch=lambda *a, **k: rec, lt=_lt)
    assert res["verdict"] == "safe" and "6.8.0-124.124" in vuln_watch.verdict_line(res)


def test_the_run_judges_exploits_after_patching_and_writes_only_about_hits(monkeypatch, tmp_path):
    from app import alarm
    today = time.strftime("%Y-%m-%d", time.gmtime())
    feed = [{"cveID": "CVE-2026-46300", "vendorProject": "Linux", "product": "Kernel",
             "vulnerabilityName": "ядро", "dateAdded": today},
            {"cveID": "CVE-2026-7", "vendorProject": "OpenBSD", "product": "OpenSSH",
             "vulnerabilityName": "ssh", "dateAdded": today}]
    order, sent = [], []
    (tmp_path / "state.json").write_text(json.dumps({"kev_alerted": []}), encoding="utf-8")
    monkeypatch.setattr(vuln_watch, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(vuln_watch, "kev_feed", lambda: feed)
    monkeypatch.setattr(vuln_watch, "installed", lambda: {})
    monkeypatch.setattr(vuln_watch, "find_python_vulns", lambda pkgs: [])
    monkeypatch.setattr(vuln_watch, "apply_os", lambda: order.append("os")
                        or {"ok": True, "installed": [], "error": ""})
    monkeypatch.setattr(vuln_watch, "deb_inventory", lambda: order.append("inventory") or _INV)
    monkeypatch.setattr(vuln_watch, "kev_verdict", lambda v, inv, pkgs, vulns: {
        "verdict": "safe" if v["cve"] == "CVE-2026-46300" else "exposed", "why": []})
    monkeypatch.setattr(alarm, "raise_alarm", lambda kind, title, lines, **k: sent.append(k["key"]))
    monkeypatch.setattr(vuln_watch, "in_class_hours", lambda: False)
    vuln_watch.main([])
    assert order == ["os", "inventory"], "вердикт до обновлений описывал бы прежнюю машину"
    assert sent == ["kev:CVE-2026-7:exposed"]
    week = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["kev_week"]
    assert {v["cve"]: v["verdict"] for v in week} == {"CVE-2026-46300": "safe",
                                                      "CVE-2026-7": "exposed"}
    #Часы пар: проверка и письма идут, а ничего не ставится — журнал не перезапускается.
    order.clear()
    monkeypatch.setattr(vuln_watch, "in_class_hours", lambda: True)
    vuln_watch.main([])
    assert order == ["inventory"]
    vuln_watch.main(["--now"])
    assert order == ["inventory", "os", "inventory"], "--now — решение человека"


def test_class_hours_are_weekdays_and_saturday_from_830_to_1830():
    from datetime import datetime
    assert vuln_watch.in_class_hours(datetime(2026, 10, 29, 9, 0))        # четверг
    assert vuln_watch.in_class_hours(datetime(2026, 10, 31, 18, 29))      # суббота
    assert not vuln_watch.in_class_hours(datetime(2026, 10, 29, 18, 30))
    assert not vuln_watch.in_class_hours(datetime(2026, 10, 29, 8, 29))
    assert not vuln_watch.in_class_hours(datetime(2026, 11, 1, 12, 0))    # воскресенье


def test_an_unidentified_running_kernel_is_unknown_not_safe():
    rec = _ubuntu(("linux", "Ubuntu:24.04:LTS", "6.8.0-999.999"))
    blind = dict(_INV, kernel={"source": "", "version": ""})
    assert vuln_watch.ubuntu_verdict(rec, blind, _lt)[0] == "unknown"
