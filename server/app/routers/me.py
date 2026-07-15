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
from ..models import User

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
