"""Event management for UniFi Access.

Provides:
- ``EventBuffer`` -- ring buffer for recent Access events received via websocket
- ``EventManager`` -- domain logic for querying, filtering, and streaming events

Dual-path routing: tries the API client (py-unifi-access) first when
available for websocket subscription, then falls back to the proxy session
path for REST event queries.

Proxy paths discovered via browser inspection:
- ``POST insights/system_log/search?page_size={n}&page_num={n}&isAccess`` -- system log search
- ``GET activities/histogram?since={ts}&until={ts}&interval=3600`` -- activity histogram
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from unifi_core.access.models.events import event_identity, with_event_identity
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError

logger = logging.getLogger(__name__)

_GET_EVENT_PAGE_SIZE = 100
_EVENT_SEARCH_TOPICS = (
    "unlocks",
    "access_denial",
    "ring",
    "updates",
    "critical",
    "admin",
    "admin_activity",
)


# ---------------------------------------------------------------------------
# EventBuffer
# ---------------------------------------------------------------------------


class EventBuffer:
    """Ring buffer for recent Access events.

    Events are stored as plain dicts with a ``_buffered_at`` timestamp for
    TTL-based lazy expiration.  The buffer is capped at *max_size* entries;
    once full the oldest entry is silently dropped.

    Thread-safety note: ``deque(maxlen=N)`` is thread-safe for single-producer
    appends on CPython, which matches our use-case (one websocket callback).
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 300) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)
        self._ttl = ttl_seconds

    def add(self, event: dict[str, Any]) -> None:
        """Add *event* to the buffer, stamping it with the current time.

        A shallow copy is made so the caller's original dict is not mutated.
        """
        self._buffer.append({**event, "_buffered_at": time.time()})

    def get_recent(
        self,
        event_type: str | None = None,
        door_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent events matching the supplied filters.

        Events older than the configured TTL are silently skipped (lazy
        expiration).  Results are returned newest-first.
        """
        cutoff = time.time() - self._ttl
        results: list[dict[str, Any]] = []
        for event in reversed(self._buffer):
            if event.get("_buffered_at", 0) < cutoff:
                continue
            if event_type and event.get("type") != event_type:
                continue
            if door_id and event.get("door_id") != door_id:
                continue
            results.append(event)
            if limit and len(results) >= limit:
                break
        return results

    def clear(self) -> None:
        """Remove all events from the buffer."""
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)


# ---------------------------------------------------------------------------
# EventManager
# ---------------------------------------------------------------------------


class EventManager:
    """Domain logic for UniFi Access events.

    Responsibilities:
    - Websocket subscription (via API client when available)
    - Event parsing and buffering
    - REST-based event queries (list, get, activity summary)
    """

    def __init__(self, connection_manager: Any, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._cm = connection_manager
        self._buffer = EventBuffer(
            max_size=int(cfg.get("buffer_size", 100)),
            ttl_seconds=int(cfg.get("buffer_ttl_seconds", 300)),
        )
        self._server: Any | None = None  # FastMCP server reference for future notifications
        self._subscribers: list[Callable[[dict], None]] = []

    # ------------------------------------------------------------------
    # Server / notification wiring
    # ------------------------------------------------------------------

    def set_server(self, server: Any) -> None:
        """Store a reference to the FastMCP server for future notification support."""
        self._server = server

    # ------------------------------------------------------------------
    # Websocket lifecycle
    # ------------------------------------------------------------------

    async def start_listening(self) -> None:
        """Subscribe to the Access websocket for real-time events.

        Uses the API client's websocket support when available.
        Logs a warning if no API client is available (websocket requires API key auth).
        """
        if not self._cm.has_api_client:
            logger.warning(
                "[event-mgr] Cannot start websocket listener: API client not available. "
                "Configure an API key to enable real-time event streaming."
            )
            return

        try:
            handlers = {
                "door_open": self._on_event,
                "door_close": self._on_event,
                "access_granted": self._on_event,
                "access_denied": self._on_event,
                "door_alarm": self._on_event,
            }
            self._cm.start_websocket(handlers)
            logger.info("[event-mgr] Websocket subscription started.")
        except Exception as e:
            logger.error("[event-mgr] Failed to start websocket: %s", e, exc_info=True)

    def _on_event(self, event_data: Any) -> None:
        """Callback invoked for websocket events. Buffers the event."""
        try:
            if isinstance(event_data, dict):
                event_dict = event_data
            else:
                # Convert to dict if it's an object
                event_dict = {
                    "id": getattr(event_data, "id", None),
                    "type": getattr(event_data, "type", "unknown"),
                    "door_id": getattr(event_data, "door_id", None),
                    "user_id": getattr(event_data, "user_id", None),
                    "timestamp": getattr(event_data, "timestamp", None),
                }
            self._buffer.add(event_dict)
            logger.debug("[event-mgr] Buffered event from websocket")
            # Phase 4B: fan out to subscribers
            for cb in list(self._subscribers):
                try:
                    cb(event_dict)
                except Exception:
                    logger.debug("[event-mgr] subscriber callback failed", exc_info=True)
        except Exception:
            logger.debug("[event-mgr] Error processing websocket event", exc_info=True)

    # ------------------------------------------------------------------
    # Buffer access
    # ------------------------------------------------------------------

    def get_recent_from_buffer(
        self,
        event_type: str | None = None,
        door_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent events from the websocket ring buffer."""
        return self._buffer.get_recent(
            event_type=event_type,
            door_id=door_id,
            limit=limit,
        )

    @property
    def buffer_size(self) -> int:
        """Current number of events in the buffer."""
        return len(self._buffer)

    def add_subscriber(self, cb: Callable[[dict], None]) -> Callable[[], None]:
        """Register *cb* to receive every buffered event. Returns unsub."""
        self._subscribers.append(cb)

        def _unsub() -> None:
            try:
                self._subscribers.remove(cb)
            except ValueError:
                pass

        return _unsub

    # ------------------------------------------------------------------
    # REST API queries
    # ------------------------------------------------------------------

    async def list_events(
        self,
        topic: str = "admin",
        start: str | None = None,
        end: str | None = None,
        door_id: str | None = None,
        user_id: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Query events from the Access controller via REST API.

        Uses the proxy path to POST to the system log search endpoint,
        which is the correct Access API discovered via browser inspection.

        Parameters
        ----------
        topic:
            Event topic to query.  Valid values include ``admin`` and
            ``admin_activity``.  The Access API requires this field.
        start:
            ISO 8601 start time filter.
        end:
            ISO 8601 end time filter.
        door_id:
            Filter events by door UUID.
        user_id:
            Filter events by user UUID.
        limit:
            Maximum number of events to return (page size).
        """
        if not self._cm.has_proxy:
            raise UniFiConnectionError("No proxy session available for list_events")

        try:
            # The system_log/search endpoint requires a ``topic`` field.
            body: dict[str, Any] = {"topic": topic}
            if start:
                body["start"] = start
            if end:
                body["end"] = end
            if door_id:
                body["door_id"] = door_id
            if user_id:
                body["user_id"] = user_id

            page_size = limit or 30
            path = f"insights/system_log/search?page_size={page_size}&page_num=1&isAccess"

            data = await self._cm.proxy_request("POST", path, json=body)

            inner = self._cm.extract_data(data)
            # Response wraps events in {"events": [...], "versions": {...}}
            if isinstance(inner, dict):
                events = inner.get("events", [])
            elif isinstance(inner, list):
                events = inner
            else:
                events = []
            return [with_event_identity(event) if isinstance(event, dict) else event for event in events]
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to list events: %s", e, exc_info=True)
            raise

    async def get_event(self, event_id: str) -> dict[str, Any]:
        """Get a single event by ID.

        Searches the system log for the specific event. Raises
        ``ValueError`` if the event is not found.
        """
        if not event_id:
            raise ValueError("event_id is required")

        if not self._cm.has_proxy:
            raise UniFiConnectionError("No proxy session available for get_event")

        try:
            # The controller has no direct event-by-id endpoint. Search every
            # page of each supported topic so any ID returned by list_events
            # remains addressable, including synthetic system-log IDs.
            for topic in _EVENT_SEARCH_TOPICS:
                page_num = 1
                while True:
                    path = f"insights/system_log/search?page_size={_GET_EVENT_PAGE_SIZE}&page_num={page_num}&isAccess"
                    try:
                        data = await self._cm.proxy_request("POST", path, json={"topic": topic})
                    except UniFiConnectionError as exc:
                        # Topic availability can vary by Access version. An
                        # unsupported category must not prevent lookup in the
                        # remaining categories.
                        if "no such topic" in str(exc).lower():
                            logger.debug("Skipping unsupported Access event topic %s", topic)
                            break
                        raise
                    inner = self._cm.extract_data(data)
                    events = (
                        inner.get("events", [])
                        if isinstance(inner, dict)
                        else (inner if isinstance(inner, list) else [])
                    )
                    for ev in events:
                        if isinstance(ev, dict) and event_identity(ev) == event_id:
                            return with_event_identity(ev)

                    total = data.get("total") if isinstance(data, dict) else None
                    if total is None and isinstance(inner, dict):
                        total = inner.get("total")
                    try:
                        total_count = int(total) if total is not None else None
                    except (TypeError, ValueError):
                        total_count = None
                    if not events:
                        break
                    if total_count is not None and page_num * _GET_EVENT_PAGE_SIZE >= total_count:
                        break
                    if total_count is None and len(events) < _GET_EVENT_PAGE_SIZE:
                        break
                    page_num += 1
            raise UniFiNotFoundError("event", event_id)
        except (UniFiConnectionError, UniFiNotFoundError, ValueError):
            raise
        except Exception as e:
            logger.error("Failed to get event %s: %s", event_id, e, exc_info=True)
            raise UniFiNotFoundError("event", event_id) from e

    async def get_activity_summary(
        self,
        door_id: str | None = None,
        days: int = 7,
    ) -> dict[str, Any]:
        """Get aggregated activity summary via the activities histogram endpoint.

        Uses the proxy path to query the activity histogram endpoint
        discovered via browser inspection.

        Parameters
        ----------
        door_id:
            Optional door UUID to scope the summary.
        days:
            Number of days to include in the summary (default 7).
        """
        if not self._cm.has_proxy:
            raise UniFiConnectionError("No proxy session available for get_activity_summary")

        try:
            now = int(time.time())
            since = now - (days * 86400)
            path = f"activities/histogram?since={since}&until={now}&interval=3600"
            if door_id:
                path += f"&door_id={door_id}"

            data = await self._cm.proxy_request("GET", path)
            return self._cm.extract_data(data)
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to get activity summary: %s", e, exc_info=True)
            raise
