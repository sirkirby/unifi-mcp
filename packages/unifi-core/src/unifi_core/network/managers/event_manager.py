"""Event Manager for UniFi Network MCP server.

Manages event log and alarm operations using the v2 system-log API
(UniFi Network 10.x+). Falls back to legacy /stat/event for older controllers.
"""

import asyncio
import logging
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

import aiohttp
from aiounifi.models.api import ApiRequest, ApiRequestV2
from aiounifi.models.message import MessageKey

from unifi_core.mac import mac_equal
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")


# ---------------------------------------------------------------------------
# EventBuffer
# ---------------------------------------------------------------------------


class EventBuffer:
    """Ring buffer for recent network events received via websocket.

    Same contract as protect/access EventBuffer. Events are stored as plain
    dicts with a ``_buffered_at`` timestamp for TTL-based lazy expiration.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 300) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)
        self._ttl = ttl_seconds

    @property
    def capacity(self) -> int:
        return self._buffer.maxlen or 0

    def add(self, event: dict[str, Any]) -> None:
        """Add *event* to the buffer, stamping it with the current time."""
        event = {**event, "_buffered_at": time.time()}
        self._buffer.append(event)

    def get_recent(
        self,
        event_type: str | None = None,
        mac: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return most-recent-first events, filtered and TTL-aged."""
        cutoff = time.time() - self._ttl
        out: list[dict[str, Any]] = []
        for event in reversed(self._buffer):
            if limit is not None and len(out) >= limit:
                break
            if event.get("_buffered_at", 0) < cutoff:
                continue
            if event_type and event.get("key") != event_type:
                continue
            if mac and not mac_equal(event.get("mac"), mac):
                continue
            out.append(event)
        return out

    def clear(self) -> None:
        """Remove all events from the buffer."""
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)


# Default categories for the system-log v2 API
_DEFAULT_CATEGORIES = [
    "CLIENT_DEVICES",
    "INTERNET_AND_WAN",
    "POWER",
    "SECURITY",
    "UNIFI_DEVICES",
    "SOFTWARE_UPDATES",
    "UNIFI_ETHERNET_PORTS",
    "VPN",
]

# Default severities
_DEFAULT_SEVERITIES = ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]


