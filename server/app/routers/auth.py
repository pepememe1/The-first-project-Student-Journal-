"""
auth.py — Авторизация: создание первого администратора и вход (JWT).

Offline-first: пользователей заводит админ в десктоп-проге, они синхронизируются
на сервер уже хешами паролей. Логин через API/сайт работает с теми же паролями.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import LoginIn, TokenOut, BootstrapIn
from ..security import hash_password, verify_password, create_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> str:
    return datetime.utcnow().isoformat()


@router.post("/bootstrap-admin", response_model=TokenOut)
def bootstrap_admin(body: BootstrapIn, db: Session = Depends(get_db)):
    """Создаёт ПЕРВОГО администратора. Работает только если админа ещё нет —
    безопасно вызывать при первичной настройке сервера."""
    exists = db.query(User).filter(
        User.role == "admin", User.deleted == False  # noqa: E712
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="Администратор уже создан")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Пароль не короче 8 символов")
    login = body.login.strip()
    # Детерминированный id (admin:<login>): когда десктоп позже пришлёт админа
    # через /sync, он обновит ЭТУ же строку, а не создаст дубликат.
    u = User(
        id=f"admin:{login}", role="admin", login=login,
        password_hash=hash_password(body.password), full_name=body.full_name,
        updated_at=_now(),
    )
    db.add(u)
    db.commit()
    return TokenOut(access_token=create_token(u.login, u.role),
                    role=u.role, name=u.full_name)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    """Вход по логину и паролю. Роль — внутри токена."""
    u = db.query(User).filter(
        User.login == body.login.strip(), User.deleted == False  # noqa: E712
    ).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    name = u.full_name or f"{u.surname} {u.name}".strip()
    return TokenOut(access_token=create_token(u.login, u.role), role=u.role, name=name)
