"""Per-controller subscriber pool for SSE streaming.

The pool owns at most one manager-callback registration per
(controller_id, product) key. Multiple HTTP clients connecting to the same
stream get separate StreamSubscribers, each with a bounded asyncio.Queue;
the pool's broadcast helper fans out incoming events to all of them.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("unifi-api.streams")


@dataclass
class StreamSubscriber:
    queue: asyncio.Queue[dict] = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    filter_fn: Callable[[dict], bool] | None = None


class SubscriberPool:
    """Per (controller_id, product) registry of HTTP-client subscribers."""

    def __init__(self, queue_maxsize: int = 256) -> None:
        self._pools: dict[tuple[str, str], list[StreamSubscriber]] = {}
        self._unsubs: dict[tuple[str, str], Callable[[], None]] = {}
        self._queue_maxsize = queue_maxsize

    async def attach(self, controller_id: str, product: str, manager: Any) -> StreamSubscriber:
        key = (controller_id, product)
        sub = StreamSubscriber(queue=asyncio.Queue(maxsize=self._queue_maxsize))
        self._pools.setdefault(key, []).append(sub)
        if key not in self._unsubs:
            self._unsubs[key] = manager.add_subscriber(lambda evt, k=key: self._broadcast(k, evt))
            logger.debug(f"[streams] attached manager callback for {key}")
        return sub

    async def detach(self, controller_id: str, product: str, sub: StreamSubscriber) -> None:
        key = (controller_id, product)
        try:
            self._pools.get(key, []).remove(sub)
        except ValueError:
            return
        if not self._pools.get(key):
            unsub = self._unsubs.pop(key, None)
            if unsub is not None:
                try:
                    unsub()
                except Exception:
                    logger.debug(f"[streams] error unsubscribing {key}", exc_info=True)
            self._pools.pop(key, None)
            logger.debug(f"[streams] detached last subscriber for {key}")

    def _broadcast(self, key: tuple[str, str], event: dict) -> None:
        for sub in list(self._pools.get(key, [])):
            if sub.filter_fn is not None and not sub.filter_fn(event):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"[streams] queue full for subscriber on {key}; dropping event")