class EventManager:
    """Manages event log operations on the UniFi Controller.

    REST query surface (existing) plus websocket buffer + per-subscriber
    fan-out (new in Phase 4B). Mirrors the protect/access EventManager
    contract: ``start_listening`` opens the websocket and registers an
    ``_on_ws_event`` handler with ``aiounifi.Controller.messages`` (the
    upstream MessageHandler subscribe pattern), events are normalized into
    a stable network-event dict shape, written to a TTL ring buffer, and
    fanned out to every callback registered via ``add_subscriber``.
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
        config: dict | None = None,
    ) -> None:
        cfg = config or {}
        self._connection = connection_manager
        self._cm = connection_manager  # alias mirroring protect/access naming
        self._use_v2: bool | None = None  # Auto-detect on first call
        # Why the v2 probe failed, when it did. Newer controllers have removed the
        # legacy paths this falls back to, so a failed probe resurfaces later as a
        # bare 404 from an endpoint the caller never asked for.
        self._v2_probe_error: str | None = None
        self._buffer = EventBuffer(
            max_size=int(cfg.get("buffer_size", 100)),
            ttl_seconds=int(cfg.get("buffer_ttl_seconds", 300)),
        )
        self._subscribers: list[Callable[[dict], None]] = []
        self._ws_unsub: Callable[[], None] | None = None
        self._subscribed_controller: Any = None
        self._ws_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._closed = False
        self._last_error: str | None = None
        self._attach_failures = 0
        self._clock = time.monotonic  # injectable for tests; the loop's clock is untouched
        # The socket currently being attached: aiounifi's connectivity object
        # (it stamps ws_message_received on every frame) and the stamp it held
        # when this attempt began. None outside an attempt (backoff, stopped).
        self._ws_connectivity: Any = None
        self._ws_frame_baseline: Any = None

    # ------------------------------------------------------------------
    # Websocket lifecycle
    # ------------------------------------------------------------------

    # Reconnect backoff bounds, in seconds, and how long a socket must stay
    # attached before the backoff resets (a peer that accepts then closes at
    # once must not be polled every second).
    _BACKOFF_INITIAL = 1.0
    _BACKOFF_MAX = 60.0
    _STABLE_SECONDS = 5.0

    @property
    def is_listening(self) -> bool:
        """True while the background websocket task is alive."""
        return self._ws_task is not None and not self._ws_task.done()

    @property
    def attached(self) -> bool:
        """True only while a frame has been received on the socket now open.

        A running task is not an open socket: a controller that holds the
        handshake, rejects it, or accepts and closes at once keeps the task
        alive and the buffer empty. aiounifi exposes no open/close callback,
        but it stamps ``ws_message_received`` on every frame, and the
        controller sends sync frames continuously, so a stamp that changed
        since the current attempt began is the confirmation (a stamp left by
        an earlier socket does not count). Cleared the moment
        ``start_websocket`` returns or raises, for the whole backoff.
        """
        if not self.is_listening or self._ws_connectivity is None:
            return False
        return getattr(self._ws_connectivity, "ws_message_received", None) != self._ws_frame_baseline

    @property
    def last_error(self) -> str | None:
        """Class (and HTTP status) of the last attach failure, or ``None``."""
        return self._last_error

    async def start_listening(self) -> None:
        """Subscribe to event/alert messages and run the websocket in the background.

        aiounifi exposes events through ``Controller.messages`` (a
        ``MessageHandler``); ``messages.subscribe(callback, message_filter)``
        returns an unsubscribe callable. ``Controller.start_websocket()`` is
        the blocking receive loop with no reconnect of its own, so it runs in
        a task that reconnects with backoff, re-subscribes when a reconnect
        replaces the Controller object, and re-logs-in when the handshake is
        rejected (aiounifi reuses the cookie captured at login). Idempotent.
        """
        if self.is_listening:
            return
        if self._closed:
            # Stopped by its owner (shutdown, or the API dropping the manager
            # on credential rotation); a late caller must not revive it.
            logger.debug("[network-event-mgr] start_listening ignored on a stopped manager")
            return
        self._stopping = False
        self._subscribe(self._cm.controller)
        self._ws_task = asyncio.create_task(self._run_websocket(), name="network-event-websocket")
        self._ws_task.add_done_callback(self._on_task_done)
        logger.info("[network-event-mgr] websocket listener started")

    async def stop_listening(self) -> None:
        """Stop the background websocket task and drop the subscription.

        The subscription is released in ``finally``: a cancellation aimed at
        the stopping caller (a second interrupt at shutdown) still propagates,
        but never leaves the controller holding our callback.
        """
        self._stopping = True
        self._closed = True
        task, self._ws_task = self._ws_task, None
        try:
            if task is not None and not task.done():
                current = asyncio.current_task()
                cancelling_before = current.cancelling() if current is not None else 0
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    # Re-raise when the cancellation was aimed at the caller,
                    # not at the task we just cancelled.
                    if current is not None and current.cancelling() > cancelling_before:
                        raise
                except Exception as exc:
                    logger.error("[network-event-mgr] websocket loop ended with %s", type(exc).__name__)
                    logger.debug("[network-event-mgr] websocket loop failure", exc_info=exc)
        finally:
            self._unsubscribe()
            self._socket_closed()
            self._last_error = None
            if task is not None:
                logger.info("[network-event-mgr] websocket listener stopped")

    def _socket_closed(self) -> None:
        """Forget the current attempt: nothing is attached until the next frame."""
        self._ws_connectivity = None
        self._ws_frame_baseline = None

    @staticmethod
    def _on_task_done(task: "asyncio.Task[None]") -> None:
        """Nothing in the loop should escape; if something does, say so now."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("[network-event-mgr] websocket task died: %s", type(exc).__name__)
            logger.debug("[network-event-mgr] websocket task failure", exc_info=exc)

    def _subscribe(self, controller: Any) -> None:
        """Bind the message subscription to *controller*, releasing any previous one."""
        if controller is None or controller is self._subscribed_controller:
            return
        self._unsubscribe()
        self._ws_unsub = controller.messages.subscribe(
            self._on_ws_event,
            (MessageKey.EVENT, MessageKey.ALERT),
        )
        self._subscribed_controller = controller

    def _unsubscribe(self) -> None:
        if self._ws_unsub is not None:
            try:
                self._ws_unsub()
            except Exception:
                logger.debug("[network-event-mgr] error unsubscribing", exc_info=True)
        self._ws_unsub = None
        self._subscribed_controller = None

    @staticmethod
    def _is_rejected_handshake(exc: BaseException) -> bool:
        return isinstance(exc, aiohttp.WSServerHandshakeError) and exc.status in (401, 403)

    @staticmethod
    def _describe(exc: BaseException) -> str:
        """Class name, plus the HTTP status of a handshake error or the text of
        our own ConnectionError; never aiounifi's messages, which quote the URL."""
        if isinstance(exc, aiohttp.WSServerHandshakeError):
            return f"{type(exc).__name__} (HTTP {exc.status})"
        if type(exc) is ConnectionError:
            return f"ConnectionError ({exc})"
        return type(exc).__name__

    async def _run_websocket(self) -> None:
        """Keep the websocket attached until stopped.

        The loop never spins against the controller: while the connection
        manager's reconnect circuit is open it only sleeps, and every failure
        backs off (doubling to ``_BACKOFF_MAX``) until an attach succeeds. A
        rejected handshake (401/403) triggers one re-login per attempt, since
        aiounifi reuses the cookie captured at login.
        """
        backoff = self._BACKOFF_INITIAL
        while not self._stopping:
            needs_reauth = False
            try:
                # The circuit half-opens on a timer; ``reconnect_blocked``
                # stays latched until a login succeeds, so it must not gate
                # the retry or an expired cool-down would never be tried.
                if self._cm.reconnect_cooldown_active:
                    raise ConnectionError("reconnect circuit open")
                if not await self._cm.ensure_connected():
                    raise ConnectionError("controller not connected")
                controller = self._cm.controller
                if controller is None:
                    raise ConnectionError("controller not available")
                self._subscribe(controller)
                self._last_error = None
                attached_at = self._clock()
                self._ws_connectivity = getattr(controller, "connectivity", None)
                self._ws_frame_baseline = getattr(self._ws_connectivity, "ws_message_received", None)
                try:
                    await controller.start_websocket()
                finally:
                    # Returned or raised: the socket is closed either way, and
                    # nothing is attached until the next attempt's first frame.
                    self._socket_closed()
                # Closed by the peer without an error. Only a socket that
                # stayed up counts as a success; an accept-then-close is a
                # failed attach and backs off like one.
                if self._clock() - attached_at < self._STABLE_SECONDS:
                    raise ConnectionError("closed by the controller before it was stable")
                backoff = self._BACKOFF_INITIAL
                self._attach_failures = 0
                logger.info("[network-event-mgr] websocket closed by the controller; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = self._describe(exc)
                self._attach_failures += 1
                needs_reauth = self._is_rejected_handshake(exc)
                logger.debug("[network-event-mgr] websocket attach failed", exc_info=True)
                if backoff >= self._BACKOFF_MAX and self._attach_failures == self._failures_at_max_backoff():
                    logger.error(
                        "[network-event-mgr] websocket has not attached after %d attempts (%s); "
                        "unifi_recent_events will stay empty until it does",
                        self._attach_failures,
                        self._last_error,
                    )
                else:
                    logger.warning(
                        "[network-event-mgr] websocket attach failed (%s); retrying in %.0fs",
                        self._last_error,
                        backoff,
                    )
            if self._stopping:
                break
            if needs_reauth:
                await self._reauthenticate_quietly()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._BACKOFF_MAX)

    def _failures_at_max_backoff(self) -> int:
        """The attempt count at which backoff first reaches its cap (escalate once)."""
        steps, value = 0, self._BACKOFF_INITIAL
        while value < self._BACKOFF_MAX:
            value *= 2
            steps += 1
        return steps + 1

    async def _reauthenticate_quietly(self) -> None:
        """Re-login after a rejected handshake; its own failure must not end the loop."""
        try:
            ok = await self._cm.reauthenticate()
        except Exception as exc:
            logger.warning("[network-event-mgr] re-authentication failed: %s", type(exc).__name__)
            return
        if not ok:
            logger.warning("[network-event-mgr] re-authentication failed; the reconnect circuit may be open")

    # ------------------------------------------------------------------
    # Event ingestion + fan-out
    # ------------------------------------------------------------------

    def _on_ws_event(self, event_obj: Any) -> None:
        """Normalize, buffer, and fan out a websocket event.

        Accepts either an aiounifi ``Message`` (with ``.data``), a raw dict,
        or anything exposing a ``.raw`` attribute. Subscribers receive the
        buffered dict (with ``_buffered_at`` stamped).
        """
        try:
            event = self._normalize_event(event_obj)
            if event is None:
                return
            self._buffer.add(event)
            stored = next(iter(self._buffer.get_recent(limit=1)), event)
            for cb in list(self._subscribers):
                try:
                    cb(stored)
                except Exception:
                    logger.debug(
                        "[network-event-mgr] subscriber callback failed",
                        exc_info=True,
                    )
        except Exception:
            logger.debug("[network-event-mgr] error processing ws event", exc_info=True)

    def _normalize_event(self, event_obj: Any) -> dict | None:
        """Convert an aiounifi Message / dict / Event into the stable shape."""
        if isinstance(event_obj, dict):
            raw = event_obj
        else:
            # aiounifi.Message exposes the event payload via `.data`
            raw = getattr(event_obj, "data", None)
            if raw is None:
                raw = getattr(event_obj, "raw", None)
        if not isinstance(raw, dict):
            return None
        return {
            "id": raw.get("_id") or raw.get("id"),
            "key": raw.get("key"),
            "msg": raw.get("msg"),
            "severity": raw.get("severity"),
            "time": raw.get("time"),
            "mac": raw.get("user") or raw.get("ap") or raw.get("sw") or raw.get("gw"),
            "ip": raw.get("ip"),
        }

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def add_subscriber(self, cb: Callable[[dict], None]) -> Callable[[], None]:
        """Register *cb* to receive every event after it is buffered.

        Returns an unsubscribe callable.
        """
        self._subscribers.append(cb)

        def _unsub() -> None:
            try:
                self._subscribers.remove(cb)
            except ValueError:
                pass

        return _unsub

    # ------------------------------------------------------------------
    # Buffer access
    # ------------------------------------------------------------------

    def get_recent_from_buffer(
        self,
        event_type: str | None = None,
        mac: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        return self._buffer.get_recent(event_type=event_type, mac=mac, limit=limit)

    @property
    def buffer_size(self) -> int:
        """Current occupancy of the ring buffer (not its capacity)."""
        return len(self._buffer)

    @property
    def buffer_capacity(self) -> int:
        return self._buffer.capacity

    async def _detect_api_version(self) -> bool:
        """Detect whether the controller supports the v2 system-log API.

        Returns True for v2, False for legacy.
        """
        try:
            now_ms = int(time.time() * 1000)
            one_hour_ago_ms = now_ms - (3600 * 1000)

            api_request = ApiRequestV2(
                method="post",
                path="/system-log/count",
                data={
                    "timestampFrom": one_hour_ago_ms,
                    "timestampTo": now_ms,
                    "severities": _DEFAULT_SEVERITIES,
                    "categories": _DEFAULT_CATEGORIES,
                    "type": "GENERAL",
                },
            )
            await self._connection.request(api_request)
            logger.info("[events] Using v2 system-log API")
            self._v2_probe_error = None
            return True
        except Exception as probe_error:
            # Log why, not just that. A probe that fails for a reason other than
            # "this controller predates v2" sends every later call down a legacy
            # path that modern controllers answer with 404, and without this the
            # only visible symptom is that 404.
            self._v2_probe_error = f"{type(probe_error).__name__}: {probe_error}"
            logger.warning(
                "[events] v2 system-log probe failed, falling back to legacy /stat/event API: %s",
                probe_error,
            )
            return False

    def _explain_legacy_failure(self, endpoint: str, error: Exception) -> Exception:
        """Attach the v2 probe failure to a legacy error, when it caused the fallback.

        Returns the original error untouched on a controller that legitimately has
        no v2 API — there is nothing extra to say about that case.
        """
        if not self._v2_probe_error:
            return error
        return RuntimeError(
            f"{endpoint} failed ({error}). This controller was put on the legacy events API "
            f"because the v2 system-log probe failed: {self._v2_probe_error}. "
            "On current UniFi Network versions the legacy endpoint no longer exists, so the "
            "underlying problem is the failed v2 probe, not the missing legacy path."
        )

    async def _ensure_api_version(self) -> None:
        """Detect API version on first call."""
        if self._use_v2 is None:
            self._use_v2 = await self._detect_api_version()

    async def get_events(
        self,
        within: int = 24,
        limit: int = 100,
        start: int = 0,
        event_type: Optional[str] = None,
        categories: Optional[List[str]] = None,
        severities: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get events from the controller.

        Uses the v2 system-log API on modern controllers (10.x+),
        falls back to legacy /stat/event for older versions.

        Args:
            within: Hours to look back (default 24).
            limit: Maximum number of events to return (default 100).
            start: Offset for pagination (default 0).
            event_type: Optional filter for specific event type.
            categories: Optional list of categories to filter (v2 only).
            severities: Optional list of severities to filter (v2 only).

        Returns:
            List of event objects.
        """
        await self._ensure_api_version()

        if self._use_v2:
            return await self._get_events_v2(within, limit, start, event_type, categories, severities)
        return await self._get_events_legacy(within, limit, start, event_type)

    async def _get_events_v2(
        self,
        within: int,
        limit: int,
        start: int,
        event_type: Optional[str],
        categories: Optional[List[str]],
        severities: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        """Get events using the v2 system-log API."""
        if limit <= 0:
            return []

        try:
            now_ms = int(time.time() * 1000)
            from_ms = now_ms - (within * 3600 * 1000)
            page_size = min(limit, 100)
            page_number = max(start, 0) // page_size
            page_offset = max(start, 0) % page_size

            payload: Dict[str, Any] = {
                "timestampFrom": from_ms,
                "timestampTo": now_ms,
                "severities": severities or _DEFAULT_SEVERITIES,
                "categories": categories or _DEFAULT_CATEGORIES,
                "type": "GENERAL",
                "pageNumber": page_number,
                "pageSize": page_size,
                "searchText": "",
            }

            if event_type:
                # ``keys`` is the controller's exact event-key filter. ``searchText``
                # searches rendered message text and silently returns the wrong result
                # for values such as CLIENT_DISCONNECTED_WIRELESS_2.
                payload["keys"] = [event_type]

            events: List[Dict[str, Any]] = []
            while len(events) < limit + page_offset:
                payload["pageNumber"] = page_number
                api_request = ApiRequestV2(
                    method="post",
                    path="/system-log/all",
                    data=payload.copy(),
                )
                response = await self._connection.request(api_request)

                envelope: Any = response
                if isinstance(response, list) and response and isinstance(response[0], dict) and "data" in response[0]:
                    envelope = response[0]

                if isinstance(envelope, dict):
                    page = envelope.get("data", envelope.get("logs", []))
                    total_pages = envelope.get("total_page_count", envelope.get("totalPageCount"))
                elif isinstance(envelope, list):
                    page = envelope
                    total_pages = None
                else:
                    page = []
                    total_pages = None

                if not isinstance(page, list) or not page:
                    break
                events.extend(event for event in page if isinstance(event, dict))
                page_number += 1

                if isinstance(total_pages, int) and page_number >= total_pages:
                    break
                if total_pages is None and len(page) < page_size:
                    break

            return events[page_offset : page_offset + limit]
        except Exception as e:
            logger.error("Error getting events (v2): %s", e)
            raise

    async def _get_events_legacy(
        self,
        within: int,
        limit: int,
        start: int,
        event_type: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Get events using the legacy /stat/event API."""
        try:
            payload: Dict[str, Any] = {
                "within": within,
                "_limit": min(limit, 3000),
                "_start": start,
            }
            if event_type:
                payload["type"] = event_type

            api_request = ApiRequest(method="post", path="/stat/event", data=payload)
            response = await self._connection.request(api_request)

            if isinstance(response, list):
                return response
            if isinstance(response, dict):
                return response.get("data", [])
            return []
        except Exception as e:
            logger.error("Error getting events (legacy): %s", e)
            raise self._explain_legacy_failure("/stat/event", e) from e

    async def get_alarms(
        self,
        archived: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get active alarms/alerts from the controller.

        Uses v2 system-log/critical on modern controllers,
        falls back to legacy /stat/alarm for older versions.
        """
        await self._ensure_api_version()

        if self._use_v2:
            return await self._get_alarms_v2(archived, limit)
        return await self._get_alarms_legacy(archived, limit)

    async def _get_alarms_v2(self, archived: bool, limit: int) -> List[Dict[str, Any]]:
        """Get alarms using the v2 system-log/critical API."""
        try:
            now_ms = int(time.time() * 1000)
            # Look back 30 days for alarms
            from_ms = now_ms - (30 * 24 * 3600 * 1000)

            payload: Dict[str, Any] = {
                "timestampFrom": from_ms,
                "timestampTo": now_ms,
                "severities": ["HIGH", "VERY_HIGH"],
                "categories": _DEFAULT_CATEGORIES,
                "type": "GENERAL",
                "pageNumber": 0,
                "pageSize": min(limit, 100),
                "searchText": "",
            }

            api_request = ApiRequestV2(
                method="post",
                path="/system-log/critical",
                data=payload,
            )
            response = await self._connection.request(api_request)

            # V2 response comes as [{"data": [...], "total_element_count": N}] or {"data": [...]}
            if isinstance(response, list) and response and isinstance(response[0], dict) and "data" in response[0]:
                return response[0]["data"][:limit]
            if isinstance(response, dict):
                return response.get("data", response.get("logs", []))[:limit]
            if isinstance(response, list):
                return response[:limit]
            return []
        except Exception as e:
            logger.error("Error getting alarms (v2): %s", e)
            raise

    async def _get_alarms_legacy(self, archived: bool, limit: int) -> List[Dict[str, Any]]:
        """Get alarms using the legacy /stat/alarm API."""
        try:
            path = "/stat/alarm"
            if archived:
                path = "/stat/alarm?archived=true"

            api_request = ApiRequest(method="get", path=path)
            response = await self._connection.request(api_request)

            alarms = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
            return alarms[:limit]
        except Exception as e:
            logger.error("Error getting alarms (legacy): %s", e)
            raise self._explain_legacy_failure("/stat/alarm", e) from e

    def get_event_type_prefixes(self) -> List[Dict[str, str]]:
        """Get legacy event type prefixes for backward compatibility."""
        return [
            {"prefix": "EVT_SW_", "description": "Switch events"},
            {"prefix": "EVT_AP_", "description": "Access Point events"},
            {"prefix": "EVT_GW_", "description": "Gateway events"},
            {"prefix": "EVT_LAN_", "description": "LAN events"},
            {"prefix": "EVT_WU_", "description": "WLAN User events (connect/disconnect)"},
            {"prefix": "EVT_WG_", "description": "WLAN Guest events"},
            {"prefix": "EVT_IPS_", "description": "IPS/IDS security events"},
            {"prefix": "EVT_AD_", "description": "Admin events"},
            {"prefix": "EVT_DPI_", "description": "Deep Packet Inspection events"},
        ]

    async def get_event_types(self) -> List[Dict[str, Any]]:
        """Get recently observed exact event keys for filtering.

        Modern controllers expose exact enum keys rather than the legacy
        ``EVT_*`` prefix catalog, so discover usable values from recent events.
        """
        events = await self.get_events(within=168, limit=1000)
        counts: Dict[str, int] = {}
        for event in events:
            key = event.get("key") or event.get("event")
            if isinstance(key, str) and key:
                counts[key] = counts.get(key, 0) + 1

        return [
            {
                "key": key,
                # Retain the old field for consumers of the existing response
                # shape; its value is now an exact key, not a prefix.
                "prefix": key,
                "description": "Exact event key observed in the 1,000 most recent events within the last 7 days",
                "observed_count": counts[key],
            }
            for key in sorted(counts)
        ]

    def get_event_categories(self) -> List[Dict[str, str]]:
        """Get available event categories for v2 API filtering."""
        return [
            {"category": "CLIENT_DEVICES", "description": "Client device connect/disconnect events"},
            {"category": "INTERNET_AND_WAN", "description": "Internet outage, failover, and performance"},
            {"category": "POWER", "description": "PoE, power supply, and UPS events"},
            {"category": "SECURITY", "description": "Firewall, IPS, honeypot events"},
            {"category": "UNIFI_DEVICES", "description": "Device adoption, discovery, reconnection"},
            {"category": "SOFTWARE_UPDATES", "description": "Firmware update events"},
            {"category": "UNIFI_ETHERNET_PORTS", "description": "Port events (STP, storms, errors)"},
            {"category": "VPN", "description": "VPN client and site-to-site events"},
        ]

    async def archive_alarm(self, alarm_id: str) -> bool:
        """Archive an alarm (mark as resolved)."""
        try:
            api_request = ApiRequest(
                method="post",
                path="/cmd/evtmgr",
                data={"cmd": "archive-alarm", "_id": alarm_id},
            )
            await self._connection.request(api_request)
            logger.info("Archived alarm %s", alarm_id)
            return True
        except Exception as e:
            logger.error("Error archiving alarm %s: %s", alarm_id, e)
            raise

    async def archive_all_alarms(self) -> bool:
        """Archive all active alarms."""
        try:
            api_request = ApiRequest(
                method="post",
                path="/cmd/evtmgr",
                data={"cmd": "archive-all-alarms"},
            )
            await self._connection.request(api_request)
            logger.info("Archived all alarms")
            return True
        except Exception as e:
            logger.error("Error archiving all alarms: %s", e)
            raise
