"""
me.py — Личные настройки текущего пользователя (self-scope).

Зачем отдельный эндпоинт, а не общий /sync/push: обобщённый push ограничен по роли
(PUSH_SCOPE — ученик не пушит ничего, преподаватель только оценки/занятия). Чтобы
персональная тема оформления «роумилась» через БД, пользователю нужно уметь менять
СВОЮ строку — но строго свою и только поле prefs (пароль/роль/чужие записи не
трогаются). Это и делает POST /me/prefs: личность берётся из JWT (get_current_user),
поэтому подменить чужой профиль нельзя. Права ролей при этом не ослабляем.

Метку updated_at ставит сервер — как и в /sync/push, чтобы LWW не зависел от часов
клиента, и обновлённый prefs уехал другим устройствам этого же пользователя на pull.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..db import get_db
from ..deps import get_current_user
from ..models import NotifyEvent, PushToken, User

router = APIRouter(prefix="/me", tags=["me"])

#Личные настройки — это тема оформления и мелкие флаги. Ограничиваем размер, чтобы
#авторизованный пользователь не «раздул» свою строку произвольным JSON (защита БД).
_MAX_PREFS_BYTES = 16 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/prefs")
def get_prefs(user: User = Depends(get_current_user)):
    """Текущие личные настройки вошедшего пользователя."""
    return {"prefs": user.prefs or {}}


@router.post("/prefs")
def set_prefs(payload: dict = Body(...), user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Сливает переданные ключи в prefs ТЕКУЩЕГО пользователя (только своя строка).

    Принимаем либо {"prefs": {...}}, либо сразу плоский словарь — обе формы удобны
    клиенту. Существующие ключи prefs сохраняются, новые перекрывают одноимённые."""
    incoming = payload.get("prefs") if isinstance(payload.get("prefs"), dict) else payload
    if not isinstance(incoming, dict):
        incoming = {}
    merged = dict(user.prefs or {})
    merged.update(incoming)
    #Лимит на размер настроек: не даём авторизованному пользователю раздувать БД.
    try:
        size = len(json.dumps(merged, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректные настройки") from None
    if size > _MAX_PREFS_BYTES:
        raise HTTPException(status_code=413, detail="Слишком большой объём настроек")
    user.prefs = merged
    #JSON-столбец меняем «по месту» — подсказываем ORM, что поле грязное, иначе
    #переприсваивание того же объекта может не попасть в UPDATE.
    flag_modified(user, "prefs")
    user.updated_at = _now()
    db.commit()
    return {"ok": True, "prefs": merged, "updated_at": user.updated_at}


#Пуш-уведомления (RuStore Push)
#Токен привязан к КОНКРЕТНОМУ телефону, поэтому живёт в отдельной таблице и НЕ входит
#в синхронизацию: на другие устройства пользователя ему ехать незачем.

@router.post("/push-token")
def register_push_token(payload: dict = Body(...),
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Приложение сообщает свой токен устройства (при запуске и при его обновлении).

    Вызывается КАЖДЫЙ запуск, а не только при первом получении токена: так поле
    last_seen остаётся свежим, и уборка не выбросит живое устройство. RuStore умеет
    менять токен молча — поэтому запись ключуется самим токеном, а не пользователем."""
    token = (payload.get("token") or "").strip()
    if not token or len(token) > 1024:
        raise HTTPException(status_code=400, detail="Нужен непустой token")
    platform = (payload.get("platform") or "android").strip()[:32]
    now = datetime.now(timezone.utc).isoformat()

    row = db.get(PushToken, token)
    if row is None:
        row = PushToken(token=token, created_at=now)
        db.add(row)
    #Логин перезаписываем ВСЕГДА: на одном телефоне мог войти другой пользователь, и
    #слать ему чужие уведомления недопустимо.
    row.login = user.login or ""
    row.platform = platform
    row.last_seen = now
    row.fail_count = 0
    db.commit()
    return {"ok": True}


@router.delete("/push-token")
def delete_push_token(payload: dict = Body(default={}),
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Отписка при выходе из аккаунта. Без неё следующий владелец телефона (или тот же
    человек под другим логином) продолжал бы получать чужие уведомления."""
    token = (payload.get("token") or "").strip()
    q = db.query(PushToken).filter(PushToken.login == (user.login or ""))
    if token:
        q = q.filter(PushToken.token == token)
    removed = q.delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "removed": removed}


@router.get("/events/{event_id}")
def get_notify_event(event_id: str,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Куда открыть экран по нажатому уведомлению.

    Проверка владельца обязательна: id события уезжает в пуш и оседает на телефоне,
    поэтому его нельзя считать секретом. На чужой id отвечаем 404, а НЕ 403 — 403
    подтвердил бы, что такое событие существует, и превратил бы перебор id в способ
    узнать чужую активность."""
    row = db.get(NotifyEvent, event_id)
    if row is None or row.login != (user.login or ""):
        raise HTTPException(status_code=404, detail="Событие не найдено")
    if not row.read_at:
        row.read_at = datetime.now(timezone.utc).isoformat()
        db.commit()
    return {"kind": row.kind, "subject": row.subject, "lesson_id": row.lesson_id,
            "created_at": row.created_at}


@router.get("/events")
def list_unread_events(user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Непрочитанные события — для значка «новое» в интерфейсе (и на сайте тоже,
    там пушей нет, а знать о новых оценках студенту так же полезно)."""
    rows = (db.query(NotifyEvent)
            .filter(NotifyEvent.login == (user.login or ""), NotifyEvent.read_at == "")
            .order_by(NotifyEvent.created_at.desc()).limit(50).all())
    return {"count": len(rows),
            "items": [{"id": r.id, "kind": r.kind, "subject": r.subject,
                       "created_at": r.created_at} for r in rows]}
