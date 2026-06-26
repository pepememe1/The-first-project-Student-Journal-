"""
deps.py — Зависимости FastAPI: текущий пользователь из JWT и проверка ролей.
"""
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .security import decode_token
from .models import User
from . import events, throttle, connect


def ensure_device_allowed(request: Request, db: Session):
    """Барьер подтверждения устройства: пускаем только одобренные ПК и сам хост.

    Применяется ко ВСЕМ защищённым эндпоинтам (через get_current_user) и ко входу
    (см. routers/auth.py). Неодобренное устройство получает 403 — оно сначала должно
    пройти подтверждение через /connect/* (вкладка «Запросы на подключение» у админа).
    Сам барьер реализован в connect.device_allowed (хост опознаётся по device_id)."""
    if not connect.device_allowed(request, db):
        raise HTTPException(
            status_code=403,
            detail="Устройство не подтверждено администратором. Запросите подключение "
                   "и введите код, который выдаст администратор.")


def get_current_user(authorization: str = Header(None),
                     request: Request = None,
                     db: Session = Depends(get_db)) -> User:
    """Достаёт пользователя по токену из заголовка Authorization: Bearer <token>."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Недействительный или просроченный токен")
    user = db.query(User).filter(
        User.login == payload.get("sub"), User.deleted == False  # noqa: E712
    ).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    #Даже с валидным токеном доступ закрыт, если устройство не подтверждено: токен мог
    #быть выдан до отзыва доступа или скопирован на чужой ПК.
    ensure_device_allowed(request, db)
    #Отмечаем активность для админского «кто онлайн». Это единая точка — через
    #get_current_user проходит КАЖДЫЙ авторизованный запрос (pull/push/admin).
    #Не критично для запроса, поэтому под try: мониторинг не должен ронять API.
    try:
        ip = throttle.client_ip(request) if request is not None else ""
        name = user.full_name or f"{user.surname} {user.name}".strip()
        events.touch(user.login, user.role, name, ip)
    except Exception:
        pass
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    return user
