"""Сторож тревог (служба gb-alarm): журнал системы, ключи входа, здоровье сайта (27.10.2026).

Три потока в одном процессе, письмо шлёт `alarm.raise_alarm`:
  • журнал — `journalctl -f -o json`: вход по ssh не нашим ключом или паролем, вход в
    консоль хостинга, упавшая служба, убийство процесса по памяти, вход учёткой-приманкой,
    правка учётных записей ОС;
  • файлы — раз в минуту хеши ключей входа, учёток ОС, sshd, cron и юнитов systemd.
    База хешей лежит на диске, поэтому видна и правка, сделанная, пока сторож лежал;
  • здоровье — раз в минуту /health журнала и сайта снаружи. Три промаха подряд —
    перезапуск службы и письмо, возврат — письмо «снова работает».

«Свои» ключи — отпечатки в `TRUSTED_KEYS` (заводятся при установке из нынешних
authorized_keys). Ключ, которого там нет, — тревога, даже если его уже дописали в
authorized_keys: дописать мог и взломщик, и о правке файла придёт отдельное письмо.
Вход нашим же ключом с украденного ноутбука так не отличить — это предел метода.

Процесс отдельный от журнала и в `main` не подключается: здесь есть `subprocess`
(journalctl, systemctl), а у боевого приложения его быть не должно (§16).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

import college_clock

from . import alarm

TRUSTED_KEYS = os.environ.get("GRADEBOOK_ALARM_TRUSTED", "/etc/gb-alarm/trusted-keys")
PAUSE_FILE = "/run/gb-alarm.pause"
HARD_SWITCH_FLAG = "/var/www/gb-maintenance/maintenance.on"
APP_HEALTH = "http://127.0.0.1:8000/health"
TICK_S = 60
FAILS_TO_ACT = 3
#Через сколько промахов после перезапуска звать человека: 5 минут — запас на долгий старт.
FAILS_TO_GIVE_UP = FAILS_TO_ACT + 5
DISK_MIN_FREE_PCT = 8

WATCH_UNITS = ("gradebook", "caddy", "fail2ban", "ssh", "ufw", "gb-backup", "gb-vulnwatch",
               "gb-report", "gb-alarm")
ACCOUNT_TOOLS = ("useradd", "userdel", "usermod", "groupadd", "groupdel", "chpasswd",
                 "passwd", "gpasswd")
WATCH_FILES = (
    "/root/.ssh/authorized_keys", "/home/gbadmin/.ssh/authorized_keys",
    "/home/relay/.ssh/authorized_keys", "/etc/passwd", "/etc/shadow", "/etc/group",
    "/etc/sudoers", "/etc/sudoers.d", "/etc/ssh/sshd_config", "/etc/ssh/sshd_config.d",
    "/etc/crontab", "/etc/cron.d", "/var/spool/cron/crontabs", "/etc/systemd/system",
    TRUSTED_KEYS,
)

#`\w+`, а не `\S+`, перед двоеточием: иначе «ssh2:» съедал двоеточие, отпечаток не
#находился, и свой ключ поднимал тревогу.
SSH_ACCEPTED = re.compile(r"Accepted (\S+) for (\S+) from (\S+) port \d+ \w+"
                          r"(?:: (\S+) (SHA256:\S+))?")
CONSOLE_LOGIN = re.compile(r"session opened for user (\S+)")
UNIT_FAILED = re.compile(r"^(\S+)\.service: Failed with result '([^']+)'")
OOM_KILL = re.compile(r"Out of memory: Killed process \d+ \(([^)]+)\)")

UNIT_HINTS = {
    "gradebook": "systemd поднимет её сам. Если письма «снова работает» нет через пять "
                 "минут — кнопка «Рестарт сервера» или «Откат бэкап» → откат выкладки.",
    "caddy": "Caddy отдаёт сайт наружу: пока он лежит, сайт не открывается. systemd "
             "поднимет его сам через 3 секунды.",
}


# ── ключи ssh ───────────────────────────────────────────────────────────────────────
def key_fingerprint(line: str) -> tuple:
    """(отпечаток SHA256:…, подпись) строки authorized_keys; ("", "") — не ключ."""
    parts = line.strip().split()
    for i, tok in enumerate(parts):
        if tok.startswith(("ssh-", "ecdsa-", "sk-")) and i + 1 < len(parts):
            try:
                blob = base64.b64decode(parts[i + 1], validate=True)
            except ValueError:
                return "", ""
            fp = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
            return "SHA256:" + fp, " ".join(parts[i + 2:])
    return "", ""


def read_trusted(path: str = TRUSTED_KEYS) -> set:
    try:
        with open(path, encoding="utf-8") as fh:
            return {ln.split()[0] for ln in fh if ln.strip() and not ln.startswith("#")}
    except OSError:
        return set()


def _who(ip: str) -> str:
    """Отпечаток, страна и провайдер вместо адреса: письмо лежит у почтового сервиса."""
    from . import canary, ipgeo
    from .report_mail import country_name
    geo = ipgeo.lookup(ip)
    where = " · ".join(x for x in (country_name(geo["country"]) if geo.get("country") else "",
                                   geo.get("as_name") or "") if x)
    return "%s%s" % (canary.ip_fingerprint(ip), (" · " + where) if where else "")


# ── журнал ──────────────────────────────────────────────────────────────────────────
def _text(value) -> str:
    #journalctl отдаёт строку с непечатными байтами массивом чисел.
    if isinstance(value, list):
        return bytes(v for v in value if isinstance(v, int)).decode("utf-8", "replace")
    return str(value or "")


def classify(entry: dict, trusted: set, who=_who) -> tuple | None:
    """Запись журнала → (вид, заголовок, строки, ключ, пауза) или None, если не тревога."""
    from . import canary
    from .events import one_line
    msg = _text(entry.get("MESSAGE"))
    ident = _text(entry.get("SYSLOG_IDENTIFIER"))
    unit = _text(entry.get("_SYSTEMD_UNIT"))
    if ident in ("sshd", "sshd-session"):
        m = SSH_ACCEPTED.search(msg)
        if not m:
            return None
        method, user, ip, ktype, fp = m.groups()
        if method == "publickey" and fp in trusted:
            return None
        if method != "publickey":
            return ("ssh", "Вход на сервер по паролю",
                    ["Пользователь: %s, способ: %s" % (user, method),
                     "Откуда: %s" % who(ip),
                     "Вход по паролю на сервере выключен — значит, кто-то поменял настройки "
                     "ssh. Если это не вы, сервер взломан."],
                    "ssh:%s:%s" % (method, ip), alarm.COOLDOWN_S)
        return ("ssh", "Вход на сервер чужим ключом",
                ["Пользователь: %s" % user, "Откуда: %s" % who(ip),
                 "Ключ: %s %s" % (ktype or "?", fp or "?"),
                 "Этого ключа нет среди наших (Ярослав, Влад, релей). Если это не вы — "
                 "сервер взломан: смените пароль в панели reg.ru и удалите ключ из "
                 "authorized_keys."],
                "ssh:%s:%s" % (fp, ip), alarm.COOLDOWN_S)
    if ident == "login":
        m = CONSOLE_LOGIN.search(msg)
        if m:
            return ("console", "Вход в консоль сервера",
                    ["Пользователь: %s" % m.group(1),
                     "Так входят через VNC в панели reg.ru. Если это не вы — сервер в "
                     "чужих руках."], "console:%s" % m.group(1), alarm.COOLDOWN_S)
        return None
    if ident == "systemd" or unit == "init.scope":
        m = UNIT_FAILED.search(msg)
        if m and m.group(1) in WATCH_UNITS:
            name, result = m.groups()
            return ("unit", "Упала служба %s" % name,
                    ["Причина: %s" % result,
                     UNIT_HINTS.get(name, "Проверь: systemctl status %s" % name)],
                    "unit:%s" % name, 900)
        return None
    if entry.get("_TRANSPORT") == "kernel":
        m = OOM_KILL.search(msg)
        if m:
            return ("oom", "Не хватило памяти: убит процесс %s" % m.group(1),
                    ["Ядро убило процесс, чтобы машина не встала. Если это журнал — "
                     "systemd поднимет его сам."], "oom:%s" % m.group(1), 900)
        return None
    if unit == "gradebook.service" and msg.startswith(canary.HONEYTOKEN_MARK):
        rest = msg[len(canary.HONEYTOKEN_MARK):].strip()
        return ("honeytoken", "Вход учёткой-приманкой",
                ["Логин приманки есть только в дампе базы или в файле окружения — похоже, "
                 "утекла копия.", "Источник и путь: %s" % one_line(rest)[:120],
                 "Подробности — раздел «Приманки» в админке."], "honeytoken", 1800)
    if ident in ACCOUNT_TOOLS:
        return ("account", "Изменены учётные записи сервера",
                [one_line(msg)[:200], "Если это не вы — на сервере чужой."],
                "account:%s" % one_line(msg)[:60], alarm.COOLDOWN_S)
    return None


def _event_time(entry: dict) -> str:
    try:
        ts = int(_text(entry.get("__REALTIME_TIMESTAMP"))) / 1e6
    except ValueError:
        return ""
    return datetime.fromtimestamp(ts, college_clock.TZ).strftime("%d.%m %H:%M:%S")


def handle_entry(entry: dict, trusted: set, raise_alarm=alarm.raise_alarm, who=_who) -> bool:
    hit = classify(entry, trusted, who)
    if not hit:
        return False
    kind, title, lines, key, cooldown = hit
    when = _event_time(entry)
    raise_alarm(kind, title, (["Когда: %s" % when] if when else []) + lines,
                key=key, cooldown=cooldown)
    return True


def follow_journal(trusted_ref: dict) -> None:
    """Читать журнал с последней запомненной позиции; упал journalctl — заново через 5 с."""
    while True:
        cursor = alarm.read_state().get("cursor") or ""
        args = ["journalctl", "-f", "-o", "json", "--no-pager"]
        args += ["--after-cursor", cursor] if cursor else ["-n", "0"]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, text=True, errors="replace")
        saved = time.time()
        for line in proc.stdout:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            try:
                handle_entry(entry, trusted_ref["keys"])
            except Exception as e:      # noqa: BLE001 — одна кривая строка не роняет сторожа
                print("[alarm-watch] строка журнала не разобрана: %s" % e, flush=True)
            if time.time() - saved > 30 and entry.get("__CURSOR"):
                cur = entry["__CURSOR"]
                alarm.update_state(lambda st, c=cur: st.__setitem__("cursor", c))
                saved = time.time()
        code = proc.wait()
        if code:
            #Позиция могла уйти с ротацией журнала: без сброса journalctl падал бы вечно.
            alarm.update_state(lambda st: st.pop("cursor", None))
        time.sleep(5)


# ── файлы ───────────────────────────────────────────────────────────────────────────
def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def snapshot(path: str) -> dict | None:
    """Отпечаток файла или каталога. Содержимое в письмо не идёт: в /etc/shadow хеши."""
    if os.path.isdir(path):
        files = {}
        for base, _dirs, names in os.walk(path):
            for n in names:
                p = os.path.join(base, n)
                if os.path.isfile(p) and not os.path.islink(p):
                    try:
                        files[os.path.relpath(p, path)] = _hash_file(p)
                    except OSError:
                        continue
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        return {"h": digest, "files": files}
    if not os.path.isfile(path):
        return None
    try:
        out = {"h": _hash_file(path)}
        if path.endswith("authorized_keys") or path == TRUSTED_KEYS:
            with open(path, encoding="utf-8", errors="replace") as fh:
                keys = [key_fingerprint(ln) for ln in fh]
            out["keys"] = {fp: comment for fp, comment in keys if fp}
        elif path == "/etc/passwd":
            with open(path, encoding="utf-8", errors="replace") as fh:
                out["users"] = sorted(ln.split(":")[0] for ln in fh if ":" in ln)
        return out
    except OSError:
        return None


def describe_change(path: str, old: dict | None, new: dict | None) -> list:
    if old is None:
        return ["Появился %s" % path]
    if new is None:
        return ["Удалён %s" % path]
    lines = []
    if "keys" in old or "keys" in new:
        a, b = old.get("keys") or {}, new.get("keys") or {}
        lines += ["Добавлен ключ %s %s" % (fp, b[fp]) for fp in b if fp not in a]
        lines += ["Удалён ключ %s %s" % (fp, a[fp]) for fp in a if fp not in b]
    if "users" in old or "users" in new:
        a, b = set(old.get("users") or ()), set(new.get("users") or ())
        lines += ["Новый пользователь ОС: %s" % u for u in sorted(b - a)]
        lines += ["Удалён пользователь ОС: %s" % u for u in sorted(a - b)]
    if "files" in old or "files" in new:
        a, b = old.get("files") or {}, new.get("files") or {}
        lines += ["Новый файл: %s" % f for f in sorted(set(b) - set(a))][:10]
        lines += ["Изменён: %s" % f for f in sorted(set(a) & set(b)) if a[f] != b[f]][:10]
        lines += ["Удалён файл: %s" % f for f in sorted(set(a) - set(b))][:10]
    return ["Изменён %s" % path] + lines


def check_files(raise_alarm=alarm.raise_alarm, paths=WATCH_FILES) -> int:
    """Сверить файлы с запомненными отпечатками; первый проход только запоминает."""
    path_store = os.path.join(alarm.STATE_DIR, "files.json")
    try:
        with open(path_store, encoding="utf-8") as fh:
            known = json.load(fh)
    except (OSError, ValueError):
        known = None
    now = {p: snapshot(p) for p in paths}
    changed = 0
    if known is not None:
        for p in paths:
            old, new = known.get(p), now.get(p)
            if (old or {}).get("h") != (new or {}).get("h"):
                changed += 1
                lines = describe_change(p, old, new) + [
                    "Если это делали вы (установка, выкладка) — всё в порядке. Если нет — "
                    "на сервере чужой."]
                raise_alarm("file", "Изменён важный файл сервера", lines,
                            key="file:%s:%s" % (p, (new or {}).get("h")), cooldown=0)
    os.makedirs(alarm.STATE_DIR, exist_ok=True)
    with open(path_store + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(now, fh)
    os.replace(path_store + ".tmp", path_store)
    return changed


# ── здоровье ────────────────────────────────────────────────────────────────────────
def _probe(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:  # nosec B310 — свой адрес
            return r.status == 200
    except Exception:       # noqa: BLE001 — любая ошибка = «не отвечает»
        return False


def _restart(service: str) -> None:
    subprocess.run(["systemctl", "restart", service], timeout=120, check=False)


def _paused(now: float) -> bool:
    try:
        with open(PAUSE_FILE, encoding="utf-8") as fh:
            return float(fh.read().strip() or 0) > now
    except (OSError, ValueError):
        return False


class Health:
    """Счётчики промахов и решения «перезапустить / позвать человека / отбой»."""

    def __init__(self, probe_app, probe_site, restart=_restart, raise_alarm=alarm.raise_alarm,
                 hard_switch_on=lambda: os.path.exists(HARD_SWITCH_FLAG),
                 paused=_paused, disk_free_pct=None):
        self.probe_app, self.probe_site = probe_app, probe_site
        self.restart, self.raise_alarm = restart, raise_alarm
        self.hard_switch_on, self.paused = hard_switch_on, paused
        self.disk_free_pct = disk_free_pct or _disk_free_pct
        self.fails = {"app": 0, "site": 0}
        self.since = {"app": 0.0, "site": 0.0}
        self.alerted = {"app": False, "site": False}

    def tick(self, now: float) -> str:
        """Один проход; итог для счёта доступности: ok / fail / planned."""
        if self.paused(now):
            return "planned"
        app_ok = self.probe_app()
        self._step("app", app_ok, now, "gradebook", "Журнал не отвечает",
                   "Журнал снова работает")
        result = "ok" if app_ok else "fail"
        #Снаружи проверяем, только когда сам журнал жив и не включён жёсткий рубильник:
        #иначе причина известна, а 503 страницы работ — штатный ответ.
        if app_ok and self.hard_switch_on():
            result = "planned"
        elif app_ok:
            site_ok = self.probe_site()
            self._step("site", site_ok, now, "caddy",
                       "Сайт не открывается снаружи", "Сайт снова открывается")
            result = "ok" if site_ok else "fail"
        self._disk()
        return result

    def _disk(self) -> None:
        free = self.disk_free_pct()
        if free is not None and free < DISK_MIN_FREE_PCT:
            self.raise_alarm("disk", "Кончается место на диске",
                             ["Свободно %.1f%%. При нуле встанет журнал и не снимутся копии."
                              % free, "Уборка: bash /root/gb-deploy/maintenance/gb_cleanup.sh"],
                             key="disk", cooldown=6 * 3600)

    def _step(self, what, ok, now, service, title_down, title_up):
        if ok:
            if self.alerted[what]:
                mins = max(1, round((now - self.since[what]) / 60))
                self.raise_alarm("health", title_up, ["Не отвечал около %d мин." % mins],
                                 key="up:%s:%d" % (what, now), cooldown=0)
            self.fails[what], self.alerted[what] = 0, False
            return
        self.fails[what] += 1
        if self.fails[what] == 1:
            self.since[what] = now
        if self.fails[what] == FAILS_TO_ACT:
            self.restart(service)
            self.alerted[what] = True
            self.raise_alarm("health", title_down,
                             ["Три проверки подряд без ответа — сторож перезапустил %s."
                              % service, "Следующее письмо — «снова работает» или «не "
                              "поднимается»."], key="down:%s" % what, cooldown=1800)
        elif self.fails[what] == FAILS_TO_GIVE_UP:
            self.raise_alarm("health", title_down + " и после перезапуска",
                             ["Нужен человек: кнопка «Откат бэкап» → откат выкладки, или "
                              "journalctl -u %s -n 50 на сервере." % service],
                             key="stuck:%s" % what, cooldown=1800)


def _disk_free_pct() -> float | None:
    try:
        u = shutil.disk_usage("/")
    except OSError:
        return None
    return 100.0 * u.free / u.total


def _site_health_url() -> str:
    from . import config
    return (config.SITE_URL or "https://esstu-gradebook.ru").rstrip("/") + "/health"


# ── запуск ──────────────────────────────────────────────────────────────────────────
def _loop(name: str, fn, every: float) -> None:
    while True:
        try:
            fn()
        except Exception as e:      # noqa: BLE001 — сбой одного прохода не роняет поток
            print("[alarm-watch] %s: %s" % (name, e), flush=True)
        time.sleep(every)


def health_tick(health: Health, now: float | None = None) -> str:
    """Минутный проход: проверка здоровья, счёт доступности для письма, досылка тревог."""
    now = time.time() if now is None else now
    result = health.tick(now)
    alarm.record_uptime(result, now)
    alarm.flush_pending()
    return result


def main() -> int:
    from . import config  # noqa: F401 — дочитывает server/.env (SMTP, получатели, секрет)
    trusted = {"keys": read_trusted()}
    if not trusted["keys"]:
        print("[alarm-watch] список своих ключей пуст (%s) — любой вход будет тревогой"
              % TRUSTED_KEYS, flush=True)
    site = _site_health_url()
    health = Health(lambda: _probe(APP_HEALTH), lambda: _probe(site))

    def files_tick():
        trusted["keys"] = read_trusted() or trusted["keys"]
        check_files()

    threads = [threading.Thread(target=follow_journal, args=(trusted,), daemon=True),
               threading.Thread(target=_loop, args=("файлы", files_tick, TICK_S), daemon=True),
               threading.Thread(target=_loop, args=("здоровье", lambda: health_tick(health),
                                                    TICK_S),
                                daemon=True)]
    for t in threads:
        t.start()
    print("[alarm-watch] сторож запущен: своих ключей %d" % len(trusted["keys"]), flush=True)
    while all(t.is_alive() for t in threads):
        time.sleep(10)
    #Поток умер — выходим с ошибкой, systemd поднимет сторожа заново.
    print("[alarm-watch] поток остановился — перезапуск", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
