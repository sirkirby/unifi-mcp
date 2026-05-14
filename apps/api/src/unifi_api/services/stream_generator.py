"""SSE replay-then-tail stream generator with keepalive."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Callable

from unifi_api.services.streams import StreamSubscriber, SubscriberPool

logger = logging.getLogger("unifi-api.stream-generator")


def format_sse_frame(*, event: dict, product: str, serializer: Any) -> bytes:
    """Render a single SSE frame: event tag, id, json data."""
    payload = serializer.serialize(event)
    eid = event.get("id") or event.get("_buffered_at") or ""
    return (f"event: {product}.event\nid: {eid}\ndata: {json.dumps(payload, default=str)}\n\n").encode()


def format_keepalive() -> bytes:
    """SSE comment-style keepalive frame (proxies don't kill idle connections)."""
    return b": keepalive\n\n"


async def sse_event_stream(
    *,
    manager: Any,
    pool: SubscriberPool,
    controller_id: str,
    product: str,
    serializer: Any,
    last_event_id: str | None = None,
    keepalive_interval: float = 30.0,
    filter_fn: Callable[[dict], bool] | None = None,
) -> AsyncIterator[bytes]:
    """Replay buffer (filtered by last_event_id) then live tail with keepalive.

    Optional filter_fn is applied to both replay-buffer events and live-tail
    events (via the StreamSubscriber.filter_fn honored by SubscriberPool._broadcast).
    """
    sub: StreamSubscriber = await pool.attach(controller_id, product, manager)
    if filter_fn is not None:
        sub.filter_fn = filter_fn
    try:
        # 1. Replay buffer (manager returns most-recent-first; reverse to oldest-first)
        replay = list(reversed(manager.get_recent_from_buffer()))
        if last_event_id:
            seen = False
            tail: list[dict] = []
            for evt in replay:
                if seen:
                    tail.append(evt)
                elif str(evt.get("id")) == str(last_event_id):
                    seen = True
            replay = tail if seen else replay
        if filter_fn is not None:
            replay = [e for e in replay if filter_fn(e)]
        for evt in replay:
            yield format_sse_frame(event=evt, product=product, serializer=serializer)

        # 2. Live tail with keepalive
        while True:
            try:
                evt = await asyncio.wait_for(sub.queue.get(), timeout=keepalive_interval)
                yield format_sse_frame(event=evt, product=product, serializer=serializer)
            except asyncio.TimeoutError:
                yield format_keepalive()
    finally:
        await pool.detach(controller_id, product, sub)
