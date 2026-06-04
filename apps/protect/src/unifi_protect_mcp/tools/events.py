"""Event tools for UniFi Protect MCP server.

Provides tools for querying events from the NVR (REST), reading recent
events from the websocket buffer (in-memory), and managing event state.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import preview_response
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.models._actions import AcknowledgeEventInput
from unifi_core.protect.models.events import (
    from_controller as event_from_controller,
)
from unifi_core.protect.models.events import (
    smart_detection_from_controller,
    thumbnail_from_controller,
)
from unifi_protect_mcp.runtime import event_manager, server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: parse ISO datetime string
# ---------------------------------------------------------------------------


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-format datetime string, returning None on failure."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        # Ensure timezone-aware (default to UTC if naive)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


@server.tool(
    name="protect_list_events",
    description=(
        "Query events from the NVR with optional filters. Returns events from "
        "the Protect controller's database via REST API. Supports filtering by "
        "time range, event type (motion, smartDetectZone, ring, etc.), camera ID, "
        "and result limit. Face events include recognized Known Face identity "
        "fields when Protect provides them. For real-time buffer events use "
        "protect_recent_events."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_list_events(
    start: Annotated[
        Optional[str],
        Field(description="Start time as ISO 8601 timestamp (e.g., 2026-03-17T00:00:00Z). Defaults to 24 hours ago."),
    ] = None,
    end: Annotated[
        Optional[str],
        Field(description="End time as ISO 8601 timestamp (e.g., 2026-03-17T23:59:59Z). Defaults to now."),
    ] = None,
    event_type: Annotated[
        Optional[str],
        Field(
            description="Filter by event type: motion, smartDetectZone, ring, sensorMotion, sensorContact, sensorDoorbell."
        ),
    ] = None,
    camera_id: Annotated[
        Optional[str],
        Field(
            description="Filter events to a specific camera by its UUID (from protect_list_cameras). Omit to include all cameras."
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum number of events to return (default 30)."),
    ] = 30,
    compact: Annotated[
        bool,
        Field(
            description="When true, omits thumbnail_id, category, sub_category, and is_favorite fields to reduce response size (~40% smaller). Recommended for digests and summaries."
        ),
    ] = False,
    metadata_fields: Annotated[
        Optional[list[str]],
        Field(
            description=(
                "Per-event metadata keys to include in the response. Default None "
                "returns no metadata (backwards-compatible). Pass top-level metadata key "
                "names (e.g. ['linesStatus', 'weather']) to include only those, or pass "
                "['*'] for the full metadata dict. Top-level keys only today; dotted "
                "paths reserved for future nested selection."
            )
        ),
    ] = None,
) -> Dict[str, Any]:
    """List events from the NVR."""
    logger.info(
        "protect_list_events called (type=%s, camera=%s, limit=%s, compact=%s)", event_type, camera_id, limit, compact
    )
    try:
        raw_events = await event_manager.list_events(
            start=_parse_datetime(start),
            end=_parse_datetime(end),
            event_type=event_type,
            camera_id=camera_id,
            limit=limit,
            compact=compact,
            metadata_fields=metadata_fields or None,
        )
        events = [event_from_controller(e).model_dump(exclude_none=True) for e in raw_events]
        return {"success": True, "data": {"events": events, "count": len(events)}}
    except Exception as e:
        logger.error("Error listing events: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list events: {e}"}


@server.tool(
    name="protect_get_event",
    description=(
        "Get detailed information for a single event by ID. Returns event type, "
        "camera, timestamps, score, smart detection types, thumbnail info, and "
        "recognized Known Face identity fields when Protect provides them."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_get_event(
    event_id: Annotated[str, Field(description="Event UUID (from protect_list_events or protect_recent_events)")],
    metadata_fields: Annotated[
        Optional[list[str]],
        Field(
            description=(
                "Per-event metadata keys to include in the response. Default None "
                "returns no metadata (backwards-compatible). Pass top-level metadata key "
                "names (e.g. ['linesStatus', 'weather']) to include only those, or pass "
                "['*'] for the full metadata dict. Top-level keys only today; dotted "
                "paths reserved for future nested selection."
            )
        ),
    ] = None,
) -> Dict[str, Any]:
    """Get a single event by ID."""
    logger.info("protect_get_event called for %s (metadata_fields=%s)", event_id, metadata_fields)
    try:
        raw = await event_manager.get_event(event_id, metadata_fields=metadata_fields or None)
        return {"success": True, "data": event_from_controller(raw).model_dump(exclude_none=True)}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting event %s: %s", event_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get event: {e}"}


@server.tool(
    name="protect_get_event_thumbnail",
    description=(
        "Get the thumbnail image for an event. Returns a base64-encoded JPEG. "
        "Thumbnails are generated after an event ends; in-progress events may "
        "not have thumbnails yet. Optionally specify width/height to resize."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_get_event_thumbnail(
    event_id: Annotated[str, Field(description="Event UUID (from protect_list_events or protect_recent_events)")],
    width: Annotated[
        Optional[int],
        Field(
            description="Resize the thumbnail to this width in pixels. Aspect ratio is preserved if only width or height is set."
        ),
    ] = None,
    height: Annotated[
        Optional[int],
        Field(
            description="Resize the thumbnail to this height in pixels. Aspect ratio is preserved if only width or height is set."
        ),
    ] = None,
) -> Dict[str, Any]:
    """Get event thumbnail."""
    logger.info("protect_get_event_thumbnail called for %s", event_id)
    try:
        raw = await event_manager.get_event_thumbnail(event_id, width=width, height=height)
        return {"success": True, "data": thumbnail_from_controller(raw).model_dump(exclude_none=True)}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting thumbnail for event %s: %s", event_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get event thumbnail: {e}"}


@server.tool(
    name="protect_list_smart_detections",
    description=(
        "List smart detection events (person, vehicle, animal, package, etc.) "
        "with optional filters. Filters by detection type, camera, confidence "
        "score, and time range. Only returns events above the minimum confidence "
        "threshold (default 50, configurable via PROTECT_SMART_DETECTION_MIN_CONFIDENCE). "
        "Face detections include recognized Known Face identity fields when "
        "Protect provides them."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_list_smart_detections(
    start: Annotated[
        Optional[str],
        Field(description="Start time as ISO 8601 timestamp (e.g., 2026-03-17T00:00:00Z). Defaults to 24 hours ago."),
    ] = None,
    end: Annotated[
        Optional[str],
        Field(description="End time as ISO 8601 timestamp (e.g., 2026-03-17T23:59:59Z). Defaults to now."),
    ] = None,
    camera_id: Annotated[
        Optional[str],
        Field(
            description="Filter detections to a specific camera by its UUID (from protect_list_cameras). Omit to include all cameras."
        ),
    ] = None,
    detection_type: Annotated[
        Optional[str],
        Field(description="Filter by smart detection type: person, vehicle, animal, package, face, licensePlate."),
    ] = None,
    min_confidence: Annotated[
        Optional[int],
        Field(
            description="Minimum confidence score (0-100) to include. Overrides the server default (50). Higher values return fewer, more certain detections."
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum number of smart detection events to return (default 30)."),
    ] = 30,
    compact: Annotated[
        bool,
        Field(
            description="When true, omits thumbnail_id, category, sub_category, and is_favorite fields to reduce response size (~40% smaller). Recommended for digests and summaries."
        ),
    ] = False,
    metadata_fields: Annotated[
        Optional[list[str]],
        Field(
            description=(
                "Per-event metadata keys to include in the response. Default None "
                "returns no metadata (backwards-compatible). Pass top-level metadata key "
                "names (e.g. ['linesStatus', 'weather']) to include only those, or pass "
                "['*'] for the full metadata dict. Top-level keys only today; dotted "
                "paths reserved for future nested selection."
            )
        ),
    ] = None,
) -> Dict[str, Any]:
    """List smart detection events."""
    logger.info(
        "protect_list_smart_detections called (type=%s, camera=%s, confidence>=%s, compact=%s)",
        detection_type,
        camera_id,
        min_confidence,
        compact,
    )
    try:
        raw_detections = await event_manager.list_smart_detections(
            start=_parse_datetime(start),
            end=_parse_datetime(end),
            camera_id=camera_id,
            detection_type=detection_type,
            min_confidence=min_confidence,
            limit=limit,
            compact=compact,
            metadata_fields=metadata_fields or None,
        )
        detections = [smart_detection_from_controller(d).model_dump(exclude_none=True) for d in raw_detections]
        return {"success": True, "data": {"detections": detections, "count": len(detections)}}
    except Exception as e:
        logger.error("Error listing smart detections: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list smart detections: {e}"}


@server.tool(
    name="protect_search_detections",
    description=(
        "Search detections across all cameras using Protect's 'Find Anything' "
        "filter vocabulary. Pass one or more labels of the form 'prefix:value' "
        "(e.g. 'vehicleType:truck', 'color:black', 'smartDetectType:vehicle'); "
        "labels are applied conjunctively. Call protect_detection_search_labels "
        "first to discover the legal labels for this controller. Returns matching "
        "smart detection events. excludeMotion defaults to true so plain motion "
        "events are filtered out."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_search_detections(
    labels: Annotated[
        list[str],
        Field(
            description=(
                "Filter labels of the form 'prefix:value' (e.g. ['vehicleType:truck', "
                "'color:black']). At least one is required; all are applied together. "
                "Use protect_detection_search_labels to discover legal values."
            )
        ),
    ],
    limit: Annotated[
        int,
        Field(description="Maximum number of detections to return (1-1000, default 100).", ge=1, le=1000),
    ] = 100,
    order: Annotated[
        str,
        Field(description="Result ordering by time: 'desc' (newest first, default) or 'asc' (oldest first)."),
    ] = "desc",
    exclude_motion: Annotated[
        bool,
        Field(description="When true (default), exclude plain motion events so only smart detections are returned."),
    ] = True,
    min_confidence: Annotated[
        Optional[int],
        Field(description="Minimum confidence score (0-100) to include. Omit to apply no confidence filter."),
    ] = None,
    start: Annotated[
        Optional[str],
        Field(
            description="Only include detections at/after this time, as an ISO 8601 timestamp (e.g., 2026-03-17T00:00:00Z). Omit for no lower bound."
        ),
    ] = None,
    end: Annotated[
        Optional[str],
        Field(
            description="Only include detections at/before this time, as an ISO 8601 timestamp (e.g., 2026-03-17T23:59:59Z). Omit for no upper bound."
        ),
    ] = None,
) -> Dict[str, Any]:
    """Search detections via the controller's detection-search endpoint."""
    logger.info(
        "protect_search_detections called (labels=%s, limit=%s, order=%s, exclude_motion=%s, min_confidence=%s, start=%s, end=%s)",
        labels,
        limit,
        order,
        exclude_motion,
        min_confidence,
        start,
        end,
    )
    try:
        result = await event_manager.search_detections(
            labels=labels,
            limit=limit,
            order=order,
            exclude_motion=exclude_motion,
            min_confidence=min_confidence,
            start=_parse_datetime(start),
            end=_parse_datetime(end),
        )
        detections = [d.model_dump(exclude_none=True) for d in result["detections"]]
        return {"success": True, "data": {"detections": detections, "count": len(detections)}}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error searching detections: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to search detections: {e}"}


