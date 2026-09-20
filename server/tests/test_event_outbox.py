"""Контракт долговечной очереди событий: транзакция, повтор, срок и приватность."""
import pytest

from app.db import SessionLocal
from app.event_outbox import (
    DEFAULT_MAX_ATTEMPTS,
    ack,
    backlog,
    claim_batch,
    enqueue,
    make_event,
    publish_pending,
    purge,
    replay,
    retry,
)
from app.models import EventOutbox


def _event(event_id="evt-1", created_ts=100):
    return make_event(
        "messenger.broadcast",
        aggregate_type="conversation",
        aggregate_id="conv:1",
        payload={"conversation_id": "conv:1", "kind": "changed"},
        event_id=event_id,
        created_ts=created_ts,
    )


def test_envelope_rejects_text_and_is_versioned():
    event = _event()
    assert event.schema_version == 1
    assert event.payload == {"conversation_id": "conv:1", "kind": "changed"}
    with pytest.raises(ValueError, match="запрещено"):
        make_event(
            "messenger.broadcast",
            aggregate_type="conversation",
            aggregate_id="conv:1",
            payload={"body": "личное сообщение"},
        )
    with pytest.raises(ValueError, match="версия"):
        make_event("messenger.broadcast", aggregate_type="conversation",
                   aggregate_id="conv:1", schema_version=2)


def test_enqueue_follows_business_transaction_and_is_idempotent(client):
    db = SessionLocal()
    try:
        enqueue(db, _event("evt-rollback"))
        db.rollback()
        assert db.query(EventOutbox).count() == 0

        row = enqueue(db, _event("evt-commit"))
        db.commit()
        again = enqueue(db, _event("evt-commit"))
        assert again.id == row.id
        with pytest.raises(ValueError, match="другим содержимым"):
            enqueue(db, make_event(
                "messenger.broadcast", aggregate_type="conversation",
                aggregate_id="conv:1", payload={"kind": "other"},
                event_id="evt-commit", created_ts=100,
            ))
    finally:
        db.close()


def test_claim_ack_retry_replay_and_bounded_purge(client):
    db = SessionLocal()
    try:
        enqueue(db, _event("evt-old", created_ts=10))
        enqueue(db, _event("evt-live", created_ts=100))
        db.commit()

        claimed = claim_batch(db, now=100, limit=10, lease_sec=30)
        assert [row.id for row in claimed] == ["evt-old", "evt-live"]
        assert all(row.attempts == 1 and row.locked_until == 130 for row in claimed)
        assert backlog(db, now=100) == {"pending": 2, "locked": 2, "dead_lettered": 0}

        assert ack(db, "evt-old", now=101)
        assert retry(db, "evt-live", "temporary", now=100, delay_sec=5) == "retry"
        db.commit()
        assert backlog(db, now=102) == {"pending": 1, "locked": 0, "dead_lettered": 0}
        assert claim_batch(db, now=104) == []
        assert [row.id for row in claim_batch(db, now=105)] == ["evt-live"]

        row = db.get(EventOutbox, "evt-live")
        for _ in range(DEFAULT_MAX_ATTEMPTS - 1):
            retry(db, row.id, "still down", now=200, max_attempts=DEFAULT_MAX_ATTEMPTS)
            row.locked_until = 0
            row.available_ts = 200
            db.flush()
            claim_batch(db, now=200)
            row = db.get(EventOutbox, "evt-live")
        assert retry(db, "evt-live", "last failure", now=200,
                     max_attempts=DEFAULT_MAX_ATTEMPTS) == "dead_lettered"
        db.commit()
        assert backlog(db, now=200)["dead_lettered"] == 1
        assert replay(db, "evt-live", now=201)
        db.commit()
        assert backlog(db, now=201) == {"pending": 1, "locked": 0, "dead_lettered": 0}

        assert purge(db, before_ts=10_000, retention_sec=100) == 1
        db.commit()
        assert db.get(EventOutbox, "evt-old") is None
        assert db.get(EventOutbox, "evt-live") is not None
    finally:
        db.close()


def test_publish_pending_acks_success_and_retries_failure(client):
    db = SessionLocal()
    seen = []
    try:
        enqueue(db, _event("evt-ok", created_ts=100))
        enqueue(db, _event("evt-fail", created_ts=101))
        db.commit()

        def publish(event):
            seen.append(event.event_id)
            if event.event_id == "evt-fail":
                raise RuntimeError("broker unavailable")

        result = publish_pending(db, publish, now=100, delay_sec=10)
        assert result == {"claimed": 1, "published": 1, "retry": 0, "dead_lettered": 0}
        assert seen == ["evt-ok"]
        assert backlog(db, now=100) == {"pending": 1, "locked": 0, "dead_lettered": 0}

        result = publish_pending(db, lambda _event: (_ for _ in ()).throw(RuntimeError("down")),
                                 now=111, delay_sec=0, max_attempts=1)
        assert result["dead_lettered"] == 1
        assert backlog(db, now=111)["dead_lettered"] == 1
    finally:
        db.close()
