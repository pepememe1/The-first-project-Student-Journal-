"""Transactional outbox для коротких серверных событий.

Мессенджер сейчас хранит сообщения в SQLite, а WebSocket-реестр живёт в процессе.
Этому модулю не поручается переписывать запись сообщений: он даёт один маленький
контракт для следующего слоя — добавить событие ДО `commit()` предметной транзакции,
забрать его после перезапуска, повторить публикацию и безопасно удалить старый хвост.

В очередь нельзя передавать текст, ФИО, логин, почту, IP, JWT или секреты. Payload
ограничен небольшим белым списком полей и проверяется до добавления в SQLAlchemy.
Функции не делают `commit()` сами: вызывающий решает границу транзакции, поэтому
откат изменения предметной таблицы откатывает и событие.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .models import EventOutbox


EVENT_SCHEMA_VERSION = 1
DEFAULT_LEASE_SEC = 30
DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_RETENTION_SEC = 7 * 24 * 60 * 60
MAX_PAYLOAD_BYTES = 8 * 1024
MAX_ID_LENGTH = 160

_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")
_ID_RE = re.compile(r"^[^\s@<>]{1,160}$")
_SAFE_PAYLOAD_KEYS = frozenset({
    "conversation_id", "message_id", "user_id", "event_id", "subject_id",
    "group_id", "status", "kind", "count", "version", "cursor", "operation",
    "category",
})
_FORBIDDEN_KEY_PARTS = frozenset({
    "body", "text", "content", "full_name", "email", "login", "password",
    "token", "secret", "jwt", "phone", "ip", "address", "name",
})


@dataclass(frozen=True)
class EventEnvelope:
    """Версионированное событие без пользовательского текста."""

    event_id: str
    event_type: str
    schema_version: int
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]
    created_ts: int


def _check_id(value: str, field: str) -> str:
    value = str(value or "").strip()
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} должен быть коротким непрозрачным идентификатором")
    return value


def _check_value(value: Any, key: str) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, float, str)):
        if isinstance(value, str):
            if len(value) > 256 or "\n" in value or "\r" in value:
                raise ValueError("значение payload слишком длинное или содержит перенос")
        return value
    if isinstance(value, list):
        if len(value) > 32:
            raise ValueError("список payload слишком длинный")
        return [_check_value(item, key) for item in value]
    raise ValueError(f"payload.{key} содержит неподдерживаемый тип")


def _safe_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise TypeError("payload должен быть отображением")
    result: dict[str, Any] = {}
    for key, value in payload.items():
        key = str(key)
        lowered = key.lower()
        if key not in _SAFE_PAYLOAD_KEYS or any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
            raise ValueError(f"поле payload.{key} запрещено контрактом событий")
        result[key] = _check_value(value, key)
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload превышает 8 КБ")
    return result


def make_event(event_type: str, *, aggregate_type: str, aggregate_id: str,
               payload: Mapping[str, Any] | None = None, event_id: str = "",
               created_ts: int | None = None,
               schema_version: int = EVENT_SCHEMA_VERSION) -> EventEnvelope:
    """Собрать и проверить envelope до открытия транзакции БД."""
    event_type = str(event_type or "").strip()
    if not _EVENT_TYPE_RE.fullmatch(event_type):
        raise ValueError("event_type должен быть в формате lower-case.event")
    if int(schema_version) != EVENT_SCHEMA_VERSION:
        raise ValueError("неподдерживаемая версия envelope")
    event_id = _check_id(event_id or uuid4().hex, "event_id")
    aggregate_type = _check_id(aggregate_type, "aggregate_type")
    aggregate_id = _check_id(aggregate_id, "aggregate_id")
    return EventEnvelope(
        event_id=event_id,
        event_type=event_type,
        schema_version=EVENT_SCHEMA_VERSION,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=_safe_payload(payload),
        created_ts=int(time.time() if created_ts is None else created_ts),
    )


def enqueue(db: Session, event: EventEnvelope) -> EventOutbox:
    """Добавить событие в текущую транзакцию идемпотентно по `event_id`.

    Здесь намеренно нет `commit()`: событие должно исчезнуть вместе с бизнес-изменением
    при rollback. Повтор с тем же id и другим содержимым считается ошибкой, иначе один
    и тот же id мог бы тихо обозначать два разных действия.
    """
    row = db.get(EventOutbox, event.event_id)
    if row is not None:
        same = (
            row.event_type == event.event_type
            and row.schema_version == event.schema_version
            and row.aggregate_type == event.aggregate_type
            and row.aggregate_id == event.aggregate_id
            and (row.payload or {}) == event.payload
        )
        if not same:
            raise ValueError("event_id уже связан с другим содержимым")
        return row
    row = EventOutbox(
        id=event.event_id,
        event_type=event.event_type,
        schema_version=event.schema_version,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        payload=event.payload,
        created_ts=event.created_ts,
        available_ts=event.created_ts,
        attempts=0,
        locked_until=0,
        published_ts=0,
        dead_lettered=False,
        last_error="",
    )
    db.add(row)
    return row


def claim_batch(db: Session, *, now: int | None = None, limit: int = 100,
                lease_sec: int = DEFAULT_LEASE_SEC) -> list[EventOutbox]:
    """Атомарно занять пачку событий на короткую публикацию.

    Обновление каждой строки содержит те же условия, что и выборка. Поэтому два
    процесса, увидевшие одного кандидата одновременно, один получит `rowcount == 1`,
    а второй пропустит его без двойного увеличения счётчика попыток.
    """
    now = int(time.time() if now is None else now)
    limit = max(1, min(int(limit), 500))
    lease_until = now + max(1, int(lease_sec))
    candidates = (db.query(EventOutbox.id)
                  .filter(EventOutbox.published_ts == 0,
                          EventOutbox.dead_lettered == False,  # noqa: E712
                          EventOutbox.available_ts <= now,
                          EventOutbox.locked_until <= now)
                  .order_by(EventOutbox.created_ts, EventOutbox.id)
                  .limit(limit).all())
    claimed = []
    for (event_id,) in candidates:
        changed = (db.query(EventOutbox)
                   .filter(EventOutbox.id == event_id,
                           EventOutbox.published_ts == 0,
                           EventOutbox.dead_lettered == False,  # noqa: E712
                           EventOutbox.locked_until <= now)
                   .update({
                       EventOutbox.locked_until: lease_until,
                       EventOutbox.attempts: EventOutbox.attempts + 1,
                   }, synchronize_session=False))
        if not changed:
            continue
        row = db.get(EventOutbox, event_id)
        if row is not None:
            db.refresh(row)
            claimed.append(row)
    return claimed


def ack(db: Session, event_id: str, *, now: int | None = None) -> bool:
    """Подтвердить публикацию. Повторный ACK безопасен."""
    row = db.get(EventOutbox, _check_id(event_id, "event_id"))
    if row is None:
        return False
    row.published_ts = int(time.time() if now is None else now)
    row.locked_until = 0
    row.last_error = ""
    row.dead_lettered = False
    return True


def retry(db: Session, event_id: str, error: str = "", *, now: int | None = None,
          delay_sec: int = 5, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> str:
    """Вернуть событие в очередь или перевести в bounded dead-letter состояние."""
    row = db.get(EventOutbox, _check_id(event_id, "event_id"))
    if row is None:
        return "missing"
    now = int(time.time() if now is None else now)
    row.locked_until = 0
    row.last_error = str(error or "")[:256].replace("\r", " ").replace("\n", " ")
    if int(row.attempts or 0) >= max(1, int(max_attempts)):
        row.dead_lettered = True
        row.available_ts = 0
        return "dead_lettered"
    row.available_ts = now + max(0, int(delay_sec))
    return "retry"


def replay(db: Session, event_id: str, *, now: int | None = None) -> bool:
    """Вернуть опубликованное или dead-letter событие в начало очереди."""
    row = db.get(EventOutbox, _check_id(event_id, "event_id"))
    if row is None:
        return False
    row.published_ts = 0
    row.dead_lettered = False
    row.locked_until = 0
    row.available_ts = int(time.time() if now is None else now)
    row.attempts = 0
    row.last_error = ""
    return True


def purge(db: Session, *, before_ts: int | None = None,
          retention_sec: int = DEFAULT_RETENTION_SEC) -> int:
    """Удалить только завершённый/исчерпанный хвост старше срока хранения."""
    cutoff = int(time.time() if before_ts is None else before_ts) - max(0, int(retention_sec))
    query = db.query(EventOutbox).filter(
        EventOutbox.created_ts < cutoff,
        or_(EventOutbox.published_ts > 0, EventOutbox.dead_lettered == True),  # noqa: E712
    )
    count = query.delete(synchronize_session=False)
    return int(count or 0)


def backlog(db: Session, *, now: int | None = None) -> dict[str, int]:
    """Небольшой безопасный снимок очереди для раздела мониторинга."""
    now = int(time.time() if now is None else now)
    pending = (db.query(EventOutbox).filter(
        EventOutbox.published_ts == 0,
        EventOutbox.dead_lettered == False,  # noqa: E712
    ).count())
    locked = (db.query(EventOutbox).filter(
        EventOutbox.published_ts == 0,
        EventOutbox.dead_lettered == False,  # noqa: E712
        EventOutbox.locked_until > now,
    ).count())
    dead = db.query(EventOutbox).filter(EventOutbox.dead_lettered == True).count()  # noqa: E712
    return {"pending": int(pending), "locked": int(locked), "dead_lettered": int(dead)}


def publish_pending(db: Session, publish, *, now: int | None = None,
                    limit: int = 100, lease_sec: int = DEFAULT_LEASE_SEC,
                    delay_sec: int = 5,
                    max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> dict[str, int]:
    """Опубликовать занятую пачку и зафиксировать ACK/повтор в БД.

    ``publish`` получает только проверенный ``EventEnvelope`` и должен быть
    идемпотентным. Сбой одного события не отменяет ACK уже опубликованных
    элементов: состояние каждой строки сохраняется одной транзакцией после
    обработки пачки.
    """

    claimed = claim_batch(db, now=now, limit=limit, lease_sec=lease_sec)
    result = {"claimed": len(claimed), "published": 0, "retry": 0, "dead_lettered": 0}
    for row in claimed:
        event = EventEnvelope(
            event_id=row.id,
            event_type=row.event_type,
            schema_version=int(row.schema_version),
            aggregate_type=row.aggregate_type,
            aggregate_id=row.aggregate_id,
            payload=dict(row.payload or {}),
            created_ts=int(row.created_ts),
        )
        try:
            publish(event)
        except Exception as exc:
            state = retry(
                db,
                row.id,
                str(exc),
                now=now,
                delay_sec=delay_sec,
                max_attempts=max_attempts,
            )
            result[state] = result.get(state, 0) + 1
            continue
        ack(db, row.id, now=now)
        result["published"] += 1
    db.commit()
    return result
