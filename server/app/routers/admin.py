"""
admin.py — Служебный мониторинг для админ-панели.

Два эндпоинта, оба ТОЛЬКО для администратора (require_admin):
  • /admin/online — кто сейчас подключён к серверу (активность за ~90 c);
  • /admin/events — журнал последних действий и ошибок сервера (дельта-опрос).

Это служебная информация о работе сервера, поэтому доступ строго админский —
преподавателю и студенту она не отдаётся.
"""
from fastapi import APIRouter, Depends, Query

from ..deps import require_admin
from ..models import User
from .. import events

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/online")
def online(_admin: User = Depends(require_admin)):
    """Пользователи, обращавшиеся к серверу в последние ~90 секунд."""
    rows = events.online()
    return {"online": rows, "count": len(rows), "window_sec": events.ONLINE_WINDOW_SEC}


@router.get("/events")
def events_feed(since: int = Query(0, ge=0),
                limit: int = Query(200, ge=1, le=500),
                _admin: User = Depends(require_admin)):
    """Журнал событий сервера. since — последний полученный id (вернутся только
    более новые события: так консоль обновляется дельтой, не перекачивая весь буфер)."""
    return events.recent(since_id=since, limit=limit)
