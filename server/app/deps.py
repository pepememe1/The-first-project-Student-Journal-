"""
deps.py — Зависимости FastAPI: текущий пользователь из JWT и проверка ролей.
"""
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .security import decode_token
from .models import User, AuthSession
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


def is_web_client(request: Request) -> bool:
    """Пришёл ли запрос из БРАУЗЕРА (веб-версия), а не из десктоп-проги.

    Веб-клиент помечает себя заголовком `X-Client: web` (см. фронтенд api/client.js).
    Спуфинг этого заголовка максимум даёт доступ уровня СТУДЕНТА (для персонала барьер
    остаётся, см. device_barrier_applies), а студенческий веб-доступ и так открыт —
    поэтому подмена ничего сверх политики не открывает."""
    if request is None:
        return False
    return (request.headers.get("x-client", "") or "").strip().lower() == "web"


def device_barrier_applies(request: Request, role: str) -> bool:
    """Нужно ли для этого запроса проверять одобрение устройства.

    Политика веба (согласована с заказчиком): СТУДЕНТ в браузере входит открыто
    (защита — креды + анти-брутфорс + HTTPS), а ПЕРСОНАЛ (teacher/admin) проходит
    веб-подтверждение устройства — как в десктопе. ДЕСКТОП и любой не-веб клиент —
    жёсткий барьер как прежде (инвариант §6 не ослаблен для них)."""
    if is_web_client(request):
        return role in ("teacher", "admin")
    return True


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
    #ЧЁРНЫЙ СПИСОК / отзыв: токен с jti валиден, только пока его сессия не revoked.
    #Так logout и админская блокировка мгновенно аннулируют украденный/устаревший токен,
    #даже если по подписи и exp он ещё «живой». Токены БЕЗ jti (старого формата) пускаем
    #по подписи+exp до их естественного истечения — обратная совместимость.
    jti = payload.get("jti")
    if jti:
        sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
        if sess is None or sess.revoked:
            raise HTTPException(status_code=401, detail="Сессия завершена или отозвана")
    user = db.query(User).filter(
        User.login == payload.get("sub"), User.deleted == False  #noqa: E712
    ).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    #Даже с валидным токеном доступ закрыт, если устройство не подтверждено: токен мог
    #быть выдан до отзыва доступа или скопирован на чужой ПК. Для веб-студента барьер
    #не применяется (открытый веб-доступ), для персонала и десктопа — применяется.
    if device_barrier_applies(request, user.role):
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
