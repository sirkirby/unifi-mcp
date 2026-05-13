"""Event tools for UniFi Access MCP server.

Provides tools for querying access events (door opens, denials, etc.)
from the Access controller, reading recent events from the in-memory
buffer, and subscribing to real-time event streams.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from unifi_core.exceptions import UniFiNotFoundError
from pydantic import Field

from unifi_access_mcp.runtime import event_manager, server
from unifi_core.access.models.events import (
    activity_summary_from_controller,
    event_from_controller,
)

logger = logging.getLogger(__name__)


@server.tool(
    name="access_list_events",
    description=(
        "Query access events from the controller with optional filters. "
        "Returns events such as door unlocks, access denials, and system events. "
        "Supports filtering by time range, door, user, and result limit. "
        "For real-time buffer events use access_recent_events."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="event",
    permission_action="read",
    auth="local_only",
)
async def access_list_events(
    topic: Annotated[
        str,
        Field(
            description="Event topic to query: 'admin' (user/account changes) or 'admin_activity' (admin actions). Default: admin."
        ),
    ] = "admin",
    start: Annotated[
        Optional[str],
        Field(description="Start time as ISO 8601 timestamp (e.g., 2026-03-17T00:00:00Z). Omit for no lower bound."),
    ] = None,
    end: Annotated[
        Optional[str],
        Field(description="End time as ISO 8601 timestamp (e.g., 2026-03-17T23:59:59Z). Omit for no upper bound."),
    ] = None,
    door_id: Annotated[
        Optional[str],
        Field(description="Filter events to a specific door by UUID (from access_list_doors). Omit for all doors."),
    ] = None,
    user_id: Annotated[
        Optional[str],
        Field(description="Filter events to a specific user by UUID (from access_list_users). Omit for all users."),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum number of events to return (default 30)."),
    ] = 30,
) -> Dict[str, Any]:
    """List access events."""
    logger.info("access_list_events tool called (topic=%s, door=%s, user=%s, limit=%s)", topic, door_id, user_id, limit)
    try:
        raw_events = await event_manager.list_events(
            topic=topic,
            start=start,
            end=end,
            door_id=door_id,
            user_id=user_id,
            limit=limit,
        )
        events = [event_from_controller(e).model_dump(exclude_none=True) for e in raw_events]
        return {"success": True, "data": {"events": events, "count": len(events)}}
    except Exception as e:
        logger.error("Error listing events: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list events: {e}"}


@server.tool(
    name="access_get_event",
    description=(
        "Returns detailed information for a single access event including "
        "event type, door, user, timestamp, and result."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="event",
    permission_action="read",
    auth="local_only",
)
async def access_get_event(
    event_id: Annotated[str, Field(description="Event UUID (from access_list_events or access_recent_events)")],
) -> Dict[str, Any]:
    """Get a single event by ID."""
    logger.info("access_get_event tool called for %s", event_id)
    try:
        raw = await event_manager.get_event(event_id)
        event = event_from_controller(raw).model_dump(exclude_none=True)
        return {"success": True, "data": event}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting event %s: %s", event_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get event: {e}"}


@server.tool(
    name="access_recent_events",
    description=(
        "Get recent events from the in-memory websocket buffer. Fast (no API call). "
        "Supports filtering by event type and door. "
        "Use for real-time monitoring; use access_list_events for historical queries."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="event",
    permission_action="read",
    auth="either",
)
async def access_recent_events(
    event_type: Annotated[
        Optional[str],
        Field(description=("Filter by event type: door_open, door_close, access_granted, access_denied, door_alarm.")),
    ] = None,
    door_id: Annotated[
        Optional[str],
        Field(description="Filter events to a specific door by UUID (from access_list_doors). Omit for all doors."),
    ] = None,
    limit: Annotated[
        Optional[int],
        Field(description="Maximum number of events to return from the buffer. Omit to return all buffered events."),
    ] = None,
) -> Dict[str, Any]:
    """Get recent events from the websocket buffer."""
    logger.info("access_recent_events called (type=%s, door=%s)", event_type, door_id)
    try:
        events = event_manager.get_recent_from_buffer(
            event_type=event_type,
            door_id=door_id,
            limit=limit,
        )
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
    name="access_subscribe_events",
    description=(
        "Returns instructions for subscribing to real-time Access events. "
        "Provides the MCP resource URI for the event stream and guidance on "
        "polling intervals. Use this to set up continuous event monitoring."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="event",
    permission_action="read",
    auth="either",
)
async def access_subscribe_events() -> Dict[str, Any]:
    """Return subscription instructions for event streaming."""
    logger.info("access_subscribe_events called")
    return {
        "success": True,
        "data": {
            "resource_uri": "access://events/stream",
            "summary_uri": "access://events/stream/summary",
            "instructions": (
                "To monitor events in real-time:\n"
                "1. Read the resource at 'access://events/stream' to get recent events as JSON\n"
                "2. Read 'access://events/stream/summary' for a lightweight event count summary\n"
                "3. Or use the 'access_recent_events' tool for filtered buffer queries\n"
                "4. Poll every 5-10 seconds for near-real-time updates\n"
                "\n"
                "Note: MCP push notifications are not yet supported from background "
                "websocket callbacks. Polling is the recommended approach."
            ),
            "buffer_size": event_manager.buffer_size,
        },
    }


@server.tool(
    name="access_get_activity_summary",
    description=(
        "Get an aggregated activity summary for Access events over a time period. "
        "Shows event counts, breakdowns by type, and trends. Optionally scope to "
        "a single door. Only available via local proxy session."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="event",
    permission_action="read",
    auth="local_only",
)
async def access_get_activity_summary(
    door_id: Annotated[
        Optional[str],
        Field(description="Door UUID to scope the summary (from access_list_doors). Omit for all doors."),
    ] = None,
    days: Annotated[
        int,
        Field(description="Number of days to include in the summary (default 7)."),
    ] = 7,
) -> Dict[str, Any]:
    """Get activity summary."""
    logger.info("access_get_activity_summary called (door=%s, days=%s)", door_id, days)
    try:
        raw = await event_manager.get_activity_summary(door_id=door_id, days=days)
        summary = activity_summary_from_controller(raw).model_dump(exclude_none=True)
        return {"success": True, "data": summary}
    except Exception as e:
        logger.error("Error getting activity summary: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get activity summary: {e}"}


logger.info(
    "Event tools registered: access_list_events, access_get_event, "
    "access_recent_events, access_subscribe_events, access_get_activity_summary"
)
