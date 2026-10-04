"""Раздел «Приманки», подробности срабатываний, учётка-приманка и вечерняя сводка (04.10.2026).

Что держим:
  • учётка-приманка пишется в ПОСТОЯННЫЙ журнал (раньше — только в кольцевой буфер в
    памяти, рестарт стирал единственный след утечки);
  • подробности (адрес, заголовки) лежат в отдельной таблице со сроком, а в бессрочный
    журнал по-прежнему идёт только отпечаток;
  • секреты из заголовков не сохраняются никогда;
  • раздел видит ТОЛЬКО администратор;
  • расширенный список приманок ловит то, что прошло мимо на бою, и не трогает законное;
  • в письме нет ни адресов, ни логинов.
"""
import time

from app import canary, honeypot, ipgeo, throttle
from conftest import make_admin, make_teacher


def _reset():
    throttle.reset()
    canary.reset_seen()
    canary.reset_mine()


def _rows(action=None):
    from app.db import SessionLocal
    from app.models import AuditEvent, HoneypotHit
    db = SessionLocal()
    try:
        if action:
            return [(r.action, r.ip, r.target, r.level) for r in
                    db.query(AuditEvent).filter(AuditEvent.action == action).all()]
        return [(h.kind, h.ip, h.path, h.headers, h.tool, h.login, h.banned, h.trusted,
                 h.fingerprint) for h in db.query(HoneypotHit).all()]
    finally:
        db.close()


# ── пункт 2: учётка-приманка ─────────────────────────────────────────────────────────

def test_honeytoken_attempt_lands_in_the_permanent_log(client, monkeypatch):
    """Обратный ход: убери `honeypot.record(...)` из ветки honeytoken в `auth.login` —
    краснеет. До 04.10.2026 сигнал жил только в `events.record` и пропадал при рестарте."""
    _reset()
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)
    monkeypatch.setattr(throttle, "client_ip", lambda request: "203.0.113.9")
    r = client.post("/auth/login", json={"login": canary.HONEY_LOGIN, "password": "Пароль!123"})
    assert r.status_code == 401
    rows = _rows("canary.honeytoken")
    assert rows, "попытка входа под учёткой-приманкой не попала в журнал безопасности"
    action, ip, target, level = rows[-1]
    assert ip == canary.ip_fingerprint("203.0.113.9"), "в бессрочный журнал ушёл не отпечаток"
    assert level == "error"
    detail = [r for r in _rows() if r[0] == "honeytoken"]
    assert detail and detail[-1][1] == "203.0.113.9" and detail[-1][5] == canary.HONEY_LOGIN
    #Пароль не сохраняется НИГДЕ — ни в журнале, ни в подробностях.
    assert "Пароль!123" not in repr(_rows()) + repr(rows)


# ── подробности приманок-путей ──────────────────────────────────────────────────────

def test_path_hit_stores_details_but_permanent_log_keeps_only_fingerprint(client, monkeypatch):
    _reset()
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)
    monkeypatch.setattr(throttle, "client_ip", lambda request: "198.51.100.23")
    client.get("/.env?x=1", headers={"User-Agent": "Nuclei - Open-source project",
                                     "Cookie": "session=SECRETCOOKIE",
                                     "Authorization": "Bearer SECRETTOKEN"})
    audit = _rows("canary.hit")
    assert audit and "198.51.100.23" not in repr(audit), "сырой адрес попал в бессрочный журнал"
    detail = _rows()
    assert detail, "подробности срабатывания не сохранились"
    kind, ip, path, headers, tool, _login, banned, _trusted, fp = detail[-1]
    assert (kind, ip, path, tool, banned) == ("path", "198.51.100.23", "/.env", "Nuclei", True)
    assert fp == canary.ip_fingerprint("198.51.100.23"), "таблицы не связаны отпечатком"
    #Секреты из заголовков: присутствие отмечено, значение — нет.
    assert "SECRETCOOKIE" not in headers and "SECRETTOKEN" not in headers
    assert '"cookie"' in headers


def test_requests_after_ban_are_counted(client, monkeypatch):
    _reset()
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)
    monkeypatch.setattr(throttle, "client_ip", lambda request: "192.0.2.77")
    client.get("/.git/config")
    for p in ("/api/x", "/phpinfo.php", "/api/x"):
        assert client.get(p).status_code == 429
    info = honeypot.blocked_info("192.0.2.77")
    assert info["n"] == 3 and "GET /phpinfo.php" in info["paths"]


