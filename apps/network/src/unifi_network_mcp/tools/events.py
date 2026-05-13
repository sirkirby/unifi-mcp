"""
UniFi Network MCP event and alarm tools.

This module provides MCP tools to view events and manage alarms on a UniFi Network Controller.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import preview_response
from unifi_core.network.models.events import event_log_from_controller
from unifi_core.network.models.system import alarm_from_controller, event_types_from_controller
from unifi_network_mcp.runtime import server

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependencies
_event_manager = None


def _get_event_manager():
    """Lazy-load the event manager to avoid circular imports."""
    global _event_manager
    if _event_manager is None:
        from unifi_core.network.managers.event_manager import EventManager
        from unifi_network_mcp.runtime import get_connection_manager

        _event_manager = EventManager(get_connection_manager())
    return _event_manager


@server.tool(
    name="unifi_list_events",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Returns timestamped event log entries (client connects/disconnects, device "
        "state changes, firmware updates, config changes) sorted newest-first. "
        "Filter by within_hours (default 24), event_type prefix (use unifi_get_event_types "
        "for valid prefixes), and paginate with start/limit. "
        "For critical alerts specifically, use unifi_list_alarms instead."
    ),
)
async def list_events(
    within_hours: Annotated[int, Field(description="Only return events from the last N hours (default 24)")] = 24,
    limit: Annotated[int, Field(description="Maximum number of events to return (default 100)")] = 100,
    start: Annotated[int, Field(description="Offset for pagination, skip the first N events (default 0)")] = 0,
    event_type: Annotated[
        Optional[str],
        Field(
            description="Filter by event type prefix (e.g., 'EVT_WU_' for wireless user events, 'EVT_SW_' for switch events). Use unifi_get_event_types to see valid prefixes"
        ),
    ] = None,
) -> Dict[str, Any]:
    """List events with optional filtering."""
    try:
        event_manager = _get_event_manager()
        events = await event_manager.get_events(
            within=within_hours,
            limit=limit,
            start=start,
            event_type=event_type,
        )

        shaped = [event_log_from_controller(e).model_dump(exclude_none=True) for e in events]
        return {
            "success": True,
            "site": event_manager._connection.site,
            "count": len(shaped),
            "filters": {
                "within_hours": within_hours,
                "limit": limit,
                "start": start,
                "event_type": event_type,
            },
            "events": shaped,
        }
    except Exception as e:
        logger.error("Error listing events: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list events: {e}"}


@server.tool(
    name="unifi_list_alarms",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Returns active alarms (security alerts, connectivity issues, firmware warnings). "
        "Each alarm includes type, message, timestamp, and related device/client MAC. "
        "By default shows only unresolved alarms; set include_archived=true for history. "
        "For general event logs (non-critical), use unifi_list_events."
    ),
)
async def list_alarms(
    include_archived: Annotated[
        bool, Field(description="When true, includes previously resolved/archived alarms. Default false (active only)")
    ] = False,
    limit: Annotated[int, Field(description="Maximum number of alarms to return (default 100)")] = 100,
) -> Dict[str, Any]:
    """List alarms with optional archived filter."""
    try:
        event_manager = _get_event_manager()
        alarms = await event_manager.get_alarms(
            archived=include_archived,
            limit=limit,
        )

        shaped = [alarm_from_controller(a).model_dump(exclude_none=False) for a in alarms]
        return {
            "success": True,
            "site": event_manager._connection.site,
            "count": len(shaped),
            "include_archived": include_archived,
            "alarms": shaped,
        }
    except Exception as e:
        logger.error("Error listing alarms: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list alarms: {e}"}


@server.tool(
    name="unifi_recent_events",
    description=(
        "Get recent events from the in-memory websocket buffer. This is fast "
        "(no API call) and returns events received via the real-time websocket "
        "stream. Supports filtering by event_type prefix, client/device mac, "
        "and limit. Use this for real-time monitoring; use unifi_list_events "
        "for historical queries."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def unifi_recent_events(
    event_type: Annotated[
        Optional[str],
        Field(
            description="Filter by event type prefix (e.g., 'EVT_WU_' for wireless user events). Use unifi_get_event_types for valid prefixes."
        ),
    ] = None,
    mac: Annotated[
        Optional[str],
        Field(description="Filter events to a specific client or device by MAC address. Omit to include all."),
    ] = None,
    limit: Annotated[
        Optional[int],
        Field(description="Maximum number of events to return from the buffer. Omit to return all buffered events."),
    ] = None,
) -> Dict[str, Any]:
    """Return recent events from the websocket ring buffer."""
    logger.info("unifi_recent_events called (type=%s, mac=%s)", event_type, mac)
    mgr = _get_event_manager()
    events = mgr.get_recent_from_buffer(event_type=event_type, mac=mac, limit=limit)
    shaped = [event_log_from_controller(e).model_dump(exclude_none=True) for e in events]
    return {"events": shaped, "count": len(shaped), "buffer_size": mgr.buffer_size}


@server.tool(
    name="unifi_subscribe_events",
    description=(
        "Returns a handle describing how to subscribe to live network events. "
        "Provides the MCP resource URI for the event stream and pointers to the "
        "buffered-event tool. Use this to set up continuous event monitoring."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def unifi_subscribe_events() -> Dict[str, Any]:
    """Return a handle describing how to subscribe to live network events."""
    logger.info("unifi_subscribe_events called")
    mgr = _get_event_manager()
    return {
        "resource_uri": "unifi://network/events",
        "summary_uri": "unifi://network/events/recent",
        "buffer_size": mgr.buffer_size,
        "instructions": (
            "Call unifi_recent_events to read buffered events. The unifi-api "
            "service (if running) exposes /v1/streams/network/events for live "
            "SSE consumption."
        ),
    }


@server.tool(
    name="unifi_get_event_types",
    description="""Get a list of known event type prefixes for filtering events.

