"""Bounded, read-only Protect incident evidence."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.types.incident_evidence import IncidentEvidence
from unifi_api.routes.resources._common import require_capability, resolve_controller
from unifi_api.services.incident_evidence import (
    DEFAULT_CALLS,
    DEFAULT_ELAPSED_MS,
    DEFAULT_EVENTS,
    DEFAULT_WINDOW_SECONDS,
    IncidentRequestError,
    collect_protect_evidence,
)
from unifi_api.services.pydantic_models import Detail

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/sites/{site_id}/incident-evidence/protect",
    response_model=Detail[dict],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/incident_evidence"],
    description=(
        "Collect bounded, read-only Protect event evidence for one incident window. Returns a versioned "
        "unifi-incident-evidence document: cited records plus per-source coverage, failures and budget usage. "
        "Each camera ID is its own source. The read stops at the first spent budget and says so; check "
        "coverage_complete before treating an empty result as an all-clear."
    ),
)
async def get_protect_incident_evidence(
    request: Request,
    site_id: str,
    start: str = Query(..., description="Window start, ISO 8601 with a UTC offset (inclusive)"),
    end: str = Query(..., description="Window end, ISO 8601 with a UTC offset (exclusive)"),
    camera_ids: list[str] | None = Query(
        None, description="Exact Protect camera IDs, each read as its own source; omit for every camera"
    ),
    location_id: str | None = Query(
        None, description="Your label for the investigated location, recorded in source scope"
    ),
    max_window_seconds: int = Query(
        DEFAULT_WINDOW_SECONDS, description="Longest window to read; a longer window is not read (1-2592000)"
    ),
    max_events: int = Query(DEFAULT_EVENTS, description="Most event rows to read across cameras (1-10000)"),
    max_calls: int = Query(DEFAULT_CALLS, description="Most NVR page reads across cameras (1-100)"),
    max_elapsed_ms: int = Query(
        DEFAULT_ELAPSED_MS, description="Most wall time for reads; a read still running is cancelled (1-120000)"
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
    require_capability(controller, "protect")
    async with request.app.state.sessionmaker() as session:
        events = await request.app.state.manager_factory.get_domain_manager(
            session, controller.id, "protect", "event_manager"
        )
        try:
            evidence = await collect_protect_evidence(
                events,
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
        except IncidentRequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except Exception as exc:
            logger.error("Failed to collect Protect incident evidence: %s", type(exc).__name__)
            raise HTTPException(
                status_code=502, detail=f"Failed to collect incident evidence ({type(exc).__name__})."
            ) from None
    data = IncidentEvidence.from_manager_output(evidence).to_dict()
    return {"data": data, "render_hint": IncidentEvidence.render_hint("detail")}