def test_retention_removes_old_details_only(client):
    from app import retention
    from app.db import SessionLocal
    from app.models import HoneypotHit
    db = SessionLocal()
    try:
        now = int(time.time())
        db.add(HoneypotHit(created_ts=now - 200 * 86400, ip="1.1.1.1", fingerprint="h:old"))
        db.add(HoneypotHit(created_ts=now - 86400, ip="2.2.2.2", fingerprint="h:new"))
        db.commit()
        assert retention.purge_honeypot(db) == 1
        db.commit()
        left = {h.fingerprint for h in db.query(HoneypotHit).all()}
        assert left == {"h:new"}
    finally:
        db.close()


def test_retention_runs_the_honeypot_step():
    """Обратный ход: вычеркни шаг из `run_all` — «хранится 90 дней» в политике станет ложью."""
    import inspect
    from app import retention
    assert "purge_honeypot(db)" in inspect.getsource(retention.run_all)


# ── доступ к разделу ────────────────────────────────────────────────────────────────

def test_section_is_admin_only(client, monkeypatch):
    _reset()
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    for path in ("/web/admin/honeypot/summary", "/web/admin/honeypot/hits",
                 "/web/admin/honeypot/source?fp=h:x"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=teacher).status_code == 403, path
        assert client.get(path, headers=admin).status_code == 200, path


def test_summary_shows_the_source(client, monkeypatch):
    _reset()
    admin = make_admin(client)
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)
    monkeypatch.setattr(throttle, "client_ip", lambda request: "203.0.113.50")
    client.get("/wp-admin/install.php", headers={"User-Agent": "curl/8.5"})
    monkeypatch.setattr(throttle, "client_ip", lambda request: "testclient")
    data = client.get("/web/admin/honeypot/summary?days=1", headers=admin).json()
    assert data["totals"]["hits"] >= 1
    src = [s for s in data["sources"] if s["ip"] == "203.0.113.50"]
    assert src and src[0]["tool"] == "curl" and src[0]["ban_left"] > 0
    card = client.get("/web/admin/honeypot/source", params={"fp": src[0]["fingerprint"]},
                      headers=admin).json()
    assert card["found"] and card["hits"][0]["path"] == "/wp-admin/install.php"


# ── пункт 3: расширенный список приманок ─────────────────────────────────────────────

def test_paths_that_slipped_through_on_prod_are_now_bait():
    for p in ("/wp-admin/install.php", "/.docker/config.json", "/.config/gcloud/credentials.db",
              "/.claude/settings.json", "/.anthropic/config.json", "/.env.example",
              "/.env-example", "/api/.env", "/laravel/.env", "/app/.git/config",
              "/000.php", "/.amplifyrc", "/server-status", "/.DS_Store"):
        assert canary.is_canary(p), p


def test_legitimate_paths_stay_clean():
    for p in ("/.well-known/acme-challenge/x", "/.well-known/assetlinks.json",
              "/assets/index-abc.js", "/app/files/1.0/index.html", "/admin/honeypot",
              "/web/admin/groups/К74/1", "/web/messenger/users/stud:ivan@mail.ru/profile",
              "/downloads/GradeBookAI.exe", "/environment", "/envelope"):
        assert not canary.is_canary(p), p


# ── классификатор ───────────────────────────────────────────────────────────────────

