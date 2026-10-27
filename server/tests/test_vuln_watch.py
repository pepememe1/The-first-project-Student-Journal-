"""Сторож уязвимостей: выбор исправления, откат при сбое, строки ночного отчёта.

Сеть и systemd подменены: проверяем решения сторожа, а не OSV и не машину."""
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
