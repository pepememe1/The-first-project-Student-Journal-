"""
deps.py — Зависимости FastAPI: текущий пользователь из JWT и проверка ролей.
"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .security import decode_token
from .models import User


def get_current_user(authorization: str = Header(None),
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
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    return user
