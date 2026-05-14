"""SSE stream-generator tests."""

import json
from unittest.mock import MagicMock

import pytest
from unifi_api.services.stream_generator import (
    format_keepalive,
    format_sse_frame,
    sse_event_stream,
)
from unifi_api.services.streams import SubscriberPool


def test_format_sse_frame_shape() -> None:
    frame = format_sse_frame(
        event={"id": "e1", "key": "EVT_LU_Connected", "msg": "client connected"},
        product="network",
        serializer=MagicMock(serialize=lambda e: e),
    )
    text = frame.decode()
    assert "event: network.event\n" in text
    assert "id: e1\n" in text
    assert "data: " in text
    assert text.endswith("\n\n")
    payload_line = next(line for line in text.split("\n") if line.startswith("data: "))
    assert json.loads(payload_line[6:]) == {"id": "e1", "key": "EVT_LU_Connected", "msg": "client connected"}


def test_format_keepalive() -> None:
    assert format_keepalive() == b": keepalive\n\n"


@pytest.mark.asyncio
async def test_sse_event_stream_replays_buffer_then_tails() -> None:
    pool = SubscriberPool()
    mgr = MagicMock()
    mgr.get_recent_from_buffer.return_value = [
        {"id": "e2", "key": "EVT_LU_Disconnected"},
        {"id": "e1", "key": "EVT_LU_Connected"},
    ]
    captured_cb = {}

    def fake_add_sub(cb):
        captured_cb["cb"] = cb
        return MagicMock()

    mgr.add_subscriber.side_effect = fake_add_sub

    serializer = MagicMock(serialize=lambda e: e)

    gen = sse_event_stream(
        manager=mgr,
        pool=pool,
        controller_id="c1",
        product="network",
        serializer=serializer,
        last_event_id=None,
        keepalive_interval=10,
    )
    # First two yields are the buffer replay (oldest-first after reverse)
    frame1 = await gen.__anext__()
    frame2 = await gen.__anext__()
    assert b"id: e1" in frame1
    assert b"id: e2" in frame2

    # Push a live event via the manager callback
    captured_cb["cb"]({"id": "e3", "key": "EVT_LU_Connected"})
    frame3 = await gen.__anext__()
    assert b"id: e3" in frame3

    # Cleanup
    await gen.aclose()


@pytest.mark.asyncio
async def test_sse_event_stream_skips_replay_before_last_event_id() -> None:
    pool = SubscriberPool()
    mgr = MagicMock()
    # Manager returns most-recent-first; reverse → e1, e2, e3 oldest-first
    mgr.get_recent_from_buffer.return_value = [
        {"id": "e3"},
        {"id": "e2"},
        {"id": "e1"},
    ]
    mgr.add_subscriber.return_value = MagicMock()
    serializer = MagicMock(serialize=lambda e: e)
    gen = sse_event_stream(
        manager=mgr,
        pool=pool,
        controller_id="c1",
        product="network",
        serializer=serializer,
        last_event_id="e1",
        keepalive_interval=10,
    )
    frame_a = await gen.__anext__()
    frame_b = await gen.__anext__()
    assert b"id: e2" in frame_a
    assert b"id: e3" in frame_b
    await gen.aclose()


@pytest.mark.asyncio
async def test_sse_event_stream_emits_keepalive_on_idle() -> None:
    pool = SubscriberPool()
    mgr = MagicMock()
    mgr.get_recent_from_buffer.return_value = []
    mgr.add_subscriber.return_value = MagicMock()
    serializer = MagicMock(serialize=lambda e: e)
    gen = sse_event_stream(
        manager=mgr,
        pool=pool,
        controller_id="c1",
        product="network",
        serializer=serializer,
        last_event_id=None,
        keepalive_interval=0.05,
    )
    frame = await gen.__anext__()
    assert frame == b": keepalive\n\n"
    await gen.aclose()
