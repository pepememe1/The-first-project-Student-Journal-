"""Мягкий рубильник обслуживания: включается из админки, админка остаётся доступной.

Пока включён, API отвечает 503 «технические работы» всем, кроме администратора, а
администратору открыт только круг сервера: «Сервер» с мониторингом, приманки, журнал
безопасности, сессии и сам рубильник (решение Ярослава 27.10.2026). Страница сайта и
статика не трогаются — экран «технические работы» рисует сама SPA (MaintenanceScreen.vue).

Жёсткий рубильник — файл-флаг в Caddy (`deploy/maintenance/gb_maintenance.sh`): им
пользуются, когда само приложение лежит или его заменяют.

Состояние — файл рядом с базой: переживает перезапуск службы, а проверка на каждом
запросе стоит один `stat` (содержимое перечитывается, только когда файл сменился).
"""
from __future__ import annotations

import json
import os
import time

#Админу во время работ — только круг сервера. Остальные разделы ждут конца работ:
#правка журнала посреди обновления — ровно то, от чего работы и включают.
ADMIN_PREFIXES = ("/web/admin/server", "/web/admin/honeypot", "/web/admin/audit",
                  "/admin/sessions", "/admin/maintenance")
#Открыто всем: вход (иначе админ не войдёт), свой профиль для оболочки сайта, проверка
#жизни, состояние рубильника, обновления приложений, картинки.
OPEN_PREFIXES = ("/health", "/auth/", "/me", "/app/", "/desktop/updates", "/downloads",
                 "/media")
DEFAULT_MESSAGE = "Идут технические работы. Журнал скоро вернётся — данные в сохранности."

_cache: dict = {"key": None, "state": {"on": False}}


def _path() -> str:
    env = os.environ.get("GRADEBOOK_MAINTENANCE_FILE")
    if env:
        return env
    from .db import DATABASE_URL
    db_path = DATABASE_URL.split("///", 1)[-1] if "///" in DATABASE_URL else ""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)) if db_path else os.getcwd(),
                        ".gradebook_maintenance.json")


def state() -> dict:
    """{on, since, by, message}; нет файла или он битый — выключено."""
    p = _path()
    try:
        st = os.stat(p)
        key = (p, st.st_mtime_ns, st.st_size)
    except OSError:
        return {"on": False}
    if _cache["key"] != key:
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            _cache["state"] = {"on": bool(data.get("on")), "since": data.get("since", 0),
                               "by": data.get("by", ""),
                               "message": (data.get("message") or "").strip() or DEFAULT_MESSAGE}
        except (OSError, ValueError):
            _cache["state"] = {"on": False}
        _cache["key"] = key
    return dict(_cache["state"])


def set_state(on: bool, by: str, message: str = "") -> dict:
    p = _path()
    if on:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"on": True, "since": time.time(), "by": by,
                       "message": (message or "").strip()[:300]}, fh, ensure_ascii=False)
        os.replace(tmp, p)
    else:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    _cache["key"] = None
    return state()


def allowed(path: str, role: str) -> bool:
    """Пропускать ли запрос, пока рубильник включён."""
    if path.startswith(OPEN_PREFIXES):
        return True
    return role == "admin" and path.startswith(ADMIN_PREFIXES)


def public_view() -> dict:
    """Что видит любой посетитель: включено ли, с какого момента и текст для людей."""
    s = state()
    return {"on": s["on"], "since": s.get("since", 0),
            "message": s.get("message", "") if s["on"] else ""}
