"""GET route for traffic flows (Insights > Flows).

The traffic-flows manager is server-paginated (it owns ``page_number`` /
``has_next``), so this route uses an opaque page cursor that encodes the
controller's 0-based page number rather than the list-style ``paginate()``.
"""

from __future__ import annotations

import base64
import inspect
import time
from typing import Annotated

from aiounifi.errors import AiounifiException
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.network.models.traffic_flows import Port

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.traffic_flow import (
    TrafficFlow,
    TrafficFlowStatistics,
)
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pydantic_models import Detail, Page
from unifi_api.services.traffic_flow_query import REJECTED, InvalidTrafficFlowFilter, build_query, is_rejection

router = APIRouter()


def _encode_flow_cursor(page: int) -> str:
    return base64.urlsafe_b64encode(str(page).encode()).decode()


def _decode_flow_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(base64.urlsafe_b64decode(cursor.encode()).decode()))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get(
    "/sites/{site_id}/traffic-flows",
    response_model=Page[to_pydantic_model(TrafficFlow)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/traffic-flows"],
)
async def get_traffic_flows(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    within_hours: int = Query(24, ge=1, le=8760),
    time_from: int | None = Query(None),
    time_to: int | None = Query(None),
    search_text: str | None = Query(None),
    # Each filter repeats for several values: ?risk=medium&risk=high
    risk: Annotated[list[str] | None, Query(description="Filter by risk (low/medium/high)")] = None,
    action: Annotated[list[str] | None, Query(description="Filter by action (allowed/blocked)")] = None,
    direction: Annotated[list[str] | None, Query(description="Filter by direction")] = None,
    protocol: Annotated[list[str] | None, Query(description="Filter by protocol")] = None,
    service: Annotated[list[str] | None, Query(description="Filter by service")] = None,
    source_mac: Annotated[list[str] | None, Query(description="Filter by source MAC")] = None,
    source_ip: Annotated[list[str] | None, Query(description="Filter by source IP")] = None,
    source_network_id: Annotated[list[str] | None, Query(description="Filter by source network ID")] = None,
    source_port: Annotated[list[Port] | None, Query(description="Filter by source port")] = None,
    destination_domain: Annotated[list[str] | None, Query(description="Filter by destination domain")] = None,
    destination_ip: Annotated[list[str] | None, Query(description="Filter by destination IP")] = None,
    destination_port: Annotated[list[Port] | None, Query(description="Filter by destination port")] = None,
    destination_region: Annotated[
        list[str] | None,
        Query(description="Filter by destination region, e.g. NL"),
    ] = None,
    page_size: int = Query(100, ge=1, le=1000),
    cursor: str | None = Query(None),
) -> dict:
    require_capability(controller, "network")
    # An ignored misspelt filter would answer with every flow, so refuse what is not declared.
    declared = inspect.signature(get_traffic_flows).parameters
    if unknown := sorted(set(request.query_params) - set(declared)):
        raise HTTPException(status_code=422, detail=f"unknown query parameter: {', '.join(unknown)}")
    page = _decode_flow_cursor(cursor)
    if (time_from is None) != (time_to is None):
        raise HTTPException(
            status_code=400,
            detail="provide both time_from and time_to, or use within_hours",
        )
    if time_from is None:
        now_ms = int(time.time() * 1000)
        time_from, time_to = now_ms - within_hours * 3600 * 1000, now_ms
    try:
        query = build_query(
            time_from=time_from,
            time_to=time_to,
            page_number=page,
            page_size=page_size,
            search_text=search_text,
            risk=risk,
            action=action,
            direction=direction,
            protocol=protocol,
            service=service,
            source_mac=source_mac,
            source_ip=source_ip,
            source_network_id=source_network_id,
            source_port=source_port,
            destination_domain=destination_domain,
            destination_ip=destination_ip,
            destination_port=destination_port,
            destination_region=destination_region,
        )
    except InvalidTrafficFlowFilter as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "network",
            "traffic_flow_manager",
            site=site_id,
        )
        try:
            result = await mgr.get_traffic_flows(query)
        except AiounifiException as exc:
            if is_rejection(exc):
                raise HTTPException(status_code=400, detail=REJECTED) from None
            raise

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_traffic_flows")
    if tool_type is None:
        # Registered at startup (discover_serializers refuses to boot otherwise);
        # this guard makes a future registry regression fail loudly, not with a
        # bare TypeError on the unpack below.
        raise HTTPException(status_code=500, detail="traffic-flow projection not registered")
    type_class, kind = tool_type
    rows = [type_class.from_manager_output(f).to_dict() for f in result.get("flows", [])]
    hint = type_class.render_hint(kind)
    next_cursor = _encode_flow_cursor(page + 1) if result.get("has_next") else None
    return {
        "items": rows,
        "next_cursor": next_cursor,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/traffic-flow-statistics",
    response_model=Detail[to_pydantic_model(TrafficFlowStatistics)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/traffic-flows"],
)
async def get_traffic_flow_statistics(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    period: str = Query("DAY"),
    top: int = Query(10, ge=1, le=100),
) -> dict:
    require_capability(controller, "network")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "network",
            "traffic_flow_manager",
            site=site_id,
        )
        try:
            result = await mgr.get_traffic_flow_statistics(period=period, top=top)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_traffic_flow_statistics")
    if tool_type is None:
        raise HTTPException(status_code=500, detail="traffic-flow-statistics projection not registered")
    type_class, kind = tool_type
    return {
        "data": type_class.from_manager_output(result).to_dict(),
        "render_hint": type_class.render_hint(kind),
    }
