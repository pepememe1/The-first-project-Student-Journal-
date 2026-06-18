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
from datetime import datetime

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import SYNC_MODELS, User

router = APIRouter(prefix="/sync", tags=["sync"])

# Что какая роль имеет право отправлять на сервер.
PUSH_SCOPE = {
    "admin": set(SYNC_MODELS.keys()),
    "teacher": {"lessons", "grades"},
    "student": set(),
}


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


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
    """Принять изменения от клиента. LWW по updated_at; права — по роли."""
    allowed = PUSH_SCOPE.get(user.role, set())
    changes = (payload or {}).get("changes", {}) or {}
    applied = {}

    for name, items in changes.items():
        model = SYNC_MODELS.get(name)
        if model is None or name not in allowed or not isinstance(items, list):
            continue
        pk = list(model.__table__.primary_key.columns)[0].name
        cols = {c.name for c in model.__table__.columns}
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get(pk)
            if not key:
                continue
            inc_ts = item.get("updated_at") or ""
            existing = db.get(model, key)
            if existing is None:
                db.add(model(**{k: v for k, v in item.items() if k in cols}))
                count += 1
            else:
                cur_ts = getattr(existing, "updated_at") or ""
                if inc_ts >= cur_ts:   # последний по времени побеждает
                    for k, v in item.items():
                        if k in cols and k != pk:
                            setattr(existing, k, v)
                    count += 1
        applied[name] = count

    db.commit()
    return {"server_time": _now(), "applied": applied}
