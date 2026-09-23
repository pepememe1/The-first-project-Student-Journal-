# -*- coding: utf-8 -*-
"""account_sessions.py — раздел «Сессии» у самого человека (4.0).

Список устройств, где открыт его аккаунт: адрес, браузер или программа, последняя
активность, местоположение. Крестик закрывает одну сессию, «Выйти из всех сессий» —
все, кроме текущей. Закрытая сессия отвечает 401 на следующем же запросе: проверка
отзыва живёт в ОДНОЙ точке — `deps.get_current_user` (по `AuthSession.revoked`), и
ничего нового в двести ручек дописывать не пришлось.

━━ ЧТО СЧИТАЕТСЯ «СЕССИЕЙ» ━━
Одна сессия = одна пара access+refresh. Access меняется каждые несколько часов
(`/auth/refresh`), а refresh живёт весь срок входа — поэтому строка списка ключуется
refresh-токеном, а «последняя активность» берётся у текущего access этой пары.
Наружу уходит не `jti`, а его отпечаток: `jti` — половина пропуска, и светить её в
интерфейсе незачем.

━━ МЕСТОПОЛОЖЕНИЕ — ТОЛЬКО ЛОКАЛЬНОЙ БАЗОЙ ━━
Внешние сервисы геолокации НЕ вызываются: адрес человека, отправленный иностранному
сервису, — трансграничная передача ПДн (п. 5.6.1 политики ВСГУТУ «не осуществляется»),
и сторож `test_subprocessors.py` покраснел бы — и правильно. Если на машине положена
база GeoIP (`GRADEBOOK_GEOIP_DB`, формат MaxMind .mmdb) и стоит читающий её пакет —
берём город оттуда. Нет — честное «местоположение неизвестно», а не догадка.
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone

from .models import AuthSession
from . import login_guard

#Как часто обновлять «последнюю активность». Запись на КАЖДЫЙ запрос — это запись на
#каждый запрос, а узкое место SQLite именно запись. Пять минут — точность, которой
#хватает человеку, выясняющему «это я сидел вчера вечером или не я».
TOUCH_EVERY_S = 300


def public_id(jti: str) -> str:
    return hashlib.sha256(("sess|" + (jti or "")).encode("utf-8")).hexdigest()[:24]


def touch(db, sess: AuthSession) -> None:
    """Отметить активность сессии — не чаще раза в `TOUCH_EVERY_S`.

    Вызывается из `get_current_user` ДО тела ручки: коммит здесь не захватывает
    чужих изменений, их ещё нет. Сбой не имеет права ронять запрос — это мониторинг."""
    now = datetime.now(timezone.utc)
    last = sess.last_seen_at or ""
    if last:
        try:
            seen = datetime.fromisoformat(last)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            if (now - seen).total_seconds() < TOUCH_EVERY_S:
                return
        except ValueError:
            pass
    sess.last_seen_at = now.isoformat()
    db.commit()


def ua_label(ua: str, client: str = "") -> str:
    """Человеческое имя устройства по User-Agent. Без библиотек: нужны браузер и система,
    а не версия сборки — «Chrome · Windows» отвечает на вопрос «это мой компьютер?»."""
    client = (client or "").strip().lower()
    ua = ua or ""
    low = ua.lower()
    if client == "android":
        return "Приложение · Android"
    if not client and not ua:
        return "Программа для Windows"
    if "edg/" in low:
        browser = "Edge"
    elif "yabrowser" in low:
        browser = "Яндекс Браузер"
    elif "opr/" in low or "opera" in low:
        browser = "Opera"
    elif "firefox/" in low:
        browser = "Firefox"
    elif "chrome/" in low or "crios/" in low:
        browser = "Chrome"
    elif "safari/" in low:
        browser = "Safari"
    elif "python-requests" in low or "httpx" in low:
        browser = "Программа"
    else:
        browser = "Браузер"
    if "android" in low:
        system = "Android"
    elif "iphone" in low or "ipad" in low:
        system = "iOS"
    elif "windows" in low:
        system = "Windows"
    elif "mac os" in low or "macintosh" in low:
        system = "macOS"
    elif "linux" in low:
        system = "Linux"
    else:
        system = ""
    if not client and browser in ("Программа", "Браузер") and not system:
        return "Программа для Windows"
    return f"{browser} · {system}" if system else browser


def geo_label(ip: str) -> str:
    """Город по адресу — ТОЛЬКО из локальной базы GeoIP. '' — неизвестно.

    ⚠️ Импорт ленивый и необязательный: пакета нет или базы нет — раздел работает, а
    колонка честно говорит «неизвестно». Сети здесь нет ни в одной ветке."""
    path = os.environ.get("GRADEBOOK_GEOIP_DB", "").strip()
    if not ip or not path or not os.path.isfile(path):
        return ""
    try:
        import maxminddb                      # noqa: PLC0415 — необязательный пакет
        with maxminddb.open_database(path) as reader:
            rec = reader.get(ip) or {}
        city = ((rec.get("city") or {}).get("names") or {})
        country = ((rec.get("country") or {}).get("names") or {})
        name_city = city.get("ru") or city.get("en") or ""
        name_country = country.get("ru") or country.get("en") or ""
        return ", ".join(x for x in (name_city, name_country) if x)
    except Exception:                         # noqa: BLE001 — местоположение не условие
        return ""


def _active_refresh_rows(db, login: str) -> list:
    now = int(time.time())
    return (db.query(AuthSession)
            .filter(AuthSession.login == login, AuthSession.kind == "refresh",
                    AuthSession.revoked == False,             # noqa: E712
                    AuthSession.expires_at > now)
            .order_by(AuthSession.issued_at.desc()).all())


def current_refresh_jti(db, access_jti: str) -> str:
    """refresh-токен ТЕКУЩЕЙ сессии (по её access). '' — токен старого формата."""
    if not access_jti:
        return ""
    row = db.query(AuthSession).filter(AuthSession.jti == access_jti).first()
    return (row.pair_jti or "") if row is not None else ""


def list_for(db, login: str, access_jti: str) -> list:
    """Сессии человека для раздела «Сессии». Новые сверху, текущая помечена."""
    current = current_refresh_jti(db, access_jti)
    out = []
    for r in _active_refresh_rows(db, login):
        access = (db.query(AuthSession).filter(AuthSession.jti == r.pair_jti).first()
                  if r.pair_jti else None)
        seen = ((access.last_seen_at if access is not None else "") or r.last_seen_at
                or (access.issued_at if access is not None else "") or r.issued_at or "")
        ip = (access.ip if access is not None and access.ip else r.ip) or ""
        ua = (access.user_agent if access is not None and access.user_agent
              else r.user_agent) or ""
        out.append({
            "id": public_id(r.jti),
            "current": bool(current and r.jti == current),
            "device": ua_label(ua, r.client or ""),
            "ip": ip,
            "location": geo_label(ip),
            "last_seen_at": seen,
            "issued_at": r.issued_at or "",
            "trusted": bool(r.trusted_device_id),
        })
    return out


def _revoke_pair(db, refresh_row: AuthSession) -> None:
    """Закрыть сессию целиком: refresh, ВСЕ его access и доверие устройства.

    ⚠️ Доверие снимается вместе с сессией. «Закрыть сессию» — это реакция на «это не
    я»; оставь устройство доверенным — и тот, кто на нём сидит, вошёл бы снова без
    кода из письма."""
    refresh_row.revoked = True
    for a in db.query(AuthSession).filter(AuthSession.pair_jti == refresh_row.jti).all():
        a.revoked = True
    if refresh_row.pair_jti:
        a = db.query(AuthSession).filter(AuthSession.jti == refresh_row.pair_jti).first()
        if a is not None:
            a.revoked = True
    if refresh_row.trusted_device_id:
        login_guard.revoke_device(db, refresh_row.trusted_device_id)


def revoke_one(db, login: str, sid: str) -> bool:
    for r in _active_refresh_rows(db, login):
        if public_id(r.jti) == sid:
            _revoke_pair(db, r)
            return True
    return False


def revoke_others(db, login: str, access_jti: str) -> int:
    """Закрыть все сессии, КРОМЕ текущей. Возвращает число закрытых.

    ⚠️ Доверие снимается со всех устройств, кроме устройства текущей сессии, — в том
    числе с тех, где человек вышел, но 15-дневный срок ещё идёт: иначе «выйти из всех»
    оставляло бы на чужом компьютере право войти без кода."""
    current = current_refresh_jti(db, access_jti)
    keep_device = ""
    n = 0
    for r in _active_refresh_rows(db, login):
        if current and r.jti == current:
            keep_device = r.trusted_device_id or ""
            continue
        _revoke_pair(db, r)
        n += 1
    login_guard.revoke_all_devices(db, login, keep=keep_device)
    return n
