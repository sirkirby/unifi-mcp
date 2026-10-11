"""Bounded, read-only Network incident evidence."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.incident_collection import (
    DEFAULT_CALLS,
    DEFAULT_ELAPSED_MS,
    DEFAULT_EVENTS,
    DEFAULT_WINDOW_SECONDS,
)

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.types.incident_evidence import IncidentEvidence
from unifi_api.routes.resources._common import require_capability, resolve_controller
from unifi_api.services.incident_evidence import IncidentRequestError, collect_network_evidence, network_request
from unifi_api.services.pydantic_models import Detail

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/sites/{site_id}/incident-evidence/network",
    response_model=Detail[dict],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/incident_evidence"],
    description=(
        "Collect bounded, read-only Network event evidence for one incident window. Returns a versioned "
        "unifi-incident-evidence document: cited records plus per-source coverage, failures and budget usage. "
        "The read stops at the first spent budget and says so; check coverage_complete before treating an "
        "empty result as an all-clear."
    ),
)
async def get_network_incident_evidence(
    request: Request,
    site_id: str,
    start: str = Query(..., description="Window start, ISO 8601 with a UTC offset (inclusive)"),
    end: str = Query(..., description="Window end, ISO 8601 with a UTC offset (exclusive)"),
    device_macs: list[str] | None = Query(
        None, description="Exact device MAC addresses; keeps only events naming one. Never device names"
    ),
    location_id: str | None = Query(
        None, description="Your label for the investigated location, recorded in source scope"
    ),
    max_window_seconds: int = Query(
        DEFAULT_WINDOW_SECONDS, description="Longest window to read; a longer window is not read (1-2592000)"
    ),
    max_events: int = Query(
        DEFAULT_EVENTS, description="Most event rows to read, including rows outside the window (1-10000)"
    ),
    max_calls: int = Query(
        DEFAULT_CALLS, description="Most HTTP requests to the controller, retries and the API probe included (1-100)"
    ),
    max_elapsed_ms: int = Query(
        DEFAULT_ELAPSED_MS,
        description="Most wall time, connecting included; a read still running is cancelled (1-120000)",
    ),
    mappings: str | None = Query(
        None,
        description=(
            "JSON-encoded array of explicit exact-identifier assertions, each {entity, target, source} where "
            "entity and target are {kind, id_kind, id} and source is operator_input or product_inventory"
        ),
    ),
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "network")
    try:
        # Validated before any controller I/O: invalid input never acquires a manager.
        incident = network_request(
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
    except IncidentRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    factory = request.app.state.manager_factory
    async with request.app.state.sessionmaker() as session:

        async def acquire() -> Any:
            return await factory.get_event_reader(session, controller.id, "network", site=site_id)

        try:
            # Acquisition happens inside the first bounded read; its failures are source failures.
            evidence = await collect_network_evidence(acquire, incident, site=site_id)
        except Exception as exc:
            logger.error("Failed to collect Network incident evidence: %s", type(exc).__name__)
            raise HTTPException(
                status_code=502, detail=f"Failed to collect incident evidence ({type(exc).__name__})."
            ) from None
    data = IncidentEvidence.from_manager_output(evidence).to_dict()
    return {"data": data, "render_hint": IncidentEvidence.render_hint("detail")}
