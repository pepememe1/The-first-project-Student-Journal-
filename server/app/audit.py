"""
audit.py — Персистентный журнал значимых действий (ФСТЭК №21 / 152-ФЗ).

Дополняет `events.py`: тот держит «живой» хвост в памяти для админ-мониторинга и
теряется при перезапуске; здесь запись ложится в БД (таблица `audit_events`),
только-на-добавление, и переживает рестарт — это доказательная база для разбора
инцидентов и проверок регуляторов.

Главный инвариант: **аудит НИКОГДА не роняет бизнес-операцию**. Любая ошибка записи
журнала гасится (rollback + проглатывание) — недоступность журнала не должна мешать
пользователю работать, но и не должна портить основную транзакцию.

Как использовать: вызывать ПОСЛЕ собственного `db.commit()` эндпоинта (сессия чиста),
либо в ветках-отказах, где несохранённых бизнес-изменений нет:
    audit.log(db, request, actor=user.login, role=user.role,
              action="grade.set", target=student_login, detail="ОП, урок 42")
"""
import time
from datetime import datetime, timezone

from . import events, throttle
from .models import AuditEvent


def _ctx(request):
    """Достать ip и усечённый device-id из запроса (best-effort, без исключений)."""
    ip = device = ""
    try:
        ip = throttle.client_ip(request)
    except Exception:
        pass
    try:
        device = (request.headers.get("X-Device-Id") or "")[:8]
    except Exception:
        pass
    return ip, device


def log(db, request=None, *, actor="", role="", action="", target="",
        detail="", level="info", ip="", device=""):
    """Записать событие в персистентный журнал (и продублировать в live-мониторинг).

    `request` — опционален: если передан, ip/device берутся из него (можно и явно).
    Ничего не возвращает и не бросает — при сбое записи бизнес-логика не страдает."""
    if request is not None:
        rip, rdev = _ctx(request)
        ip = ip or rip
        device = device or rdev
    now = time.time()
    try:
        db.add(AuditEvent(
            created_ts=int(now),
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            actor=actor or "", role=role or "", ip=ip or "", device=device or "",
            action=action or "", target=target or "", detail=detail or "",
            level=level or "info",
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    #Живой мониторинг админки — best-effort, отдельно от БД.
    try:
        msg = action + (f" · {target}" if target else "") + (f" · {detail}" if detail else "")
        events.record(level, action, msg, login=actor, ip=ip)
    except Exception:
        pass


def recent(db, limit=200, action=None, actor=None):
    """Последние записи журнала (для админ-эндпоинта). Свежие сверху."""
    q = db.query(AuditEvent)
    if action:
        q = q.filter(AuditEvent.action == action)
    if actor:
        q = q.filter(AuditEvent.actor == actor)
    limit = max(1, min(int(limit or 200), 1000))
    rows = q.order_by(AuditEvent.id.desc()).limit(limit).all()
    return [{
        "id": r.id, "ts": r.ts, "actor": r.actor, "role": r.role,
        "ip": r.ip, "device": r.device, "action": r.action,
        "target": r.target, "detail": r.detail, "level": r.level,
    } for r in rows]
