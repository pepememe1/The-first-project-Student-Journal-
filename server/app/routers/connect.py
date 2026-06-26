"""
connect.py (router) — Барьер подтверждения подключения устройств.

Две группы эндпоинтов:
  • «Калитка» для НОВОГО ПК (без авторизации — он ещё не одобрен и не вошёл):
    /connect/request, /connect/status, /connect/verify. Барьер device_allowed к ним
    НЕ применяется, иначе одобриться было бы невозможно. Защита — анти-брутфорс по IP
    (throttle) и лимит попыток ввода кода (connect.py).
  • Действия АДМИНИСТРАТОРА (require_admin): /connect/requests, /connect/approve,
    /connect/reject — управление списком запросов из вкладки «Запросы на подключение».

Логика хранения и кодов — в app/connect.py; здесь только HTTP-обвязка.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import User
from ..schemas import ConnectRequestIn, ConnectVerifyIn, DeviceActionIn
from .. import connect, throttle, events

router = APIRouter(prefix="/connect", tags=["connect"])


#Калитка для нового ПК (без авторизации)
@router.post("/request")
def request_connect(body: ConnectRequestIn, request: Request,
                    db: Session = Depends(get_db)):
    """Новый ПК просит доступ. Если устройство УЖЕ одобрено в БД — сразу 'approved'
    (повторный заход с того же ПК не гоняет админа). Иначе кладём в ожидающие, чтобы
    админ увидел запрос с IP."""
    ip = throttle.client_ip(request)
    #Грубый лимит по IP, чтобы нельзя было засыпать список запросами.
    left = throttle.seconds_until_unlocked(ip, "connect")
    if left > 0:
        raise HTTPException(status_code=429,
                            detail=f"Слишком много запросов. Повторите через {left} с.",
                            headers={"Retry-After": str(left)})
    dev = (body.device_id or "").strip()
    if not dev:
        raise HTTPException(status_code=400, detail="Не передан идентификатор устройства")
    if connect.is_approved(db, dev):
        return {"status": "approved"}
    status = connect.submit(dev, ip=ip, hostname=body.hostname)
    throttle.register_failure(ip, "connect")   #каждый запрос «стоит» одной отметки
    events.record("info", "connect_request",
                  f"запрос на подключение устройства ({body.hostname or '—'})",
                  ip=ip)
    return {"status": status}


@router.get("/status")
def connect_status(device_id: str = Query(...)):
    """Опрос статуса запроса клиентом (pending|code_issued|approved|rejected|none)."""
    return {"status": connect.get_status(device_id)}


@router.post("/verify")
def verify_connect(body: ConnectVerifyIn, request: Request,
                   db: Session = Depends(get_db)):
    """Пользователь вводит код, выданный администратором. Успех → заносим устройство
    в одобренные (БД) и отдаём 'approved'; иначе — понятная причина отказа."""
    ip = throttle.client_ip(request)
    ok, reason = connect.verify(body.device_id, body.code)
    if ok:
        connect.add_approved(db, body.device_id, ip=ip,
                             hostname="", approved_by="")
        events.record("info", "connect_verified",
                      "устройство подтверждено кодом", ip=ip)
        return {"status": "approved"}
    msgs = {
        "no_request": "Запрос не найден или код ещё не выдан администратором.",
        "expired": "Срок действия кода истёк — попросите администратора выдать новый.",
        "too_many": "Слишком много неверных попыток — запросите код заново.",
        "bad_code": "Неверный код подтверждения.",
    }
    raise HTTPException(status_code=400, detail=msgs.get(reason, "Не удалось подтвердить код"))


#Действия администратора
@router.get("/requests")
def list_requests(_admin: User = Depends(require_admin)):
    """Активные запросы на подключение (для вкладки «Запросы на подключение»)."""
    rows = connect.list_active()
    #Не отдаём код тем, у кого он ещё не выдан (status=pending) — там его попросту нет.
    return {"requests": rows, "count": len(rows)}


@router.post("/approve")
def approve_request(body: DeviceActionIn, admin: User = Depends(require_admin)):
    """Принять запрос: сервер генерит 6-значный код, админ сообщает его пользователю."""
    code = connect.approve(body.device_id)
    if not code:
        raise HTTPException(status_code=404, detail="Запрос не найден")
    events.record("info", "connect_approved", "запрос на подключение принят (выдан код)",
                  login=admin.login)
    return {"code": code}


@router.post("/reject")
def reject_request(body: DeviceActionIn, admin: User = Depends(require_admin)):
    """Отклонить запрос: убираем из списка, клиент при опросе увидит 'rejected'."""
    if not connect.reject(body.device_id):
        raise HTTPException(status_code=404, detail="Запрос не найден")
    events.record("warn", "connect_rejected", "запрос на подключение отклонён",
                  login=admin.login)
    return {"ok": True}
