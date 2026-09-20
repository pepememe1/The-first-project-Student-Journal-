"""Контракт межпроцессных сигналов WebSocket."""

from __future__ import annotations

import asyncio


def test_broadcast_publishes_only_opaque_refresh_signal(monkeypatch):
    from app.routers.messenger import _common as mod

    delivered = []
    streamed = []
    monkeypatch.setattr(mod, "_participant_ids", lambda db, conv_id: ["u:1", "u:2"])
    monkeypatch.setattr(mod.ws_manager, "emit_users", lambda ids, data: delivered.append((list(ids), data)))
    monkeypatch.setattr(mod.shared_state, "available", lambda: True)
    monkeypatch.setattr(
        mod.shared_state,
        "stream_append",
        lambda channel, payload, maxlen=500: streamed.append((channel, payload, maxlen)) or 1,
    )

    mod._broadcast(object(), "conv:1", "message")

    assert delivered == [(["u:1", "u:2"], {"type": "message", "conversation_id": "conv:1"})]
    assert streamed and streamed[0][0] == "messenger:broadcast"
    event = streamed[0][1]
    assert event["conversation_id"] == "conv:1"
    assert event["kind"] == "message"
    assert event["origin"] == mod.ws_manager._process_id
    assert isinstance(event["event_id"], str) and len(event["event_id"]) == 32
    assert not ({"body", "text", "full_name", "email", "login", "user_id"} & set(event))
    assert streamed[0][2] == 500


def test_shared_consumer_forwards_foreign_event_without_blocking(monkeypatch):
    from app.routers.messenger._common import _WSManager

    manager = _WSManager()
    manager._process_id = "local"
    rows = [[
        {
            "_seq": 4,
            "origin": "other",
            "conversation_id": "conv:1",
            "kind": "changed",
        }
    ], []]

    async def send_users(ids, data):
        forwarded.append((ids, data))
        raise asyncio.CancelledError

    forwarded = []
    monkeypatch.setattr("app.routers.messenger._common.shared_state.stream_read", lambda *args: rows.pop(0) if rows else [])
    monkeypatch.setattr(manager, "_participant_ids_for_broadcast", lambda conv_id: ["u:2"])
    monkeypatch.setattr(manager, "send_users", send_users)
    async def run():
        try:
            await manager._consume_shared()
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert forwarded == [(["u:2"], {"type": "changed", "conversation_id": "conv:1"})]
