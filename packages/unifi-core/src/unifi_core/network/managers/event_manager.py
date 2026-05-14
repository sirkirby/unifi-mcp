"""Event Manager for UniFi Network MCP server.

Manages event log and alarm operations using the v2 system-log API
(UniFi Network 10.x+). Falls back to legacy /stat/event for older controllers.
"""

import logging
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from aiounifi.models.api import ApiRequest, ApiRequestV2
from aiounifi.models.message import MessageKey

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
            if event.get("_buffered_at", 0) < cutoff:
                continue
            if event_type and event.get("key") != event_type:
                continue
            if mac and event.get("mac") != mac:
                continue
            out.append(event)
            if limit and len(out) >= limit:
                break
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
        self._buffer = EventBuffer(
            max_size=int(cfg.get("buffer_size", 100)),
            ttl_seconds=int(cfg.get("buffer_ttl_seconds", 300)),
        )
        self._subscribers: list[Callable[[dict], None]] = []
        self._ws_unsub: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Websocket lifecycle
    # ------------------------------------------------------------------

    async def start_listening(self) -> None:
        """Open the aiounifi websocket and subscribe to event/alert messages.

        aiounifi exposes events through ``Controller.messages`` (a
        ``MessageHandler``). ``messages.subscribe(callback, message_filter)``
        returns an unsubscribe callable. We filter to ``EVENT`` + ``ALERT``
        so only event-log payloads flow through.
        """
        controller = self._cm.controller
        await controller.start_websocket()
        self._ws_unsub = controller.messages.subscribe(
            self._on_ws_event,
            (MessageKey.EVENT, MessageKey.ALERT),
        )
        logger.info("[network-event-mgr] websocket subscription started")

    async def stop_listening(self) -> None:
        """Unsubscribe from the websocket message handler."""
        if self._ws_unsub is not None:
            try:
                self._ws_unsub()
            except Exception:
                logger.debug("[network-event-mgr] error unsubscribing", exc_info=True)
            self._ws_unsub = None
            logger.info("[network-event-mgr] websocket subscription stopped")

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
        return len(self._buffer)

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
            return True
        except Exception:
            logger.info("[events] Falling back to legacy /stat/event API")
            return False

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
        try:
            now_ms = int(time.time() * 1000)
            from_ms = now_ms - (within * 3600 * 1000)

            payload: Dict[str, Any] = {
                "timestampFrom": from_ms,
                "timestampTo": now_ms,
                "severities": severities or _DEFAULT_SEVERITIES,
                "categories": categories or _DEFAULT_CATEGORIES,
                "type": "GENERAL",
                "pageNumber": start // limit if limit > 0 else 0,
                "pageSize": min(limit, 100),
                "searchText": "",
            }

            if event_type:
                payload["searchText"] = event_type

            api_request = ApiRequestV2(
                method="post",
                path="/system-log/all",
                data=payload,
            )
            response = await self._connection.request(api_request)

            # V2 response comes as [{"data": [...], "total_element_count": N}] or {"data": [...]}
            if isinstance(response, list) and response and isinstance(response[0], dict) and "data" in response[0]:
                return response[0]["data"]
            if isinstance(response, dict):
                return response.get("data", response.get("logs", []))
            if isinstance(response, list):
                return response
            return []
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
            raise

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
            raise

    def get_event_type_prefixes(self) -> List[Dict[str, str]]:
        """Get a list of known event type prefixes for filtering."""
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
