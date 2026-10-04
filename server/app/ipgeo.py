"""Страна и провайдер по IP-адресу — ИЗ ЛОКАЛЬНОЙ БАЗЫ, без единого внешнего запроса.

Нужно разделу «Приманки» и вечерней сводке: «откуда стучались» читается по стране и
провайдеру (Google Cloud, DigitalOcean, Ростелеком) быстрее, чем по голому адресу.

━━ ПОЧЕМУ НЕ ВНЕШНИЙ СЕРВИС (ip-api, ipinfo и т.п.) ━━
🔒 Отправить адрес иностранному сервису = трансграничная передача персональных данных,
а п. 5.6.1 политики ВСГУТУ её запрещает (IP становится ПДн, когда его можно связать с
человеком, — а студент со сканером из дома ровно такой случай). Поэтому ПОИСК идёт по
файлу на нашем диске, а наружу не уходит ничего.

Источник — публичная база iptoasn.com (`ip2asn-combined.tsv.gz`, лицензия PDDL —
общественное достояние). Её СКАЧИВАНИЕ — запрос В ОДНУ сторону: мы забираем общий файл и
не передаём ни одного адреса. Делает это `python -m app.ipgeo --update` (на бою — сама
вечерняя сводка, если базе больше `MAX_AGE_DAYS`).

━━ ФОРМАТ НА ДИСКЕ ━━
Обычный SQLite (данные публичные, шифровать нечего): таблицы `v4` (целые числа), `v6`
(32 шестнадцатеричных знака — у SQLite нет 128-битных целых, а строки фиксированной
длины сравниваются в том же порядке, что числа) и `asn` (имена провайдеров один раз, а
не на каждую строку диапазона). ~25 МБ, поиск — один индексный запрос.

⚠️ Нет файла — `lookup` отвечает пустыми полями, а не падает: страна — украшение
детектора, а не условие его работы.
"""
from __future__ import annotations

import gzip
import ipaddress
import os
import sqlite3
import sys
import tempfile
import time

SOURCE_URL = "https://iptoasn.com/data/ip2asn-combined.tsv.gz"
#Месяц: распределение адресов по провайдерам меняется медленно, а скачивать 9 МБ каждую
#ночь на машину с одним ядром незачем.
MAX_AGE_DAYS = 30


def db_path() -> str:
    """Где лежит база. Явная настройка → рядом с основной базой → текущий каталог.

    ⚠️ «Рядом с основной базой», а не «в каталоге кода»: после ужесточения юнита
    (`deploy/install.sh`) каталог кода только для чтения, а состояние живёт в
    `/var/lib/gradebook`. Положи файл в код — обновление базы стран упадёт молча."""
    env = os.environ.get("GRADEBOOK_IPASN_DB", "").strip()
    if env:
        return env
    try:
        from .db import DATABASE_URL
        if DATABASE_URL.startswith("sqlite") and "///" in DATABASE_URL:
            main = DATABASE_URL.split("///", 1)[-1]
            folder = os.path.dirname(os.path.abspath(main))
            if folder:
                return os.path.join(folder, "ipasn.db")
    except Exception:      # noqa: BLE001 — без основной базы просто берём каталог процесса
        pass
    return os.path.abspath("ipasn.db")


def status() -> dict:
    """Есть ли база и насколько она свежая — для раздела и сводки."""
    path = db_path()
    if not os.path.isfile(path):
        return {"available": False, "updated": "", "age_days": None}
    mtime = os.path.getmtime(path)
    return {"available": True,
            "updated": time.strftime("%Y-%m-%d", time.gmtime(mtime)),
            "age_days": round((time.time() - mtime) / 86400, 1)}


def _empty() -> dict:
    return {"country": "", "asn": 0, "as_name": ""}


