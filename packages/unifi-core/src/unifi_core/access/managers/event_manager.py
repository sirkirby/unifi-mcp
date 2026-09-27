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
from datetime import datetime, timezone
from typing import Any

from unifi_core.access.models.events import event_from_controller, event_identity, with_event_identity
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError, UniFiOperationError

logger = logging.getLogger(__name__)

_GET_EVENT_PAGE_SIZE = 100
_MAX_SCAN_PAGES = 10
MAX_EVENT_QUERY_LIMIT = 5000


def _parse_iso_timestamp(value: str | None, name: str) -> tuple[datetime, str] | tuple[None, None]:
    """Convert an ISO 8601 string into a UTC datetime and RFC 3339 string with fractional seconds preserved.

    Raises ValueError on invalid timestamps.
    """
    if value is None:
        return None, None
    if not isinstance(value, str):
        raise ValueError(f"Invalid timestamp {value!r} for {name}: expected ISO 8601 string")
    text = value.strip()
    if not text:
        return None, None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError(f"Invalid timestamp {value!r} for {name}: expected ISO 8601 string") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt, dt.isoformat().replace("+00:00", "Z")


def _matches_filters(event: Any, door_id: str | None, user_id: str | None) -> bool:
    """Check if an event matches the specified door_id and user_id filters.

    Uses typed event identity from event_from_controller, ensuring hub actors
    (type != 'user') and non-door devices (e.g. readers) are excluded from matches.
    """
    if not door_id and not user_id:
        return True
    norm = event_from_controller(event)
    if door_id and norm.door_id != door_id:
        return False
    if user_id and norm.user_id != user_id:
        return False
    return True


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
            if limit is not None and len(results) >= limit:
                break
            if event.get("_buffered_at", 0) < cutoff:
                continue
            if event_type and event.get("type") != event_type:
                continue
            if door_id and event.get("door_id") != door_id:
                continue
            results.append(event)
        return results

    def clear(self) -> None:
        """Remove all events from the buffer."""
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)


# ---------------------------------------------------------------------------
# EventManager
# ---------------------------------------------------------------------------


# The topics are the Access UI's own syslog Category filters, lowercased and
# snake_cased. All seven verified against a live controller; anything else is
# rejected with CODE_PARAMS_INVALID "no such topic".
#
# "unlocks" is the door history - access.door.unlock and access.dps.status.update
# records, i.e. "Access Granted (Face)" and door open/close. Guessing at names
# like door_openings or access finds nothing, which is what made this look
# unreachable.
SYSTEM_LOG_TOPICS: tuple[str, ...] = (
    "unlocks",
    "access_denial",
    "ring",
    "updates",
    "critical",
    "admin",
    "admin_activity",
)


# The controller's histogram endpoint fails with CODE_SYSTEM_ERROR once the
# request spans too many buckets. Measured live: 100 buckets succeed, 104 and
# above return a 500. Kept well under the observed edge.
_MAX_HISTOGRAM_BUCKETS = 96

# Finest-to-coarsest: the loop below returns the FIRST interval that fits, so
# this order is what makes the chosen bucket the finest one available. Reordering
# it would silently pick the coarsest interval every time.
_HISTOGRAM_INTERVALS = (3600, 7200, 21600, 43200, 86400, 604800)


