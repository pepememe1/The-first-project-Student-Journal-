"""
auth.py — Авторизация: создание первого администратора и вход (JWT).

Offline-first: пользователей заводит админ в десктоп-проге, они синхронизируются
на сервер уже хешами паролей. Логин через API/сайт работает с теми же паролями.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import LoginIn, TokenOut, BootstrapIn
from ..security import hash_password, verify_password, create_token
from .. import throttle

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> str:
    #UTC + смещение (+00:00) — единый формат меток с клиентом, чтобы LWW-сравнение
    #строк было корректным независимо от часового пояса.
    return datetime.now(timezone.utc).isoformat()


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
    #Детерминированный id (admin:<login>): когда десктоп позже пришлёт админа
    #через /sync, он обновит ЭТУ же строку, а не создаст дубликат.
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
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    """Вход по логину и паролю. Роль — внутри токена.

    Анти-брутфорс: до сверки пароля проверяем, не заблокирован ли этот источник за
    серию неверных попыток (см. throttle). Блокировка по паре (IP, логин) — чтобы
    атакующий не мог запереть вход настоящему пользователю. Неудача увеличивает
    счётчик, удачный вход его сбрасывает."""
    login_str = body.login.strip()
    ip = throttle.client_ip(request)

    left = throttle.seconds_until_unlocked(ip, login_str)
    if left > 0:
        #429 + Retry-After — стандартный сигнал «слишком много попыток, подожди».
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много неудачных попыток. Повторите через {left} с.",
            headers={"Retry-After": str(left)},
        )

    u = db.query(User).filter(
        User.login == login_str, User.deleted == False  # noqa: E712
    ).first()
    if not u or not verify_password(body.password, u.password_hash):
        throttle.register_failure(ip, login_str)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    throttle.register_success(ip, login_str)
    name = u.full_name or f"{u.surname} {u.name}".strip()
    return TokenOut(access_token=create_token(u.login, u.role), role=u.role, name=name)