def lookup(ip: str) -> dict:
    """{country, asn, as_name} для адреса. Пусто — базы нет, адрес частный или не найден."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return _empty()
    #Частные и петлевые адреса в публичной базе искать бессмысленно — и их принадлежность
    #мы знаем сами: это локальная сеть или эта же машина.
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return {"country": "", "asn": 0, "as_name": "локальная сеть"}
    path = db_path()
    if not os.path.isfile(path):
        return _empty()
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=2)
    except sqlite3.Error:
        return _empty()
    try:
        if addr.version == 4:
            key = int(addr)
            row = conn.execute("SELECT start, end, asn, cc FROM v4 WHERE start <= ? "
                               "ORDER BY start DESC LIMIT 1", (key,)).fetchone()
        else:
            key = addr.packed.hex()
            row = conn.execute("SELECT start, end, asn, cc FROM v6 WHERE start <= ? "
                               "ORDER BY start DESC LIMIT 1", (key,)).fetchone()
        if not row or key > row[1]:
            return _empty()
        name = conn.execute("SELECT name FROM asn WHERE asn = ?", (row[2],)).fetchone()
        return {"country": row[3] or "", "asn": int(row[2] or 0),
                "as_name": (name[0] if name else "")}
    except sqlite3.Error:
        return _empty()
    finally:
        conn.close()


def build_from_tsv(lines, target: str) -> dict:
    """Собрать базу из строк формата iptoasn. Пишем во ВРЕМЕННЫЙ файл и подменяем целиком.

    ⚠️ Подмена атомарная (`os.replace`): поиск, идущий в этот момент из раздела
    «Приманки», видит либо старую базу, либо новую, но не полусобранную."""
    folder = os.path.dirname(os.path.abspath(target)) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="ipasn-", suffix=".db", dir=folder)
    os.close(fd)
    counts = {"v4": 0, "v6": 0, "asn": 0, "skipped": 0}
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(
            "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"
            "CREATE TABLE v4 (start INTEGER PRIMARY KEY, end INTEGER, asn INTEGER, cc TEXT);"
            "CREATE TABLE v6 (start TEXT PRIMARY KEY, end TEXT, asn INTEGER, cc TEXT);"
            "CREATE TABLE asn (asn INTEGER PRIMARY KEY, name TEXT);")
        names: dict = {}
        v4, v6 = [], []
        for line in lines:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                counts["skipped"] += 1
                continue
            start, end, asn_s, cc, name = parts[:5]
            try:
                asn = int(asn_s)
            except ValueError:
                counts["skipped"] += 1
                continue
            #«Not routed» (AS 0) не храним: такой адрес не может прислать нам запрос, а
            #строк таких пятая часть базы.
            if asn == 0:
                continue
            cc = "" if cc == "None" else cc[:2]
            try:
                a, b = ipaddress.ip_address(start), ipaddress.ip_address(end)
            except ValueError:
                counts["skipped"] += 1
                continue
            if a.version == 4:
                v4.append((int(a), int(b), asn, cc))
            else:
                v6.append((a.packed.hex(), b.packed.hex(), asn, cc))
            names.setdefault(asn, name[:120])
            if len(v4) >= 20000:
                conn.executemany("INSERT OR REPLACE INTO v4 VALUES (?,?,?,?)", v4)
                counts["v4"] += len(v4)
                v4 = []
            if len(v6) >= 20000:
                conn.executemany("INSERT OR REPLACE INTO v6 VALUES (?,?,?,?)", v6)
                counts["v6"] += len(v6)
                v6 = []
        conn.executemany("INSERT OR REPLACE INTO v4 VALUES (?,?,?,?)", v4)
        conn.executemany("INSERT OR REPLACE INTO v6 VALUES (?,?,?,?)", v6)
        counts["v4"] += len(v4)
        counts["v6"] += len(v6)
        conn.executemany("INSERT OR REPLACE INTO asn VALUES (?,?)", names.items())
        counts["asn"] = len(names)
        conn.commit()
    finally:
        conn.close()
    #Пустая база хуже старой: обрыв закачки дал бы файл без строк, и поиск молча перестал
    #бы находить что-либо. Подменяем только осмысленным результатом.
    if counts["v4"] < 1000:
        os.remove(tmp)
        raise RuntimeError("собрано подозрительно мало диапазонов (%d) — база не заменена"
                           % counts["v4"])
    os.replace(tmp, target)
    return counts


def update(url: str = SOURCE_URL) -> dict:
    """Скачать публичную базу и пересобрать локальную. Наружу не уходит ни одного адреса."""
    import urllib.request
    folder = os.path.dirname(db_path()) or "."
    fd, gz = tempfile.mkstemp(prefix="ipasn-", suffix=".tsv.gz", dir=folder)
    os.close(fd)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GradeBookAI-ipgeo/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(gz, "wb") as out:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
        with gzip.open(gz, "rt", encoding="utf-8", errors="replace") as fh:
            return build_from_tsv(fh, db_path())
    finally:
        try:
            os.remove(gz)
        except OSError:
            pass


def ensure_fresh(max_age_days: float = MAX_AGE_DAYS) -> str:
    """Обновить базу, если её нет или она старше срока. Возвращает строку для сводки.

    ⚠️ Ничего не бросает: сводка не имеет права не прийти из-за того, что iptoasn.com
    сегодня не ответил, — она скажет об этом прямо."""
    st = status()
    if st["available"] and (st["age_days"] or 0) < max_age_days:
        return "актуальна (%s)" % st["updated"]
    try:
        counts = update()
        return "обновлена: %d диапазонов IPv4, %d IPv6" % (counts["v4"], counts["v6"])
    except Exception as e:      # noqa: BLE001
        if st["available"]:
            return "устарела (%s), обновить не удалось: %s" % (st["updated"], e)
        return "не загружена, скачать не удалось: %s" % e


if __name__ == "__main__":
    if "--update" in sys.argv:
        print("[ipgeo] база:", db_path())
        print("[ipgeo]", update())
    elif len(sys.argv) > 1:
        for a in sys.argv[1:]:
            print(a, lookup(a))
    else:
        print("python -m app.ipgeo --update | <ip> ...")
        print(status())