@server.tool(
    name="protect_detection_search_labels",
    description=(
        "List the detection-search filter vocabulary supported by this controller. "
        "Returns the legal label values (colors, vehicle types, smart detection "
        "types, event types, etc.) that the 'Find Anything' panel offers. Use the "
        "returned values as labels for protect_search_detections."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_detection_search_labels() -> Dict[str, Any]:
    """List the detection-search filter vocabulary."""
    logger.info("protect_detection_search_labels called")
    try:
        labels = await event_manager.get_detection_search_labels()
        return {"success": True, "data": labels}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error listing detection search labels: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list detection search labels: {e}"}


@server.tool(
    name="protect_recent_events",
    description=(
        "Get recent events from the in-memory websocket buffer. This is fast "
        "(no API call) and returns events received via the real-time websocket "
        "stream. Supports filtering by event_type, camera_id, min_confidence, "
        "and limit. Face events include recognized Known Face identity fields "
        "when Protect provides them. Use this for real-time monitoring; use "
        "protect_list_events for historical queries."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_recent_events(
    event_type: Annotated[
        Optional[str],
        Field(
            description="Filter by event type: motion, smartDetectZone, ring, sensorMotion, sensorContact, sensorDoorbell."
        ),
    ] = None,
    camera_id: Annotated[
        Optional[str],
        Field(
            description="Filter events to a specific camera by its UUID (from protect_list_cameras). Omit to include all cameras."
        ),
    ] = None,
    min_confidence: Annotated[
        Optional[int],
        Field(description="Minimum confidence score (0-100) to include. Only applies to smart detection events."),
    ] = None,
    limit: Annotated[
        Optional[int],
        Field(description="Maximum number of events to return from the buffer. Omit to return all buffered events."),
    ] = None,
    metadata_fields: Annotated[
        Optional[list[str]],
        Field(
            description=(
                "Per-event metadata keys to include in the response. Default None "
                "returns no metadata (backwards-compatible). Pass top-level metadata key "
                "names (e.g. ['linesStatus', 'weather']) to include only those, or pass "
                "['*'] for the full metadata dict. Top-level keys only today; dotted "
                "paths reserved for future nested selection."
            )
        ),
    ] = None,
) -> Dict[str, Any]:
    """Get recent events from the websocket buffer."""
    logger.info("protect_recent_events called (type=%s, camera=%s)", event_type, camera_id)
    try:
        raw_events = event_manager.get_recent_from_buffer(
            event_type=event_type,
            camera_id=camera_id,
            min_confidence=min_confidence,
            limit=limit,
        )
        # Buffer events are raw dicts with the full metadata payload.
        # Apply metadata_fields filtering here without mutating the buffer.
        effective_metadata_fields = metadata_fields or None
        processed: list[Dict[str, Any]] = []
        for raw in raw_events:
            event_dict = dict(raw)  # shallow copy — don't mutate the buffer's stored event
            # Strip internal buffer timestamp from outgoing response
            event_dict.pop("_buffered_at", None)
            if effective_metadata_fields is None:
                event_dict.pop("metadata", None)
            elif "*" in effective_metadata_fields:
                pass  # keep full metadata as-is
            else:
                raw_md = event_dict.get("metadata") or {}
                event_dict["metadata"] = {k: raw_md[k] for k in effective_metadata_fields if k in raw_md}
                if not event_dict["metadata"]:
                    event_dict.pop("metadata", None)
            processed.append(event_dict)
        events = [event_from_controller(e).model_dump(exclude_none=True) for e in processed]
        return {
            "success": True,
            "data": {
                "events": events,
                "count": len(events),
                "source": "websocket_buffer",
                "buffer_size": event_manager.buffer_size,
            },
        }
    except Exception as e:
        logger.error("Error reading recent events: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to read recent events: {e}"}


@server.tool(
    name="protect_subscribe_events",
    description=(
        "Returns instructions for subscribing to real-time Protect events. "
        "Provides the MCP resource URI for the event stream and guidance on "
        "polling intervals. Use this to set up continuous event monitoring."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_subscribe_events() -> Dict[str, Any]:
    """Return subscription instructions for event streaming."""
    logger.info("protect_subscribe_events called")
    return {
        "success": True,
        "data": {
            "resource_uri": "protect://events/stream",
            "summary_uri": "protect://events/stream/summary",
            "instructions": (
                "To monitor events in real-time:\n"
                "1. Read the resource at 'protect://events/stream' to get recent events as JSON\n"
                "2. Read 'protect://events/stream/summary' for a lightweight event count summary\n"
                "3. Or use the 'protect_recent_events' tool for filtered buffer queries\n"
                "4. Poll every 5-10 seconds for near-real-time updates\n"
                "\n"
                "Note: MCP push notifications are not yet supported from background "
                "websocket callbacks. Polling is the recommended approach."
            ),
            "buffer_size": event_manager.buffer_size,
        },
    }


# ---------------------------------------------------------------------------
# Mutation tools (preview/confirm pattern)
# ---------------------------------------------------------------------------


@server.tool(
    name="protect_acknowledge_event",
    description=(
        "Acknowledge an event by marking it as a favorite on the NVR. "
        "This is the closest equivalent to 'marking as read' in the Protect "
        "system. Requires confirm=True to apply."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="event",
    permission_action="update",
)
async def protect_acknowledge_event(
    event_id: Annotated[
        str, Field(description="Event UUID to acknowledge (from protect_list_events or protect_recent_events)")
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, marks the event as acknowledged. When false (default), returns a preview of the changes."
        ),
    ] = False,
) -> Dict[str, Any]:
    """Acknowledge an event with preview/confirm."""
    logger.info("protect_acknowledge_event called for %s (confirm=%s)", event_id, confirm)
    try:
        try:
            AcknowledgeEventInput(event_id=event_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        preview_data = await event_manager.acknowledge_event(event_id)

        if not confirm:
            return preview_response(
                action="acknowledge",
                resource_type="event",
                resource_id=event_id,
                current_state={
                    "is_favorite": preview_data["current_is_favorite"],
                },
                proposed_changes={
                    "is_favorite": preview_data["proposed_is_favorite"],
                },
                resource_name=f"{preview_data['type']} event on camera {preview_data.get('camera_id', 'unknown')}",
            )

        result = await event_manager.apply_acknowledge_event(event_id)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error acknowledging event %s: %s", event_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to acknowledge event: {e}"}


logger.info(
    "Event tools registered: protect_list_events, protect_get_event, "
    "protect_get_event_thumbnail, protect_list_smart_detections, "
    "protect_search_detections, protect_detection_search_labels, "
    "protect_recent_events, protect_subscribe_events, protect_acknowledge_event"
)
