"""Event resources for UniFi Access MCP server.

Registers an MCP resource at ``access://events/stream`` that returns the
current contents of the event buffer as a JSON array.

MCP clients can poll this resource to get the latest events without making
a tool call.  The ``access_recent_events`` tool is an alternative for
clients that prefer tools over resources.
"""

from __future__ import annotations

import json
import logging

from mcp.types import Annotations

from unifi_access_mcp.runtime import event_manager, server

logger = logging.getLogger(__name__)

EVENT_RESOURCE_META = {
    "io.unifi.resourceKind": "event-buffer",
    "io.unifi.updateMode": "poll",
    "io.unifi.pollIntervalMs": 1000,
    "io.unifi.protocolSubscribe": False,
    "io.unifi.relatedTools": ["access_recent_events", "access_subscribe_events"],
}

EVENT_SUMMARY_RESOURCE_META = {
    "io.unifi.resourceKind": "event-summary",
    "io.unifi.updateMode": "poll",
    "io.unifi.pollIntervalMs": 1000,
    "io.unifi.protocolSubscribe": False,
    "io.unifi.relatedTools": ["access_recent_events", "access_subscribe_events"],
}


@server.resource(
    "access://events/stream",
    name="Access Event Stream",
    title="Recent Access Events",
    description=(
        "Real-time UniFi Access events from the event buffer. "
        "Returns a JSON array of recent events (newest first). "
        "Poll this resource to monitor for door opens, denials, and other events."
    ),
    mime_type="application/json",
    annotations=Annotations(audience=["user", "assistant"], priority=0.8),
    meta=EVENT_RESOURCE_META,
)
async def event_stream() -> str:
    """Return recent events from the event ring buffer as JSON."""
    try:
        events = event_manager.get_recent_from_buffer()
        return json.dumps(events, default=str)
    except Exception as exc:
        logger.error("[event-resource] Error reading event buffer: %s", exc, exc_info=True)
        return json.dumps({"error": str(exc)})


@server.resource(
    "access://events/stream/summary",
    name="Access Event Stream Summary",
    title="Access Event Buffer Summary",
    description=(
        "Summary statistics for the event buffer: total count and breakdown by "
        "event type. Lightweight alternative to reading the full event stream."
    ),
    mime_type="application/json",
    annotations=Annotations(audience=["assistant"], priority=0.5),
    meta=EVENT_SUMMARY_RESOURCE_META,
)
async def event_stream_summary() -> str:
    """Return summary statistics of the event buffer."""
    try:
        events = event_manager.get_recent_from_buffer()
        by_type: dict[str, int] = {}
        by_door: dict[str, int] = {}
        for ev in events:
            et = ev.get("type", "unknown")
            by_type[et] = by_type.get(et, 0) + 1
            door = ev.get("door_id") or "unknown"
            by_door[door] = by_door.get(door, 0) + 1
        summary = {
            "total_events": len(events),
            "by_type": by_type,
            "by_door": by_door,
            "buffer_size": event_manager.buffer_size,
        }
        return json.dumps(summary, default=str)
    except Exception as exc:
        logger.error("[event-resource] Error generating summary: %s", exc, exc_info=True)
        return json.dumps({"error": str(exc)})


logger.info("Event resources registered: access://events/stream, access://events/stream/summary")