Use these prefixes with unifi_list_events event_type parameter to filter specific event categories.""",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_event_types() -> Dict[str, Any]:
    """Get list of event type prefixes."""
    try:
        event_manager = _get_event_manager()
        prefixes = event_manager.get_event_type_prefixes()
        shaped = event_types_from_controller(prefixes)

        return {
            "success": True,
            "event_types": shaped.event_types,
            "usage": "Use prefix value with unifi_list_events event_type parameter",
        }
    except Exception as e:
        logger.error("Error getting event types: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get event types: {e}"}


@server.tool(
    name="unifi_archive_alarm",
    description="Archive (resolve/dismiss) a specific alarm by its ID",
    permission_category="events",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def archive_alarm(
    alarm_id: Annotated[
        str, Field(description="Unique identifier (_id) of the alarm to archive (from unifi_list_alarms)")
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, archives the alarm. When false (default), requires confirmation"),
    ] = False,
) -> Dict[str, Any]:
    """Archive a specific alarm."""
    if not confirm:
        return preview_response(
            action="archive",
            resource_type="alarm",
            resource_id=alarm_id,
            current_state={"archived": False},
            proposed_changes={"archived": True},
            resource_name=alarm_id,
            warnings=["This will archive/dismiss the alarm."],
        )

    try:
        event_manager = _get_event_manager()
        success = await event_manager.archive_alarm(alarm_id)

        if success:
            return {
                "success": True,
                "message": f"Alarm {alarm_id} archived successfully.",
            }
        return {"success": False, "error": f"Failed to archive alarm {alarm_id}."}
    except Exception as e:
        logger.error("Error archiving alarm %s: %s", alarm_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to archive alarm {alarm_id}: {e}"}


@server.tool(
    name="unifi_archive_all_alarms",
    description="Archive (resolve/dismiss) all active alarms",
    permission_category="events",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def archive_all_alarms(
    confirm: Annotated[
        bool,
        Field(description="When true, archives all active alarms. When false (default), requires confirmation"),
    ] = False,
) -> Dict[str, Any]:
    """Archive all active alarms."""
    if not confirm:
        return preview_response(
            action="archive",
            resource_type="alarm_collection",
            resource_id="all_active_alarms",
            current_state={"scope": "active_alarms"},
            proposed_changes={"archived": True},
            resource_name="all active alarms",
            warnings=["This will archive/dismiss every active alarm."],
        )

    try:
        event_manager = _get_event_manager()
        success = await event_manager.archive_all_alarms()

        if success:
            return {
                "success": True,
                "message": "All alarms archived successfully.",
            }
        return {"success": False, "error": "Failed to archive all alarms."}
    except Exception as e:
        logger.error("Error archiving all alarms: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to archive all alarms: {e}"}
