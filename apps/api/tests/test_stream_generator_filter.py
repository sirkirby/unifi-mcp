"""Per-subscriber filter tests for sse_event_stream."""

import asyncio
from unittest.mock import MagicMock

import pytest
from unifi_api.services.stream_generator import sse_event_stream
from unifi_api.services.streams import SubscriberPool


@pytest.mark.asyncio
async def test_filter_fn_drops_replay_events_that_dont_match() -> None:
    pool = SubscriberPool()
    mgr = MagicMock()
    mgr.get_recent_from_buffer.return_value = [
        {"id": "e3", "camera_id": "A"},
        {"id": "e2", "camera_id": "B"},
        {"id": "e1", "camera_id": "A"},
    ]
    mgr.add_subscriber.return_value = MagicMock()
    serializer = MagicMock(serialize=lambda e: e)

    gen = sse_event_stream(
        manager=mgr,
        pool=pool,
        controller_id="c1",
        product="protect",
        serializer=serializer,
        last_event_id=None,
        keepalive_interval=10,
        filter_fn=lambda e: e.get("camera_id") == "A",
    )

    f1 = await gen.__anext__()
    f2 = await gen.__anext__()
    assert b"id: e1" in f1
    assert b"id: e3" in f2
    await gen.aclose()


@pytest.mark.asyncio
async def test_filter_fn_drops_live_events_that_dont_match() -> None:
    pool = SubscriberPool()
    mgr = MagicMock()
    mgr.get_recent_from_buffer.return_value = []
    captured = {}

    def fake_add(cb):
        captured["cb"] = cb
        return MagicMock()

    mgr.add_subscriber.side_effect = fake_add
    serializer = MagicMock(serialize=lambda e: e)

    gen = sse_event_stream(
        manager=mgr,
        pool=pool,
        controller_id="c1",
        product="protect",
        serializer=serializer,
        last_event_id=None,
        keepalive_interval=10,
        filter_fn=lambda e: e.get("camera_id") == "A",
    )

    # Prime the generator so pool.attach runs and add_subscriber registers cb
    first_task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)  # let attach() run
    assert "cb" in captured

    captured["cb"]({"id": "e1", "camera_id": "A"})
    captured["cb"]({"id": "e2", "camera_id": "B"})

    f1 = await asyncio.wait_for(first_task, timeout=1.0)
    assert b"id: e1" in f1
    await gen.aclose()


@pytest.mark.asyncio
async def test_filter_fn_none_means_no_filter() -> None:
    """Default behavior preserved when filter_fn is None."""
    pool = SubscriberPool()
    mgr = MagicMock()
    mgr.get_recent_from_buffer.return_value = [{"id": "e1"}]
    mgr.add_subscriber.return_value = MagicMock()
    serializer = MagicMock(serialize=lambda e: e)

    gen = sse_event_stream(
        manager=mgr,
        pool=pool,
        controller_id="c1",
        product="network",
        serializer=serializer,
        last_event_id=None,
        keepalive_interval=10,
        filter_fn=None,
    )
    frame = await gen.__anext__()
    assert b"id: e1" in frame
    await gen.aclose()
