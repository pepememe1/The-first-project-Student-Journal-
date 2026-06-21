"""
sync.py — Сердце offline-first: дельта-синхронизация десктопа с сервером.

Идея:
  • GET  /sync/pull?since=<ISO> — сервер отдаёт все записи, изменённые ПОЗЖЕ since
    (по каждой сущности). Десктоп вливает их в локальный SQLite.
  • POST /sync/push — десктоп присылает свои изменения (накопленные офлайн).
    Сервер применяет их по правилу «последний по времени побеждает» (LWW по
    updated_at). Удаления приходят как deleted=true (надгробия), а не пропажа строк.

Десктоп хранит метку последней успешной синхронизации и в следующий раз тянет
только дельту. Так связь нужна редко и кратко — это и даёт работу «без интернета».

Авторизация: по JWT. Что роль вправе ПУШИТЬ — ограничено (PUSH_SCOPE):
  admin — всё; teacher — занятия и оценки; student — ничего (только тянет).
Тянуть (pull) общий набор данных может любой авторизованный пользователь.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import SYNC_MODELS, User

router = APIRouter(prefix="/sync", tags=["sync"])

#Что какая роль имеет право отправлять на сервер.
PUSH_SCOPE = {
    "admin": set(SYNC_MODELS.keys()),
    "teacher": {"lessons", "grades"},
    "student": set(),
}


def _now() -> str:
    #UTC + смещение (+00:00), с микросекундами. Сервер — ЕДИНЫЙ источник меток
    #времени для синка (см. push): так LWW не зависит от часов клиентов.
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row, model) -> dict:
    return {c.name: getattr(row, c.name) for c in model.__table__.columns}


@router.get("/pull")
def pull(since: str = "", user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    """Отдать изменения позже метки since (пусто — отдать всё)."""
    changes = {}
    for name, model in SYNC_MODELS.items():
        q = db.query(model)
        if since:
            q = q.filter(model.updated_at > since)
        changes[name] = [_row_to_dict(r, model) for r in q.all()]
    return {"server_time": _now(), "changes": changes}


@router.post("/push")
def push(payload: dict = Body(...), user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    """Принять изменения от клиента. Права — по роли (PUSH_SCOPE).

    Метку времени ставит СЕРВЕР (server_ts), а не клиент: так разрешение конфликтов
    не зависит от часов на машинах преподавателей (clock skew). Правило получается
    «последняя успешно дошедшая до сервера правка побеждает».

    Чтобы дельта-синк не гонял все записи каждый цикл, штампуем и применяем только
    те записи, чьё содержимое реально изменилось (клиент шлёт полный снимок)."""
    allowed = PUSH_SCOPE.get(user.role, set())
    changes = (payload or {}).get("changes", {}) or {}
    server_ts = _now()
    applied = {}

    for name, items in changes.items():
        model = SYNC_MODELS.get(name)
        if model is None or name not in allowed or not isinstance(items, list):
            continue
        pk = list(model.__table__.primary_key.columns)[0].name
        cols = {c.name for c in model.__table__.columns}
        #Поля, по которым решаем «изменилось ли»: всё, кроме PK и служебной метки.
        compare_cols = cols - {pk, "updated_at"}
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get(pk)
            if not key:
                continue
            existing = db.get(model, key)
            if existing is None:
                data = {k: v for k, v in item.items() if k in cols}
                data[pk] = key
                data["updated_at"] = server_ts   #метка — серверная
                db.add(model(**data))
                count += 1
                continue
            #Применяем, только если контент реально отличается от хранимого —
            #иначе не трогаем (иначе каждая синхронизация бы «омолаживала» всё).
            changed = any(k in item and getattr(existing, k) != item[k]
                          for k in compare_cols)
            if changed:
                for k, v in item.items():
                    if k in compare_cols:
                        setattr(existing, k, v)
                existing.updated_at = server_ts   #метку обновляет сервер
                count += 1
        applied[name] = count

    db.commit()
    return {"server_time": server_ts, "applied": applied}
