"""Bounded, read-only Network incident evidence.

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
    require_label,
)
from unifi_core.incident_evidence_view import (
    DEFAULT_MAX_RECORDS_RETURNED,
    MAX_RECORDS_RETURNED,
    EvidencePresentation,
    EvidenceViewTooLarge,
)
from unifi_core.network.incident_collection import collect_network_incident_evidence
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_network_mcp.runtime import server

logger = logging.getLogger(__name__)

_OPERATION = "Failed to collect incident evidence"


@server.tool(
    name="unifi_get_incident_evidence",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Collects bounded, read-only Network event evidence for one incident window. Returns a "
        "unifi-incident-evidence-view by default: every source's coverage, failures and budget usage "
        "plus a bounded list of record citations, with omitted records counted; detail='full' returns "
        "the whole unifi-incident-evidence document. Stops at the first spent budget and says so; "
        "check coverage_complete before treating an empty result as an all-clear."
    ),
)
async def get_incident_evidence(
    start: Annotated[str, Field(description="Window start, ISO 8601 with a UTC offset (inclusive)")],
    end: Annotated[str, Field(description="Window end, ISO 8601 with a UTC offset (exclusive)")],
    device_macs: Annotated[
        Optional[List[str]],
        Field(description="Exact device MAC addresses; keeps only events naming one. Never device names"),
    ] = None,
    location_id: Annotated[
        Optional[str], Field(description="Your label for the investigated location, recorded in source scope")
    ] = None,
    max_window_seconds: Annotated[
        int, Field(description="Longest window to read; a longer window is not read (1-2592000)")
    ] = DEFAULT_WINDOW_SECONDS,
    max_events: Annotated[
        int, Field(description="Most event rows to read, including rows outside the window (1-10000)")
    ] = DEFAULT_EVENTS,
    max_calls: Annotated[
        int, Field(description="Most HTTP requests to the controller, retries and the API probe included (1-100)")
    ] = DEFAULT_CALLS,
    max_elapsed_ms: Annotated[
        int, Field(description="Most wall time, connecting included; a read still running is cancelled (1-120000)")
    ] = DEFAULT_ELAPSED_MS,
    mappings: Annotated[
        Optional[List[Dict[str, Any]]],
        Field(
            description=(
                "Explicit exact-identifier assertions, each {entity, target, source} where entity and target "
                "are {kind, id_kind, id} and source is operator_input or product_inventory (at most 20)"
            )
        ),
    ] = None,
    # Validated by Core with the request, so a rejected value is never echoed.
    detail: Annotated[
        str,
        Field(
            description="view: coverage plus bounded record citations; full: the whole evidence document",
            json_schema_extra={"enum": ["view", "full"]},
        ),
    ] = "view",
    max_records_returned: Annotated[
        Optional[int],
        Field(
            description=(
                f"Most record citations in the view (default {DEFAULT_MAX_RECORDS_RETURNED}, "
                f"1-{MAX_RECORDS_RETURNED}); omitted records stay in coverage. View only"
            )
        ),
    ] = None,
    resume_after: Annotated[
        Optional[str],
        Field(
            description=(
                "record_selection.next_cursor from an earlier view of the same request; returns the records "
                "after it. View only"
            )
        ),
    ] = None,
) -> Dict[str, Any]:
    """Collect bounded Network incident evidence."""
    try:
        request = NetworkIncidentRequest(
            start=start,
            end=end,
            device_macs=device_macs,
            location_id=location_id,
            max_window_seconds=max_window_seconds,
            max_events=max_events,
            max_calls=max_calls,
            max_elapsed_ms=max_elapsed_ms,
            mappings=mappings,
        )
    except ValidationError as exc:
        return {"success": False, "error": f"{_OPERATION}: {describe_validation_error(exc, NetworkIncidentRequest)}"}
    try:
        presentation = EvidencePresentation(
            detail=detail, max_records_returned=max_records_returned, resume_after=resume_after
        )
    except ValidationError as exc:
        return {"success": False, "error": f"{_OPERATION}: {describe_validation_error(exc, EvidencePresentation)}"}
    try:
        from unifi_network_mcp.runtime import get_connection_manager, get_event_manager

        # The configured site is recorded in each source's scope, so it is held to the label rule.
        try:
            site = require_label("configured site", get_connection_manager().site)
        except ValueError as exc:
            return {
                "success": False,
                "error": f"{_OPERATION}: {exc}; set UNIFI_NETWORK_SITE to the site's name, for example default",
            }
        evidence = await collect_network_incident_evidence(get_event_manager(), request, site=site)
        return {"success": True, "data": presentation.render(evidence)}
    except EvidenceViewTooLarge as exc:
        return {"success": False, "error": f"{_OPERATION}: {exc}"}
    except Exception as exc:
        logger.error("Error collecting Network incident evidence: %s", type(exc).__name__)
        return {"success": False, "error": f"{_OPERATION}: {type(exc).__name__}"}
