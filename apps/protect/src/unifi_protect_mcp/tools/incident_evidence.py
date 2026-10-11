"""Bounded, read-only Protect incident evidence.

This module holds only read-only tools: lazy registration loads it at
startup (``LAZY_DIRECT_TOOLS``) so read-only clients can call it directly.
"""

import logging
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.incident_collection import (
    DEFAULT_CALLS,
    DEFAULT_ELAPSED_MS,
    DEFAULT_EVENTS,
    DEFAULT_WINDOW_SECONDS,
    describe_validation_error,
)
from unifi_core.incident_evidence import evidence_to_json
from unifi_core.protect.incident_collection import collect_protect_incident_evidence
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest
from unifi_protect_mcp.runtime import event_manager, server

logger = logging.getLogger(__name__)

_OPERATION = "Failed to collect incident evidence"


@server.tool(
    name="protect_get_incident_evidence",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Collects bounded, read-only Protect event evidence for one incident window and returns a "
        "versioned unifi-incident-evidence document: cited records plus per-source coverage, failures "
        "and budget usage. Each camera ID is its own source. Stops at the first spent budget and says "
        "so; check coverage_complete before treating an empty result as an all-clear."
    ),
)
async def get_incident_evidence(
    start: Annotated[str, Field(description="Window start, ISO 8601 with a UTC offset (inclusive)")],
    end: Annotated[str, Field(description="Window end, ISO 8601 with a UTC offset (exclusive)")],
    camera_ids: Annotated[
        Optional[List[str]],
        Field(description="Exact Protect camera IDs, each read as its own source; omit for every camera"),
    ] = None,
    location_id: Annotated[
        Optional[str], Field(description="Your label for the investigated location, recorded in source scope")
    ] = None,
    max_window_seconds: Annotated[
        int, Field(description="Longest window to read; a longer window is not read (1-2592000)")
    ] = DEFAULT_WINDOW_SECONDS,
    max_events: Annotated[int, Field(description="Most event rows to read across cameras (1-10000)")] = DEFAULT_EVENTS,
    max_calls: Annotated[int, Field(description="Most NVR page reads across cameras (1-100)")] = DEFAULT_CALLS,
    max_elapsed_ms: Annotated[
        int, Field(description="Most wall time for reads; a read still running is cancelled (1-120000)")
    ] = DEFAULT_ELAPSED_MS,
    mappings: Annotated[
        Optional[List[Dict[str, Any]]],
        Field(
            description=(
                "Explicit exact-identifier assertions, each {entity, target, source} where entity and target "
                "are {kind, id_kind, id} and source is operator_input or product_inventory"
            )
        ),
    ] = None,
) -> Dict[str, Any]:
    """Collect bounded Protect incident evidence."""
    try:
        request = ProtectIncidentRequest(
            start=start,
            end=end,
            camera_ids=camera_ids,
            location_id=location_id,
            max_window_seconds=max_window_seconds,
            max_events=max_events,
            max_calls=max_calls,
            max_elapsed_ms=max_elapsed_ms,
            mappings=mappings,
        )
    except ValidationError as exc:
        return {"success": False, "error": f"{_OPERATION}: {describe_validation_error(exc)}"}
    try:
        evidence = await collect_protect_incident_evidence(event_manager, request)
        return {"success": True, "data": evidence_to_json(evidence)}
    except Exception as exc:
        logger.error("Error collecting Protect incident evidence: %s", type(exc).__name__)
        return {"success": False, "error": f"{_OPERATION}: {type(exc).__name__}"}
