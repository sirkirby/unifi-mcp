"""Event resources for UniFi Protect MCP server.

Registers an MCP resource at ``protect://events/stream`` that returns the
current contents of the websocket event buffer as a JSON array.

MCP clients can poll this resource to get the latest events without making
a tool call.  The ``protect_recent_events`` tool is an alternative for
clients that prefer tools over resources.

**Push notification limitation:**  The MCP spec defines
``notifications/resources/updated`` for server-initiated pushes, but
FastMCP's ``ServerSession.send_resource_updated(uri)`` is only accessible
during an active request context.  There is no public API for broadcasting
notifications from a background callback (e.g., websocket).  When FastMCP
adds broadcast support, we can wire EventManager._on_ws_message to push
notifications automatically.  Until then, clients should poll the resource
or use the ``protect_subscribe_events`` tool for instructions.
"""

from __future__ import annotations

import json
import logging

from mcp.types import Annotations

from unifi_protect_mcp.runtime import event_manager, server

logger = logging.getLogger(__name__)

EVENT_RESOURCE_META = {
    "io.unifi.resourceKind": "event-buffer",
    "io.unifi.updateMode": "poll",
    "io.unifi.pollIntervalMs": 1000,
    "io.unifi.protocolSubscribe": False,
    "io.unifi.relatedTools": ["protect_recent_events", "protect_subscribe_events"],
}

EVENT_SUMMARY_RESOURCE_META = {
    "io.unifi.resourceKind": "event-summary",
    "io.unifi.updateMode": "poll",
    "io.unifi.pollIntervalMs": 1000,
    "io.unifi.protocolSubscribe": False,
    "io.unifi.relatedTools": ["protect_recent_events", "protect_subscribe_events"],
}


@server.resource(
    "protect://events/stream",
    name="Protect Event Stream",
    title="Recent Protect Events",
    description=(
        "Real-time UniFi Protect events from the websocket buffer. "
        "Returns a JSON array of recent events (newest first). "
        "Poll this resource to monitor for motion, smart detections, rings, and other events."
    ),
    mime_type="application/json",
    annotations=Annotations(audience=["user", "assistant"], priority=0.8),
    meta=EVENT_RESOURCE_META,
)
async def event_stream() -> str:
    """Return recent events from the websocket ring buffer as JSON."""
    try:
        events = event_manager.get_recent_from_buffer()
        return json.dumps(events, default=str)
    except Exception as exc:
        logger.error("[event-resource] Error reading event buffer: %s", exc, exc_info=True)
        return json.dumps({"error": str(exc)})


@server.resource(
    "protect://events/stream/summary",
    name="Protect Event Stream Summary",
    title="Protect Event Buffer Summary",
    description=(
        "Summary statistics for the event buffer: total count, breakdown by "
        "event type, and breakdown by camera. Lightweight alternative to "
        "reading the full event stream."
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
        by_camera: dict[str, int] = {}
        for ev in events:
            et = ev.get("type", "unknown")
            by_type[et] = by_type.get(et, 0) + 1
            cam = ev.get("camera_id") or "unknown"
            by_camera[cam] = by_camera.get(cam, 0) + 1
        summary = {
            "total_events": len(events),
            "by_type": by_type,
            "by_camera": by_camera,
            "buffer_size": event_manager.buffer_size,
        }
        return json.dumps(summary, default=str)
    except Exception as exc:
        logger.error("[event-resource] Error generating summary: %s", exc, exc_info=True)
        return json.dumps({"error": str(exc)})


logger.info("Event resources registered: protect://events/stream, protect://events/stream/summary")