def _histogram_interval(days: int) -> int:
    """Pick the finest bucket interval whose bucket count the controller accepts.

    A fixed ``interval=3600`` meant the default 7-day window asked for 168
    buckets and always failed, so the tool never worked at its own default.

    Raises ``ValueError`` when no interval fits. Falling back to the coarsest
    one instead would re-create the very failure this guards: 1000 days at one
    bucket per week is 142 buckets, back over the limit. ``days`` is unbounded
    on the MCP tool and the GraphQL resolver, so the bound has to be here.
    """
    span = max(int(days), 1) * 86400
    for interval in _HISTOGRAM_INTERVALS:
        # Ceil, not floor: the controller sees ceil(span/interval) buckets, so
        # flooring let days=673 pass the guard and then ask for 97 against a
        # cap of 96, while the error text still claimed 672 was the limit.
        if -(-span // interval) <= _MAX_HISTOGRAM_BUCKETS:
            return interval
    max_days = _MAX_HISTOGRAM_BUCKETS * _HISTOGRAM_INTERVALS[-1] // 86400
    raise ValueError(
        f"A {int(days)}-day activity window cannot be served: even at one bucket "
        f"per week it exceeds the controller's histogram limit. "
        f"Request at most {max_days} days."
    )


# Delivered by the "*" subscription but deliberately NOT buffered: these are
# high-rate telemetry, and the ring holds only 100 entries. A burst of them
# would evict a door unlock seconds after it happened, so
# get_recent(event_type="access.door.unlock") would come back empty.
_BUFFER_EXCLUDED_EVENTS: frozenset[str] = frozenset(
    {
        "access.data.v2.location.update",
        "access.data.device.location_update_v2",
        "access.data.location.update",
        "access.data.v2.device.update",
        "access.remote_view",
        "access.remote_view.change",
        "access.base.info",
    }
)


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
            # The client dispatches on ``WebsocketMessage.event``, whose values
            # are the controller's dotted names - ``access.logs.add``,
            # ``access.hw.door_bell``, ``access.data.device.remote_unlock`` and
            # friends. Enumerating friendly names like ``door_open`` matched
            # none of them, so every message hit the client's "unhandled" branch
            # and the buffer stayed empty. ``"*"`` is the client's wildcard.
            handlers = {"*": self._on_event}
            # NB: the wildcard also delivers high-rate telemetry frames. See
            # _BUFFER_EXCLUDED_EVENTS - they are logged but not buffered, so a
            # burst cannot evict a just-occurred door event from the ring.
            self._cm.start_websocket(handlers)
            logger.info("[event-mgr] Websocket subscription started.")
        except Exception as e:
            logger.error("[event-mgr] Failed to start websocket: %s", e, exc_info=True)

    @staticmethod
    def _normalize_ws_event(event_data: Any) -> dict[str, Any]:
        """Flatten a websocket message into the buffer's dict shape.

        The client hands the handler a frozen ``WebsocketMessage`` carrying
        ``event`` / ``event_object_id`` / ``door_id``. It has no ``type``,
        ``id``, ``user_id`` or ``timestamp``, so reading those names off it
        buffered ``{"type": "unknown", "door_id": ""}`` - a row that no
        ``get_recent`` filter could match and that carried no time at all.
        """
        raw: dict[str, Any] = {}
        if isinstance(event_data, dict):
            raw = dict(event_data)
        else:
            # Prefer the model's own dump, but only when it really yields a
            # mapping - `hasattr` alone is true for any mock or proxy object.
            dump = getattr(event_data, "model_dump", None)
            if callable(dump):
                try:
                    dumped = dump()
                except Exception:  # pragma: no cover - defensive
                    dumped = None
                if isinstance(dumped, dict):
                    raw = dict(dumped)
            if not raw:
                # Plain object: read both naming schemes, since callers may
                # hand us either the websocket model or a legacy event object.
                raw = {
                    key: getattr(event_data, key, None)
                    for key in ("id", "type", "door_id", "user_id", "timestamp", "event", "event_object_id")
                }

        # Project to a known flat shape rather than carrying the whole dump.
        # `model_dump()` includes the `data` sub-payload (actor display names,
        # credential and device identifiers), and both `access_recent_events`
        # and GET /access/recent-events return buffered rows unprojected - so
        # keeping it would widen what a READ-scoped caller sees.
        normalized: dict[str, Any] = {}
        normalized["type"] = raw.get("type") or raw.get("event") or "unknown"
        normalized["id"] = raw.get("id") or raw.get("event_object_id") or None
        normalized["door_id"] = raw.get("door_id") or None
        normalized["user_id"] = raw.get("user_id") or None
        # Websocket messages are not timestamped by the controller; stamp on
        # arrival so buffered rows can be ordered and aged like any other.
        normalized["timestamp"] = raw.get("timestamp") or datetime.now(timezone.utc).isoformat()
        return normalized

    def _on_event(self, event_data: Any) -> None:
        """Callback invoked for websocket events. Buffers the event."""
        try:
            event_dict = self._normalize_ws_event(event_data)
            if event_dict.get("type") in _BUFFER_EXCLUDED_EVENTS:
                logger.debug("[event-mgr] Skipping high-rate frame %s", event_dict.get("type"))
                return
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
            Event topic to query. One of :data:`SYSTEM_LOG_TOPICS`, which
            mirrors the Access UI's syslog Category filter. ``unlocks`` is the
            door history (grants plus open/close), ``access_denial`` the
            refused attempts. Anything else is rejected with ``no such topic``.
        start:
            ISO 8601 start time filter (e.g. '2026-09-19T00:00:00Z').
            Translated to UTC RFC 3339 ``since`` parameter for the controller.
        end:
            ISO 8601 end time filter (e.g. '2026-09-19T23:59:59Z').
            Translated to UTC RFC 3339 ``until`` parameter for the controller.
        door_id:
            Filter events by door UUID. Enforced client-side using typed event
            models, excluding non-door devices (e.g. readers).
        user_id:
            Filter events by user UUID. Enforced client-side using typed event
            models, excluding hub actors from user matches.
        limit:
            Maximum number of matching events to return (0-5000, default 30).
        """
        if topic not in SYSTEM_LOG_TOPICS:
            raise ValueError(
                f"Unsupported topic {topic!r}. The controller accepts only "
                f"{', '.join(SYSTEM_LOG_TOPICS)}. Door unlock and open/close history "
                "is under 'unlocks'; denied attempts are under 'access_denial'."
            )

        if limit < 0:
            raise ValueError("limit must be zero or greater")
        if limit > MAX_EVENT_QUERY_LIMIT:
            raise ValueError(
                f"limit must not exceed {MAX_EVENT_QUERY_LIMIT}; narrow the time range for larger histories"
            )

        if not self._cm.has_proxy:
            raise UniFiConnectionError("No proxy session available for list_events")

        if limit == 0:
            return []

        since_dt, since_rfc = _parse_iso_timestamp(start, "start")
        until_dt, until_rfc = _parse_iso_timestamp(end, "end")
        if since_dt is not None and until_dt is not None and since_dt > until_dt:
            raise ValueError(f"start time ({since_rfc}) must not be after end time ({until_rfc})")

        door_id_filter = door_id.strip() if isinstance(door_id, str) and door_id.strip() else None
        user_id_filter = user_id.strip() if isinstance(user_id, str) and user_id.strip() else None
        has_client_filters = bool(door_id_filter or user_id_filter)

        try:
            body: dict[str, Any] = {"topic": topic}
            if since_rfc is not None:
                body["since"] = since_rfc
            if until_rfc is not None:
                body["until"] = until_rfc

            collected: list[dict[str, Any]] = []
            page_num = 1
            page_size = _GET_EVENT_PAGE_SIZE if has_client_filters else min(limit, _GET_EVENT_PAGE_SIZE)
            page_budget = (
                _MAX_SCAN_PAGES if has_client_filters else (limit + page_size - 1) // page_size + _MAX_SCAN_PAGES
            )
            scanned_pages = 0
            scanned_events = 0
            seen_identities: set[str] = set()
            seen_page_signatures: set[tuple[str, ...]] = set()
            exhausted = False

            while len(collected) < limit:
                if scanned_pages >= page_budget:
                    break

                path = f"insights/system_log/search?page_size={page_size}&page_num={page_num}&isAccess"
                data = await self._cm.proxy_request("POST", path, json=body)
                scanned_pages += 1

                inner = self._cm.extract_data(data)
                # Response wraps events in {"events": [...], "versions": {...}}
                if isinstance(inner, dict):
                    events = inner.get("events", [])
                elif isinstance(inner, list):
                    events = inner
                else:
                    events = []

                if not isinstance(events, list):
                    events = []

                if not events:
                    exhausted = True
                    break

                page_sig = tuple(str(event_identity(e) or id(e)) for e in events)
                if page_sig in seen_page_signatures:
                    raise UniFiOperationError(
                        f"Cannot establish completeness for access events: controller returned repeated page "
                        f"data on page {page_num}. Narrow the date range using start and end filters."
                    )
                seen_page_signatures.add(page_sig)

                scanned_events += len(events)

                for event in events:
                    if not isinstance(event, dict):
                        continue
                    ident = event_identity(event) or str(event)
                    if ident in seen_identities:
                        continue
                    seen_identities.add(ident)

                    if _matches_filters(event, door_id_filter, user_id_filter):
                        collected.append(with_event_identity(event))
                        if len(collected) >= limit:
                            break

                total = data.get("total") if isinstance(data, dict) else None
                if total is None and isinstance(inner, dict):
                    total = inner.get("total")
                try:
                    total_count = int(total) if total is not None else None
                except (TypeError, ValueError):
                    total_count = None

                if total_count is not None:
                    if len(seen_identities) >= total_count:
                        exhausted = True
                        break
                elif len(events) < page_size:
                    exhausted = True
                    break

                page_num += 1

            if len(collected) < limit and not exhausted:
                raise UniFiOperationError(
                    f"Cannot establish completeness for access events: scanned {scanned_pages} pages "
                    f"({scanned_events} events) and found {len(collected)} matching events, but more events remain "
                    "on the controller. Narrow the date range using start and end filters."
                )

            return collected[:limit]
        except (UniFiConnectionError, UniFiOperationError, ValueError):
            raise
        except Exception as e:
            logger.error("Failed to list events: %s", e, exc_info=True)
            raise

    async def get_event(self, event_id: str) -> dict[str, Any]:
        """Get a single event by ID.

        Searches every available system-log topic and raises
        ``UniFiNotFoundError`` if the event is not found.
        """
        if not event_id:
            raise ValueError("event_id is required")

        if not self._cm.has_proxy:
            raise UniFiConnectionError("No proxy session available for get_event")

        try:
            # The controller has no direct event-by-id endpoint. Search every
            # page of each supported topic so any ID returned by list_events
            # remains addressable, including synthetic system-log IDs.
            for topic in SYSTEM_LOG_TOPICS:
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
            # Clamp once and use the clamped value for the window too: the MCP
            # tool declares `days: int` with no bounds, so days=0 sent an empty
            # window and days=-5 sent since > until, both slipping past the
            # interval guard that had already judged the request servable.
            window_days = max(int(days), 1)
            now = int(time.time())
            since = now - (window_days * 86400)
            path = f"activities/histogram?since={since}&until={now}&interval={_histogram_interval(window_days)}"
            if door_id:
                path += f"&door_id={door_id}"

            data = await self._cm.proxy_request("GET", path)
            return self._cm.extract_data(data)
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to get activity summary: %s", e, exc_info=True)
            raise
