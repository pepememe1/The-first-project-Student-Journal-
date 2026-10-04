"""Раздел «Приманки»: кто стучался туда, куда не ходит никто законный (04.10.2026).

🔒 ТОЛЬКО АДМИНИСТРАТОР (`require_admin`) — прямое требование Ярослава. Модератор сюда
не попадает: раздел показывает сырые адреса, а модератору для разбора жалоб в чатах они
не нужны (каждый лишний раздел с ПДн — лишний человек с доступом к ним).

⚠️ ТОЛЬКО ЧТЕНИЕ. Ни снять бан, ни удалить запись отсюда нельзя: след, который можно
стереть из интерфейса, перестаёт быть следом. Бан снимается сроком (сутки) или
перезапуском службы, записи — политикой хранения (`retention.purge_honeypot`).

В программе (десктоп) префикс пересылается на бой (`desktop/local_api._PROXY_PREFIXES`):
локальная копия не видит атак на боевую машину и бодро показала бы «атак нет».
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import honeypot
from ..db import get_db
from ..deps import require_admin
from ..models import User

router = APIRouter(prefix="/web/admin/honeypot", tags=["honeypot"])


@router.get("/summary")
def honeypot_summary(days: int = Query(30, ge=1, le=90),
                     tz: int = Query(480, ge=-720, le=840),
                     _admin: User = Depends(require_admin),
                     db: Session = Depends(get_db)):
    """Итоги, график по дням, топы и источники за период.

    `tz` — смещение часового пояса устройства в минутах (Иркутск = 480): «сегодня» на
    графике — сутки администратора, а не UTC сервера."""
    return honeypot.summary(db, days=days, tz_minutes=tz)


@router.get("/hits")
def honeypot_hits(days: int = Query(30, ge=1, le=90), q: str = Query("", max_length=120),
                  limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
                  _admin: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    """Отдельные срабатывания со всеми подробностями (заголовки, отпечатки, признаки)."""
    return honeypot.list_hits(db, days=days, q=q, limit=limit, offset=offset)


@router.get("/source")
def honeypot_source(fp: str = Query(..., min_length=3, max_length=40),
                    _admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    """Карточка источника по отпечатку адреса (`h:…`).

    ⚠️ Отпечаток — в параметре, а не в пути: в нём двоеточие, а у IPv6-адреса их много;
    путь с ними — лишний повод для разночтений между прокси и роутером."""
    return honeypot.source(db, fp)
