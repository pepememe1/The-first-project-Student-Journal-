#!/usr/bin/env python3
"""Бан на неделю сканерам, которые уже ходили к нам в разные дни (28.10.2026).

Джейл gb-scanner-week ловит возвращение только с момента установки, а журнал Caddy
помнит прежние визиты. Скрипт читает его (и сжатые старые части) тем же failregex, что
и fail2ban (/etc/fail2ban/filter.d/caddy-scanner.conf — второй копии списка путей нет),
и находит адреса, светившиеся в два и больше разных дня. Исключения (Cloudflare и петля)
берутся из ignoreip самого джейла — тоже без второй копии.

    python3 scanner_repeat_seed.py          показать, кого забанит
    python3 scanner_repeat_seed.py --ban    забанить на неделю (только 80/443)
"""
from __future__ import annotations

import collections
import glob
import gzip
import ipaddress
import json
import re
import subprocess
import sys

FILTER = "/etc/fail2ban/filter.d/caddy-scanner.conf"
JAIL_CONF = "/etc/fail2ban/jail.d/gb-scanner-week.conf"
LOGS = "/var/log/caddy/access*.log*"
JAIL = "gb-scanner-week"
MIN_DAYS = 2


def scanner_regex(path: str = FILTER) -> re.Pattern[str]:
    text = open(path, encoding="utf-8").read()
    line = re.search(r"^failregex\s*=\s*(.+)$", text, re.M)
    if not line:
        raise SystemExit(f"в {path} нет failregex")
    # В нашем фильтре <HOST> стоит внутри "remote_ip":"…", поэтому хватает «до кавычки».
    return re.compile(line.group(1).strip().replace("<HOST>", r'(?P<host>[^"]+)'))


def offenders(rx: re.Pattern[str], paths: list[str]) -> dict[str, set[int]]:
    days: dict[str, set[int]] = collections.defaultdict(set)
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                m = rx.match(raw)
                if not m:
                    continue
                try:
                    ts = float(json.loads(raw).get("ts", 0))
                except ValueError:
                    continue
                days[m.group("host")].add(int(ts // 86400))
    return days


def ignored_nets(path: str = JAIL_CONF) -> list[ipaddress._BaseNetwork]:
    text = open(path, encoding="utf-8").read()
    block = re.search(r"^ignoreip\s*=\s*(.+?)(?=^\S|\Z)", text, re.M | re.S)
    words = block.group(1).split() if block else []
    return [ipaddress.ip_network(w, strict=False) for w in words]


def bannable(host: str, nets: list[ipaddress._BaseNetwork]) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_global and not any(ip in n for n in nets if n.version == ip.version)


def main(argv: list[str]) -> int:
    rx, nets = scanner_regex(), ignored_nets()
    days = offenders(rx, sorted(glob.glob(LOGS)))
    hits = sorted(h for h, d in days.items() if len(d) >= MIN_DAYS and bannable(h, nets))
    print(f"адресов со сканами: {len(days)}, в {MIN_DAYS}+ разных дня: {len(hits)}")
    if "--ban" not in argv or not hits:
        for h in hits:
            print(f"  {h}  дней: {len(days[h])}")
        return 0
    subprocess.run(["fail2ban-client", "set", JAIL, "banip", *hits], check=True)
    print(f"забанены на неделю: {len(hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
