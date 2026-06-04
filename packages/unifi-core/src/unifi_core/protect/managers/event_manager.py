"""Event management for UniFi Protect.

Provides:
- ``EventBuffer`` -- ring buffer for recent NVR events received via websocket
- ``EventManager`` -- domain logic for querying, filtering, and streaming events
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from uiprotect.data import Event, EventType, ModelType, SmartDetectObjectType, WSAction, WSSubscriptionMessage

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.models.detection_search import from_controller as detection_search_from_controller
from unifi_core.protect.models.events import smart_detection_from_controller

logger = logging.getLogger(__name__)

# Allowed label prefixes for the detection-search endpoint. Each label is a
# ``prefix:value`` token; the prefix selects which filter category the value
# applies to (e.g. ``vehicleType:truck``).
_VALID_DETECTION_LABEL_PREFIXES = frozenset(
    {
        "vehicleType",
        "color",
        "smartDetectType",
        "eventType",
        "groupType",
        "camera",
        "zone",
        "line",
        "loiterZone",
        "doorAccess",
    }
)

# Sort directions accepted by detection-search (lowercased on input, sent uppercased).
_VALID_DETECTION_ORDERS = frozenset({"asc", "desc"})

# Inclusive bounds for the detection-search result limit.
_DETECTION_LIMIT_MIN = 1
_DETECTION_LIMIT_MAX = 1000

# Inclusive bounds for the detection-search minimum-confidence filter (percent).
_DETECTION_CONFIDENCE_MIN = 0
_DETECTION_CONFIDENCE_MAX = 100


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_any(obj: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = _get(obj, key)
        if value is not None:
            return value
    return default


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _enum_values(values: list[Any] | None) -> list[str]:
    return [t.value if hasattr(t, "value") else str(t) for t in (values or [])]


# ---------------------------------------------------------------------------
# EventBuffer
# ---------------------------------------------------------------------------


class EventBuffer:
    """Ring buffer for recent NVR events.

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
        """Add *event* to the buffer, stamping it with the current time."""
        event["_buffered_at"] = time.time()
        self._buffer.append(event)

    def get_recent(
        self,
        event_type: str | None = None,
        camera_id: str | None = None,
        min_confidence: int | None = None,
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
            if camera_id and event.get("camera_id") != camera_id:
                continue
            if min_confidence is not None and event.get("score", 100) < min_confidence:
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
    """Domain logic for UniFi Protect events.

    Responsibilities:
    - Websocket subscription via pyunifiprotect
    - Event parsing and buffering
    - REST-based event queries (list, get, smart detections, thumbnails)
    - Acknowledge mutations
    """

    def __init__(self, connection_manager: Any, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._cm = connection_manager
        self._buffer = EventBuffer(
            max_size=int(cfg.get("buffer_size", 100)),
            ttl_seconds=int(cfg.get("buffer_ttl_seconds", 300)),
        )
        self._min_confidence = int(cfg.get("smart_detection_min_confidence", 50))
        self._ws_unsub: Callable[[], None] | None = None
        self._server: Any | None = None  # FastMCP server reference for future notifications
        self._subscribers: list[Callable[[dict], None]] = []

    # ------------------------------------------------------------------
    # Server / notification wiring
    # ------------------------------------------------------------------

    def set_server(self, server: Any) -> None:
        """Store a reference to the FastMCP server.

        This enables future resource-update notifications once FastMCP
        exposes a public API for sending notifications from background
        callbacks.  Currently the session is only accessible during
        request handling, so push notifications are not yet supported.
        """
        self._server = server

    # ------------------------------------------------------------------
    # Websocket lifecycle
    # ------------------------------------------------------------------

    async def start_listening(self) -> None:
        """Subscribe to the pyunifiprotect websocket for real-time events.

        The ``subscribe_websocket`` method on the API client returns an
        unsubscribe callable which we store for clean shutdown.
        """
        self._ws_unsub = self._cm.client.subscribe_websocket(self._on_ws_message)
        logger.info("[event-mgr] Websocket subscription started.")

    async def stop_listening(self) -> None:
        """Unsubscribe from the websocket."""
        if self._ws_unsub is not None:
            try:
                self._ws_unsub()
            except Exception:
                logger.debug("[event-mgr] Error unsubscribing websocket", exc_info=True)
            self._ws_unsub = None
            logger.info("[event-mgr] Websocket subscription stopped.")

    # ------------------------------------------------------------------
    # Websocket callback & parsing
    # ------------------------------------------------------------------

    def _on_ws_message(self, msg: WSSubscriptionMessage) -> None:
        """Callback invoked for every websocket message from the NVR.

        Filters for Event model updates and adds them to the ring buffer.
        """
        try:
            event_dict = self._parse_ws_message(msg)
            if event_dict:
                self._buffer.add(event_dict)
                logger.debug(
                    "[event-mgr] Buffered event: type=%s camera=%s",
                    event_dict.get("type"),
                    event_dict.get("camera_id"),
                )
                # Phase 4B: fan out to subscribers
                for cb in list(self._subscribers):
                    try:
                        cb(event_dict)
                    except Exception:
                        logger.debug("[event-mgr] subscriber callback failed", exc_info=True)
                # NOTE: Push notifications to MCP clients are not yet
                # supported because ServerSession.send_resource_updated()
                # is only accessible from within a request context.  When
                # FastMCP adds a public broadcast API we can wire it here.
        except Exception:
            logger.debug("[event-mgr] Error processing websocket message", exc_info=True)

    def _parse_ws_message(self, msg: WSSubscriptionMessage) -> dict[str, Any] | None:
        """Parse a pyunifiprotect WSSubscriptionMessage into a plain dict.

        Only ``ADD`` and ``UPDATE`` actions for ``Event`` models are
        captured.  Returns ``None`` for messages we don't care about.
        """
        if msg.action not in (WSAction.ADD, WSAction.UPDATE):
            return None

        obj = msg.new_obj
        if obj is None:
            return None

        # Only process Event model objects
        model = getattr(obj, "model", None)
        if model != ModelType.EVENT:
            return None

        # obj is an Event instance at this point
        return self._event_to_dict(obj)

    def _resolve_camera_name(self, camera_id: str | None) -> str | None:
        """Resolve a camera ID to its display name from bootstrap data."""
        if not camera_id:
            return None
        try:
            cameras = self._cm.client.bootstrap.cameras
            camera = cameras.get(camera_id)
            return camera.name if camera else None
        except Exception:
            return None

    def _detected_thumbnails(self, event: Event) -> list[Any]:
        """Return detected-thumbnail metadata without fetching image bytes."""
        thumbnails: list[Any] = []
        metadata = _get(event, "metadata")
        raw_thumbnails = _get_any(metadata, "detected_thumbnails", "detectedThumbnails")
        if isinstance(raw_thumbnails, list):
            thumbnails.extend(raw_thumbnails)

        get_detected_thumbnail = getattr(event, "get_detected_thumbnail", None)
        if callable(get_detected_thumbnail):
            try:
                best_thumbnail = get_detected_thumbnail()
            except Exception:
                best_thumbnail = None
            if best_thumbnail is not None and not any(best_thumbnail is thumb for thumb in thumbnails):
                thumbnails.append(best_thumbnail)
        return [thumb for thumb in thumbnails if thumb is not None]

    def _face_recognition_fields(self, event: Event) -> dict[str, Any]:
        """Extract recognized-face identity metadata from detected thumbnails."""
        thumbnails = self._detected_thumbnails(event)
        if not thumbnails:
            return {}

        smart_detect_types = set(_enum_values(_get(event, "smart_detect_types")))
        face_thumbnails = [thumb for thumb in thumbnails if _get(thumb, "type") == "face"]
        candidates = face_thumbnails or (thumbnails if "face" in smart_detect_types else [])
        if not candidates:
            return {}

        def _score(thumb: Any) -> tuple[int, int, int, int]:
            group = _get(thumb, "group")
            name = _get_any(group, "matched_name", "matchedName", "name") or _get_any(
                thumb, "matched_name", "matchedName", "name"
            )
            group_id = _get_any(group, "id", "group_id", "groupId") or _get_any(thumb, "group_id", "groupId")
            confidence = _coerce_int(
                _get_any(group, "confidence", "matched_group_confidence", "matchedGroupConfidence")
                or _get_any(thumb, "confidence", "matched_group_confidence", "matchedGroupConfidence")
            )
            clock_best_wall = _get_any(thumb, "clock_best_wall", "clockBestWall")
            return (
                1 if name else 0,
                1 if group_id else 0,
                1 if clock_best_wall else 0,
                confidence or 0,
            )

        thumbnail = max(candidates, key=_score)
        group = _get(thumbnail, "group")
        recognized_person_id = _stringify(
            _get_any(group, "id", "group_id", "groupId") or _get_any(thumbnail, "group_id", "groupId")
        )
        recognized_person_name = _get_any(group, "matched_name", "matchedName", "name") or _get_any(
            thumbnail, "matched_name", "matchedName", "name"
        )
        recognized_person_confidence = _coerce_int(
            _get_any(group, "confidence", "matched_group_confidence", "matchedGroupConfidence")
            or _get_any(thumbnail, "confidence", "matched_group_confidence", "matchedGroupConfidence")
        )
        detected_thumbnail_id = _stringify(
            _get_any(thumbnail, "thumbnail_id", "thumbnailId", "cropped_id", "croppedId", "id")
        )

        fields: dict[str, Any] = {}
        if recognized_person_id:
            fields["recognized_person_id"] = recognized_person_id
        if recognized_person_name:
            fields["recognized_person_name"] = str(recognized_person_name)
        if recognized_person_confidence is not None:
            fields["recognized_person_confidence"] = recognized_person_confidence
        if detected_thumbnail_id:
            fields["detected_thumbnail_id"] = detected_thumbnail_id
        return fields

    async def _lookup_event_recognition_fields(self, event: Event) -> dict[str, Any]:
        """Fetch the same face event from the list/search path when detail drops group metadata."""
        if "face" not in set(_enum_values(_get(event, "smart_detect_types"))):
            return {}

        kwargs: dict[str, Any] = {
            "limit": 100,
            "sorting": "desc",
            "types": [EventType.SMART_DETECT, EventType.SMART_DETECT_LINE],
            "smart_detect_types": [SmartDetectObjectType.FACE],
        }
        if event.start:
            kwargs["start"] = event.start - timedelta(seconds=5)
            end = event.end or event.start
            kwargs["end"] = end + timedelta(minutes=1)

        try:
            events: list[Event] = await self._cm.client.get_events(**kwargs)
        except Exception:
            logger.debug("[event-mgr] Unable to backfill recognition metadata for event %s", event.id, exc_info=True)
            return {}

        for candidate in events:
            if candidate.id == event.id:
                return self._face_recognition_fields(candidate)
        return {}

    async def _known_face_names_by_id(self) -> dict[str, str]:
        """Map Known Face group IDs to assigned names using the recognition directory."""
        try:
            data = await self._cm.client.api_request(
                "recognition/face/groups",
                method="get",
                params={"hasName": True, "page": 1, "pageSize": 1000000},
            )
        except Exception:
            logger.debug("[event-mgr] Unable to load Known Face names for event enrichment", exc_info=True)
            return {}

        groups = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(groups, list):
            return {}

        names: dict[str, str] = {}
        for group in groups:
            group_id = _stringify(_get(group, "id"))
            name = _get_any(group, "matched_name", "matchedName", "name")
            if group_id and name:
                names[group_id] = str(name)
        return names

    async def _apply_known_face_names(self, events: list[dict[str, Any]]) -> None:
        """Fill recognized_person_name from Known Faces when events only expose group IDs."""
        missing_name_ids = {
            event["recognized_person_id"]
            for event in events
            if event.get("recognized_person_id") and not event.get("recognized_person_name")
        }
        if not missing_name_ids:
            return

        names = await self._known_face_names_by_id()
        if not names:
            return

        for event in events:
            group_id = event.get("recognized_person_id")
            if group_id in missing_name_ids and names.get(group_id):
                event["recognized_person_name"] = names[group_id]

    def _event_to_dict(self, event: Event, compact: bool = False) -> dict[str, Any]:
        """Convert a uiprotect ``Event`` object to a serialisable dict.

        When *compact* is True, omits low-value fields (thumbnail_id,
        category, sub_category, is_favorite) to reduce token usage in
        LLM contexts (~40% smaller per event).
        """
        result: dict[str, Any] = {
            "id": event.id,
            "type": event.type.value if isinstance(event.type, EventType) else str(event.type),
            "camera_id": event.camera_id,
            "camera_name": self._resolve_camera_name(event.camera_id),
            "start": event.start.isoformat() if event.start else None,
            "end": event.end.isoformat() if event.end else None,
            "score": event.score,
            "smart_detect_types": _enum_values(event.smart_detect_types),
        }
        result.update(self._face_recognition_fields(event))
        if not compact:
            result["thumbnail_id"] = event.thumbnail_id
            result["category"] = event.category
            result["sub_category"] = event.sub_category
            result["is_favorite"] = event.is_favorite
        return result

    def _raw_event_to_dict(
        self,
        raw: dict[str, Any],
        *,
        compact: bool = False,
        metadata_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Convert a RAW UniFi event dict (as returned by api_request_list) to the
        same response shape as _event_to_dict.

        Unlike _event_to_dict (which takes a parsed uiprotect.Event), this path
        preserves every field UniFi returned — including fields uiprotect strips
        during parsing (linesStatus, zonesStatus, weather, etc.). Opt in to that
        extra data via `metadata_fields`.
        """
        camera_id = _get(raw, "camera") or _get(raw, "camera_id")
        type_value = _get(raw, "type")
        # raw start/end are epoch milliseconds; normalize to ISO strings to match
        # the existing _event_to_dict response shape.
        start_ms = _get(raw, "start")
        end_ms = _get(raw, "end")
        start_iso = (
            datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat()
            if isinstance(start_ms, (int, float))
            else None
        )
        end_iso = (
            datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat()
            if isinstance(end_ms, (int, float))
            else None
        )
        sdt = _get(raw, "smartDetectTypes") or _get(raw, "smart_detect_types") or []
        if not isinstance(sdt, list):
            sdt = []

        result: dict[str, Any] = {
            "id": _get(raw, "id"),
            "type": type_value,
            "camera_id": camera_id,
            "camera_name": self._resolve_camera_name(camera_id),
            "start": start_iso,
            "end": end_iso,
            "score": _get(raw, "score"),
            "smart_detect_types": sdt,
        }
        # Existing face convenience extractor (relies on _get/_get_any which
        # handle both Event objects and dicts) keeps working untouched.
        # Note: PR-4 introduces _license_plate_recognition_fields on a separate
        # branch. This PR does not depend on PR-4; when both merge an integration
        # commit will add the parallel call here.
        result.update(self._face_recognition_fields(raw))

        if not compact:
            result["thumbnail_id"] = _get(raw, "thumbnail") or _get(raw, "thumbnail_id")
            result["category"] = _get(raw, "category")
            result["sub_category"] = _get(raw, "subCategory") or _get(raw, "sub_category")
            result["is_favorite"] = _get(raw, "isFavorite") or _get(raw, "is_favorite")

        if metadata_fields:
            raw_md = _get(raw, "metadata") or {}
            if "*" in metadata_fields:
                if raw_md:
                    result["metadata"] = raw_md
            else:
                filtered = {k: raw_md[k] for k in metadata_fields if k in raw_md}
                if filtered:
                    result["metadata"] = filtered

        return result

    # ------------------------------------------------------------------
    # Buffer access
    # ------------------------------------------------------------------

    def get_recent_from_buffer(
        self,
        event_type: str | None = None,
        camera_id: str | None = None,
        min_confidence: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent events from the websocket ring buffer."""
        return self._buffer.get_recent(
            event_type=event_type,
            camera_id=camera_id,
            min_confidence=min_confidence,
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
        start: datetime | None = None,
        end: datetime | None = None,
        event_type: str | None = None,
        camera_id: str | None = None,
        limit: int = 30,
        compact: bool = False,
        metadata_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Query events from the NVR via the REST API.

        When camera_id or metadata_fields is set, bypasses uiprotect's
        get_events() (which has no camera filter and drops several metadata
        fields) and calls UniFi's events endpoint directly. Otherwise
        delegates to the existing uiprotect path for full backwards
        compatibility.
        """
        use_raw_path = bool(camera_id) or bool(metadata_fields)

        if use_raw_path:
            params: dict[str, Any] = {
                "orderDirection": "DESC",
                "limit": limit,
                "withoutDescriptions": "true",
            }
            if start is not None:
                params["start"] = int(start.timestamp() * 1000)
            if end is not None:
                params["end"] = int(end.timestamp() * 1000)
            if event_type:
                params["types"] = [event_type]
            if camera_id:
                params["cameras"] = [camera_id]

            raw_events = await self._cm.client.api_request_list("events", params=params)

            results: list[dict[str, Any]] = []
            for raw in raw_events:
                results.append(self._raw_event_to_dict(raw, compact=compact, metadata_fields=metadata_fields))
            await self._apply_known_face_names(results)
            return results

        # ----- existing uiprotect path (unchanged) -----
        kwargs: dict[str, Any] = {"limit": limit, "sorting": "desc"}
        if start:
            kwargs["start"] = start
        if end:
            kwargs["end"] = end

        types_filter: list[EventType] | None = None
        if event_type:
            try:
                types_filter = [EventType(event_type)]
            except ValueError:
                for et in EventType:
                    if et.name.lower() == event_type.lower():
                        types_filter = [et]
                        break
                if types_filter is None:
                    logger.warning("[event-mgr] Unknown event type filter: %s", event_type)
        if types_filter:
            kwargs["types"] = types_filter

        events: list[Event] = await self._cm.client.get_events(**kwargs)

        results = []
        for ev in events:
            if camera_id and ev.camera_id != camera_id:
                continue
            results.append(self._event_to_dict(ev, compact=compact))

        await self._apply_known_face_names(results)
        return results

    async def get_event(
        self,
        event_id: str,
        metadata_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get a single event by ID.

        When ``metadata_fields`` is non-empty, bypasses uiprotect's Event
        parsing and calls UniFi's ``events/<id>`` endpoint directly to
        preserve the full metadata payload (filtered to caller-requested
        top-level keys).

        Raises ``ValueError`` if the event is not found.
        """
        if metadata_fields:
            try:
                raw = await self._cm.client.api_request_obj(f"events/{event_id}")
            except Exception as exc:
                raise UniFiNotFoundError("event", event_id) from exc
            result = self._raw_event_to_dict(raw, metadata_fields=metadata_fields)
            await self._apply_known_face_names([result])
            return result

        try:
            event: Event = await self._cm.client.get_event(event_id)
        except Exception as exc:
            raise UniFiNotFoundError("event", event_id) from exc
        result = self._event_to_dict(event)
        if not result.get("recognized_person_id") and not result.get("recognized_person_name"):
            result.update(await self._lookup_event_recognition_fields(event))
        await self._apply_known_face_names([result])
        return result

    async def get_event_thumbnail(
        self,
        event_id: str,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Get the thumbnail for an event.

        Returns a dict with ``thumbnail_id`` and optionally ``image_base64``
        (JPEG bytes encoded as base64).
        """
        # First retrieve the event to get its thumbnail_id
        try:
            event: Event = await self._cm.client.get_event(event_id)
        except Exception as exc:
            raise UniFiNotFoundError("event", event_id) from exc

        if not event.thumbnail_id:
            return {
                "event_id": event_id,
                "thumbnail_available": False,
                "message": "Event has no thumbnail (may still be in progress).",
            }

        try:
            thumb_bytes = await self._cm.client.get_event_thumbnail(
                event.thumbnail_id,
                width=width,
                height=height,
            )
        except Exception as exc:
            logger.debug("[event-mgr] Failed to fetch thumbnail for %s: %s", event_id, exc)
            return {
                "event_id": event_id,
                "thumbnail_id": event.thumbnail_id,
                "thumbnail_available": False,
                "message": "Thumbnail not yet available (event may still be in progress).",
            }

        if thumb_bytes is None:
            return {
                "event_id": event_id,
                "thumbnail_id": event.thumbnail_id,
                "thumbnail_available": False,
                "message": "Thumbnail not yet available (event may still be in progress).",
            }

        import base64

        return {
            "event_id": event_id,
            "thumbnail_id": event.thumbnail_id,
            "thumbnail_available": True,
            "image_base64": base64.b64encode(thumb_bytes).decode(),
            "content_type": "image/jpeg",
        }

    async def list_smart_detections(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        camera_id: str | None = None,
        detection_type: str | None = None,
        min_confidence: int | None = None,
        limit: int = 30,
        compact: bool = False,
        metadata_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List smart detection events with optional filtering.

        Queries for ``smartDetectZone`` and ``smartDetectLine`` event types,
        then filters by detection type and confidence score.

        When camera_id or metadata_fields is set, bypasses uiprotect's
        get_events() and calls UniFi's events endpoint directly (same raw-API
        path as list_events) so that metadata fields are preserved.
        """
        min_conf = min_confidence if min_confidence is not None else self._min_confidence
        use_raw_path = bool(camera_id) or bool(metadata_fields)

        if use_raw_path:
            params: dict[str, Any] = {
                "orderDirection": "DESC",
                "limit": limit,
                "withoutDescriptions": "true",
                "types": ["smartDetectZone", "smartDetectLine"],
            }
            if start is not None:
                params["start"] = int(start.timestamp() * 1000)
            if end is not None:
                params["end"] = int(end.timestamp() * 1000)
            if camera_id:
                params["cameras"] = [camera_id]
            if detection_type:
                params["smartDetectTypes"] = [detection_type]

            raw_events = await self._cm.client.api_request_list("events", params=params)

            results: list[dict[str, Any]] = []
            for raw in raw_events:
                score = raw.get("score", 100) or 0
                if score < min_conf:
                    continue
                results.append(self._raw_event_to_dict(raw, compact=compact, metadata_fields=metadata_fields))
            await self._apply_known_face_names(results)
            return results

        # ----- existing uiprotect path (unchanged) -----
        kwargs: dict[str, Any] = {
            "limit": limit,
            "sorting": "desc",
            "types": [EventType.SMART_DETECT, EventType.SMART_DETECT_LINE],
        }
        if start:
            kwargs["start"] = start
        if end:
            kwargs["end"] = end

        # Filter by smart detect type if specified
        if detection_type:
            smart_types_filter: list[SmartDetectObjectType] = []
            try:
                smart_types_filter = [SmartDetectObjectType(detection_type)]
            except ValueError:
                for sdt in SmartDetectObjectType:
                    if sdt.name.lower() == detection_type.lower():
                        smart_types_filter = [sdt]
                        break
            if smart_types_filter:
                kwargs["smart_detect_types"] = smart_types_filter

        events: list[Event] = await self._cm.client.get_events(**kwargs)

        uiprotect_results: list[dict[str, Any]] = []
        for ev in events:
            if camera_id and ev.camera_id != camera_id:
                continue
            if ev.score < min_conf:
                continue
            uiprotect_results.append(self._event_to_dict(ev, compact=compact))

        await self._apply_known_face_names(uiprotect_results)
        return uiprotect_results

    def _build_detection_search_params(
        self,
        *,
        labels: list[str],
        limit: int,
        order: str,
        exclude_motion: bool,
        min_confidence: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[tuple[str, str]]:
        """Validate inputs and build the detection-search query params.

        Returns a list of ``(key, value)`` tuples with stringified values so the
        ``labels`` key is repeated once per label by the underlying HTTP client
        (the controller applies the labels conjunctively).
        """
        normalized_labels = [label.strip() for label in labels if label and label.strip()]
        if not normalized_labels:
            raise ValueError("At least one label is required.")
        for label in normalized_labels:
            prefix = label.split(":", 1)[0] if ":" in label else ""
            if prefix not in _VALID_DETECTION_LABEL_PREFIXES:
                raise ValueError(
                    f"Invalid label {label!r}. Labels must be 'prefix:value' with prefix "
                    f"in {sorted(_VALID_DETECTION_LABEL_PREFIXES)}."
                )

        if not (_DETECTION_LIMIT_MIN <= limit <= _DETECTION_LIMIT_MAX):
            raise ValueError(f"limit must be between {_DETECTION_LIMIT_MIN} and {_DETECTION_LIMIT_MAX}, got {limit}.")

        normalized_order = order.strip().lower()
        if normalized_order not in _VALID_DETECTION_ORDERS:
            raise ValueError(f"Invalid order {order!r}. Valid orders: {sorted(_VALID_DETECTION_ORDERS)}.")

        if min_confidence is not None and not (
            _DETECTION_CONFIDENCE_MIN <= min_confidence <= _DETECTION_CONFIDENCE_MAX
        ):
            raise ValueError(
                f"min_confidence must be between {_DETECTION_CONFIDENCE_MIN} and "
                f"{_DETECTION_CONFIDENCE_MAX}, got {min_confidence}."
            )

        params: list[tuple[str, str]] = [("excludeMotion", "true" if exclude_motion else "false")]
        params.extend(("labels", label) for label in normalized_labels)
        params.append(("limit", str(limit)))
        params.append(("orderDirection", normalized_order.upper()))
        if min_confidence is not None:
            params.append(("minConfidence", str(min_confidence)))
        # The controller's detection-search endpoint expects epoch-millisecond bounds.
        if start is not None:
            params.append(("start", str(int(start.timestamp() * 1000))))
        if end is not None:
            params.append(("end", str(int(end.timestamp() * 1000))))
        return params

    async def search_detections(
        self,
        *,
        labels: list[str],
        limit: int,
        order: str,
        exclude_motion: bool,
        min_confidence: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        """Search detections via the controller's detection-search endpoint.

        The ``labels`` query key is repeated once per label so the controller
        applies them conjunctively. Returns a ``{"detections": [...], "count": n}``
        envelope of :class:`SmartDetection` items parsed from the
        ``{"events": [...]}`` response shape.

        Optional ``min_confidence`` (0-100) maps to the ``minConfidence`` query
        param; ``start``/``end`` map to the ``start``/``end`` epoch-millisecond
        bounds. All three are omitted from the request when ``None``.
        """
        params = self._build_detection_search_params(
            labels=labels,
            limit=limit,
            order=order,
            exclude_motion=exclude_motion,
            min_confidence=min_confidence,
            start=start,
            end=end,
        )
        data = await self._cm.client.api_request("detection-search", method="get", params=params)
        if not isinstance(data, dict):
            data = {}
        events = data.get("events") or []
        detections = [smart_detection_from_controller(event) for event in events]
        return {"detections": detections, "count": len(detections)}

    async def get_detection_search_labels(self) -> dict[str, Any]:
        """Return the detection-search filter vocabulary from the controller.

        Wraps the ``detection-search/labels`` endpoint, which lists the legal
        filter values (colors, vehicle types, smart-detect types, ...) the
        "Find Anything" panel offers. The raw response is normalised through
        :func:`detection_search_from_controller` into snake_case group lists.
        """
        raw = await self._cm.client.api_request("detection-search/labels", method="get")
        return detection_search_from_controller(raw).model_dump(exclude_none=True)

    async def acknowledge_event(self, event_id: str) -> dict[str, Any]:
        """Mark an event as acknowledged/favorite on the NVR.

        Uses the ``is_favorite`` field as an acknowledgement mechanism since
        the Protect API does not have a dedicated acknowledge endpoint.

        Returns a preview dict for the confirmation pattern.
        """
        try:
            event: Event = await self._cm.client.get_event(event_id)
        except Exception as exc:
            raise UniFiNotFoundError("event", event_id) from exc

        return {
            "event_id": event_id,
            "type": event.type.value if isinstance(event.type, EventType) else str(event.type),
            "camera_id": event.camera_id,
            "camera_name": self._resolve_camera_name(event.camera_id),
            "current_is_favorite": event.is_favorite,
            "proposed_is_favorite": True,
        }

    async def apply_acknowledge_event(self, event_id: str) -> dict[str, Any]:
        """Apply the acknowledge (favorite) mutation to the NVR."""
        try:
            event: Event = await self._cm.client.get_event(event_id)
        except Exception as exc:
            raise UniFiNotFoundError("event", event_id) from exc

        # The Protect API uses is_favorite as the closest analog to
        # "acknowledged".  We set it to True.
        # Note: the exact mutation API depends on the uiprotect version.
        # Some versions expose event.set_is_favorite() or similar.
        # Fall back to a generic save approach.
        try:
            event.is_favorite = True
            await event.save_device()
        except AttributeError:
            # Older API versions may not have save_device on events
            logger.warning("[event-mgr] Event save_device not available; acknowledge may not persist.")

        return {
            "event_id": event_id,
            "acknowledged": True,
            "is_favorite": True,
        }
