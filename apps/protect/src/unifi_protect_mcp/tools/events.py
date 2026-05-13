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
) -> Dict[str, Any]:
    """Get a single event by ID."""
    logger.info("protect_get_event called for %s", event_id)
    try:
        raw = await event_manager.get_event(event_id)
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
        )
        detections = [smart_detection_from_controller(d).model_dump(exclude_none=True) for d in raw_detections]
        return {"success": True, "data": {"detections": detections, "count": len(detections)}}
    except Exception as e:
        logger.error("Error listing smart detections: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list smart detections: {e}"}


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
        events = [event_from_controller(e).model_dump(exclude_none=True) for e in raw_events]
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
    "protect_recent_events, protect_subscribe_events, protect_acknowledge_event"
)