def test_classifier_names_tools_and_spots_fake_browsers():
    assert honeypot.classify("sqlmap/1.8")["tool_kind"] == "scanner"
    assert honeypot.classify("python-requests/2.32")["tool"] == "python-requests"
    assert honeypot.classify("")["tool_kind"] == "empty"
    fake = honeypot.classify(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/81.0.4044.129 Safari/537.36", {})
    assert fake["browser"] == "Chrome 81"
    assert any("устаревший" in r for r in fake["automated"])
    assert any("Accept-Language" in r for r in fake["automated"])
    #Телефон Cubot — не робот: голое «bot» в правилах было бы ошибкой.
    cubot = honeypot.classify("Mozilla/5.0 (Linux; Android 12; CUBOT KINGKONG) Chrome/140.0")
    assert cubot["tool_kind"] == "browser"


# ── база стран ──────────────────────────────────────────────────────────────────────

def test_ipgeo_lookup_from_local_file(tmp_path, monkeypatch):
    target = tmp_path / "ipasn.db"
    monkeypatch.setenv("GRADEBOOK_IPASN_DB", str(target))
    lines = ["1.0.0.0\t1.0.0.255\t0\tNone\tNot routed\n"]
    for i in range(1200):           #база меньше 1000 диапазонов считается битой
        lines.append("10.%d.0.0\t10.%d.0.255\t%d\tDE\tFILLER\n" % (i // 250, i % 250, 64512 + i))
    lines += ["8.8.8.0\t8.8.8.255\t15169\tUS\tGOOGLE\n",
              "2a00:1450::\t2a00:1450::ffff\t64500\tNL\tEXAMPLE-V6\n"]
    ipgeo.build_from_tsv(lines, str(target))
    assert ipgeo.lookup("8.8.8.8") == {"country": "US", "asn": 15169, "as_name": "GOOGLE"}
    assert ipgeo.lookup("2a00:1450::1")["as_name"] == "EXAMPLE-V6"
    assert ipgeo.lookup("9.9.9.9")["asn"] == 0
    assert ipgeo.lookup("192.168.1.5")["as_name"] == "локальная сеть"


def test_ipgeo_without_database_answers_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("GRADEBOOK_IPASN_DB", str(tmp_path / "нет.db"))
    assert ipgeo.lookup("8.8.8.8") == {"country": "", "asn": 0, "as_name": ""}


# ── вечерняя сводка ─────────────────────────────────────────────────────────────────

def test_report_has_no_addresses_or_logins(client, monkeypatch):
    """🔒 Письмо хранится у Google: ни адрес атакующего, ни логин человека в него не идут.
    Обратный ход: выведи `s["ip"]` в `_honeypot_block` или логин в активность — краснеет."""
    from app import nightly_report, report_mail
    from app.db import SessionLocal
    _reset()
    make_admin(client, login="ivanov.secret")
    client.post("/auth/login", json={"login": "petrov.unknown", "password": "x" * 10})
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)
    monkeypatch.setattr(throttle, "client_ip", lambda request: "203.0.113.201")
    client.get("/.env", headers={"User-Agent": "<script>alert(1)</script>"})
    db = SessionLocal()
    try:
        data = nightly_report.collect(db)
    finally:
        db.close()
    page, inline = report_mail.render_html(data)
    text = report_mail.render_text(data)
    for secret in ("203.0.113.201", "ivanov.secret", "petrov.unknown"):
        assert secret not in page and secret not in text, secret
    assert "<script>alert(1)</script>" not in page, "строка атакующего попала в письмо как разметка"
    assert data["honeypot"]["audit_hits"] >= 1
    #Каждая вложенная картинка действительно используется письмом, и наоборот.
    cids = {c for c, _b, _s in inline}
    assert all("cid:" + c in page for c in cids)
    assert "cid:vector" in page and "vector" in cids


def test_report_needs_a_recipient(monkeypatch):
    from app import nightly_report
    monkeypatch.delenv("GRADEBOOK_REPORT_EMAIL", raising=False)
    assert nightly_report.recipients() == []
    monkeypatch.setenv("GRADEBOOK_REPORT_EMAIL", "a@b.ru; c@d.ru, мусор")
    assert nightly_report.recipients() == ["a@b.ru", "c@d.ru"]


def test_mailer_inline_images_build_related_part(monkeypatch):
    """Картинки уходят ВНУТРИ письма (cid), а письма без них собираются как раньше."""
    from app import mailer
    sent = []

    class _SMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, *a): pass
        def send_message(self, msg): sent.append(msg)

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _SMTP)
    monkeypatch.setenv("GRADEBOOK_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("GRADEBOOK_SMTP_USER", "u@example.com")
    monkeypatch.setenv("GRADEBOOK_SMTP_PORT", "465")
    monkeypatch.setattr("app.secrets_source.get", lambda name: "pw")
    gif = b"GIF89a" + b"\0" * 10
    assert mailer.send_email("x@y.ru", "т", "текст", html="<img src='cid:v'>",
                             inline=[("v", gif, "gif")])
    raw = sent[-1].as_string()
    assert "multipart/related" in raw and "Content-ID: <v>" in raw
    assert mailer.send_email("x@y.ru", "т", "текст", html="<b>1</b>")
    assert "multipart/related" not in sent[-1].as_string()


def test_report_assets_are_in_place():
    import os
    from app import report_mail
    for name in ("vector_wave.gif", "vector_think.gif", "radar.gif", "pulse_ok.gif",
                 "pulse_warn.gif", "pulse_bad.gif"):
        data = report_mail._asset(name)
        assert data and data[:6] == b"GIF89a", name
    assert os.path.isdir(report_mail.ASSETS)


