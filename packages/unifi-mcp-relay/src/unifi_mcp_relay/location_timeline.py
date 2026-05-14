"""Cross-product location timeline tool for the relay sidecar.

Fans out event queries to all connected servers via the ToolForwarder,
merges results into a single time-sorted timeline, and returns a unified
response. This tool is only available in relay mode — local/stdio mode
uses the single-product event timeline from unifi-mcp-shared.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from unifi_core.event_timeline import NormalizedEvent, filter_by_area, merge_timelines

logger = logging.getLogger("unifi-mcp-relay")


def validate_timeline_input(
    *,
    start_time: str,
    end_time: str,
    location_id: str | None = None,
    is_relay_mode: bool = True,
) -> list[str]:
    """Validate timeline tool input parameters.

    Returns list of error messages (empty if valid).
    """
    errors: list[str] = []

    if not start_time:
        errors.append("start_time is required")
    if not end_time:
        errors.append("end_time is required")

    parsed_start = None
    parsed_end = None

    if start_time:
        try:
            parsed_start = datetime.fromisoformat(start_time)
        except ValueError:
            errors.append(f"start_time is not valid ISO 8601: '{start_time}'")

    if end_time:
        try:
            parsed_end = datetime.fromisoformat(end_time)
        except ValueError:
            errors.append(f"end_time is not valid ISO 8601: '{end_time}'")

    if parsed_start and parsed_end and parsed_end <= parsed_start:
        errors.append("end_time must be after start_time")

    if location_id and not is_relay_mode:
        errors.append("location_id is only meaningful in relay mode. Omit this parameter for local connections.")

    return errors


def build_timeline_summary(events: list[NormalizedEvent]) -> dict[str, Any]:
    """Build summary statistics from a list of events."""
    if not events:
        return {
            "total_events": 0,
            "by_product": {},
            "by_type": {},
            "by_location": {},
        }

    by_product = Counter(e.product for e in events)
    by_type = Counter(e.event_type for e in events)
    by_location = Counter(e.location_id for e in events if e.location_id is not None)

    summary: dict[str, Any] = {
        "total_events": len(events),
        "by_product": dict(by_product),
        "by_type": dict(by_type),
        "by_location": dict(by_location),
        "time_range": {
            "start": events[0].timestamp.isoformat(),
            "end": events[-1].timestamp.isoformat(),
        },
    }

    return summary


def build_timeline_response(
    events: list[NormalizedEvent],
) -> dict[str, Any]:
    """Build the final tool response from merged events."""
    return {
        "success": True,
        "data": {
            "timeline": [e.to_dict() for e in events],
            "summary": build_timeline_summary(events),
        },
    }


# ---------------------------------------------------------------------------
# Tool definition for relay-native registration
# ---------------------------------------------------------------------------

#: Tool name used for registration and routing.
TOOL_NAME = "unifi_location_timeline"

#: Tool metadata used by the relay to register the tool in its catalog.
TOOL_DESCRIPTION = (
    "Query a unified, cross-product event timeline for this location. "
    "Fans out to Network, Protect, and Access servers and merges results "
    "into a single time-sorted view."
)

TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "start_time": {
            "type": "string",
            "description": "ISO 8601 start of time range (required).",
        },
        "end_time": {
            "type": "string",
            "description": "ISO 8601 end of time range (required).",
        },
        "products": {
            "type": "array",
            "items": {"type": "string", "enum": ["network", "protect", "access"]},
            "description": "Limit query to specific products (default: all).",
        },
        "area_hint": {
            "type": "string",
            "description": "Case-insensitive substring to filter events by area name.",
        },
        "event_types": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Only include events with these event_type values.",
        },
        "location_id": {
            "type": "string",
            "description": "Location ID filter (relay mode only).",
        },
    },
    "required": ["start_time", "end_time"],
}

TOOL_ANNOTATIONS: dict[str, Any] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------


async def handle_location_timeline(
    arguments: dict[str, Any],
    forwarder: Any,  # ToolForwarder instance
    location_id: str | None = None,
    location_name: str | None = None,
    is_relay_mode: bool = True,
) -> dict[str, Any]:
    """Handle the unifi_location_timeline tool call.

    Fans out event queries to connected product servers, merges results,
    applies filters, and returns a unified timeline.
    """
    start_time = arguments.get("start_time", "")
    end_time = arguments.get("end_time", "")
    req_location_id = arguments.get("location_id")
    products = arguments.get("products")
    area_hint = arguments.get("area_hint")
    event_types = arguments.get("event_types")

    errors = validate_timeline_input(
        start_time=start_time,
        end_time=end_time,
        location_id=req_location_id,
        is_relay_mode=is_relay_mode,
    )
    if errors:
        return {"success": False, "error": "; ".join(errors)}

    # Event-listing tool names per product
    event_tool_map = {
        "network": "unifi_list_events",
        "protect": "unifi_protect_list_events",
        "access": "unifi_access_list_events",
    }

    target_products = products or list(event_tool_map.keys())
    all_event_lists: list[list[NormalizedEvent]] = []

    for product in target_products:
        tool_name = event_tool_map.get(product)
        if not tool_name:
            continue
        try:
            result = await forwarder.forward(
                tool_name=tool_name,
                arguments={"start_time": start_time, "end_time": end_time},
            )
            if result and result.get("success"):
                events = _normalize_product_events(
                    product,
                    result.get("data", []),
                    location_id=location_id,
                    location_name=location_name,
                )
                all_event_lists.append(events)
        except Exception as e:
            logger.warning("[timeline] Failed to query %s events: %s", product, e)

    merged = merge_timelines(all_event_lists)

    if area_hint:
        merged = filter_by_area(merged, area_hint=area_hint)

    if event_types:
        merged = [e for e in merged if e.event_type in event_types]

    return build_timeline_response(merged)


def _normalize_product_events(
    product: str,
    raw_events: list[dict[str, Any]],
    location_id: str | None = None,
    location_name: str | None = None,
) -> list[NormalizedEvent]:
    """Normalize raw product events to NormalizedEvent instances.

    Placeholder normalization -- maps common fields. Each product's event
    schema is different; full normalization will be refined per product.
    """
    events: list[NormalizedEvent] = []
    for raw in raw_events:
        try:
            ts_raw = raw.get("timestamp") or raw.get("datetime") or raw.get("time", "")
            if isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc)
            else:
                ts = datetime.fromisoformat(str(ts_raw))

            events.append(
                NormalizedEvent(
                    timestamp=ts,
                    product=product,
                    event_type=raw.get("type", raw.get("event_type", "unknown")),
                    summary=raw.get("msg", raw.get("description", raw.get("type", "event"))),
                    normalized_fields={},
                    raw=raw,
                    location_id=location_id,
                    location_name=location_name,
                    area_names=[],
                )
            )
        except Exception as e:
            logger.debug("[timeline] Skipping unparseable event: %s", e)

    return events
