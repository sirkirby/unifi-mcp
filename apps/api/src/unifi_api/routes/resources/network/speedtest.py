"""GET /v1/sites/{site_id}/speedtest-status — gateway speedtest status (DETAIL)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)

router = APIRouter()


@router.get(
    "/sites/{site_id}/speedtest-status",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/observability"],
)
async def get_speedtest_status(
    request: Request,
    site_id: str,
    gateway_mac: str = Query(..., description="MAC address of the gateway device"),
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "network")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "network",
            "device_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        status = await mgr.get_speedtest_status(gateway_mac)

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_speedtest_status")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(status or {}).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_speedtest_status")
        data = serializer.serialize(status or {})
        hint = registry.render_hint_for_tool("unifi_get_speedtest_status")
    return {"data": data, "render_hint": hint}
