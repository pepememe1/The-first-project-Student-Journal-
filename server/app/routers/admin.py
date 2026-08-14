"""
admin.py — Служебный мониторинг для админ-панели.

Два эндпоинта, оба ТОЛЬКО для администратора (require_admin):
  • /admin/online — кто сейчас подключён к серверу (активность за ~90 c);
  • /admin/events — журнал последних действий и ошибок сервера (дельта-опрос).

Это служебная информация о работе сервера, поэтому доступ строго админский —
преподавателю и студенту она не отдаётся.
"""
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import User, AuthSession
from ..schemas import RevokeIn
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


@router.get("/sessions")
def sessions(active: bool = Query(True),
             _admin: User = Depends(require_admin),
             db: Session = Depends(get_db)):
    """Список выданных токенов (сессий). active=True — только живые (не отозваны и не
    истёк exp). Админ видит, кто и с какого устройства сейчас имеет доступ — и может
    отозвать токен (POST /admin/sessions/revoke)."""
    now = int(time.time())
    q = db.query(AuthSession)
    if active:
        q = q.filter(AuthSession.revoked == False,  # noqa: E712
                     AuthSession.expires_at > now)
    rows = q.order_by(AuthSession.issued_at.desc()).limit(1000).all()
    out = [{
        "jti": s.jti, "login": s.login, "role": s.role, "kind": s.kind,
        "device_id": s.device_id, "ip": s.ip, "issued_at": s.issued_at,
        "expires_at": s.expires_at, "revoked": bool(s.revoked),
        "expires_in_sec": max(0, int(s.expires_at) - now),
    } for s in rows]
    return {"sessions": out, "count": len(out), "now": now}


@router.post("/sessions/revoke")
def revoke_session(body: RevokeIn,
                   _admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    """Отозвать сессию(и). По `jti` — конкретный токен (и парный к нему); по `login` —
    ВСЕ сессии пользователя (экстренная блокировка / смена ролей / увольнение).

    После отзыва сервер мгновенно перестаёт принимать эти токены (get_current_user
    проверяет AuthSession.revoked), даже если по подписи и exp они ещё живы."""
    revoked = 0
    if body.jti:
        targets = db.query(AuthSession).filter(AuthSession.jti == body.jti).all()
        #гасим и парный токен (access↔refresh), чтобы доступ закрылся целиком
        for s in list(targets):
            if s.pair_jti:
                targets += db.query(AuthSession).filter(
                    AuthSession.jti == s.pair_jti).all()
    elif body.login:
        targets = db.query(AuthSession).filter(
            AuthSession.login == body.login.strip()).all()
    else:
        targets = []
    for s in targets:
        if not s.revoked:
            s.revoked = True
            revoked += 1
    db.commit()
    if revoked:
        #🔒 Экстренная блокировка обязана РВАТЬ живые сокеты, а не только закрывать вход:
        #иначе уволенный сотрудник ещё часами видит, в каких беседах идёт переписка.
        #Логины собираем из самих отозванных строк — по `jti` login заранее неизвестен.
        from .auth import _kick_sockets
        for login in {(s.login or "") for s in targets if s.login}:
            u = db.query(User).filter(User.login == login).first()
            if u is not None:
                _kick_sockets(u.id)
        events.record("warn", "token_revoked",
                      f"админ отозвал сессии ({revoked})",
                      body.login or body.jti, "")
    return {"revoked": revoked}
