"""GET /v1/sites/{site_id}/lookup-by-ip — find a client by IP address.

Phase 5A PR1 Cluster 2 — clients & user groups. Single DETAIL endpoint
backed by ``ClientManager.get_client_by_ip`` (Phase 4A discovered the
manager method name diverges from the tool name).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)

router = APIRouter()


@router.get(
    "/sites/{site_id}/lookup-by-ip",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/lookup"],
)
async def lookup_client_by_ip(
    request: Request,
    site_id: str,
    ip: str = Query(..., description="Client IP address to look up"),
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "network")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "network",
                "client_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "network")
            if cm.site != site_id:
                await cm.set_site(site_id)
            client = await mgr.get_client_by_ip(ip)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if client is None:
        raise HTTPException(status_code=404, detail=f"client with ip {ip} not found")

    type_class = request.app.state.type_registry.lookup("network", "client_lookup")
    data = type_class.from_manager_output(client).to_dict()
    hint = type_class.render_hint("detail")
    return {
        "data": data,
        "render_hint": hint,
    }
