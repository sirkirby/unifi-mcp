"""GET /v1/sites/{site_id}/snmp-settings — SNMP settings (single GET).

Phase 5A PR2 Cluster 5. SystemManager.get_settings("snmp") returns a
list[dict]; the SnmpSettingsSerializer unwraps the first element as the
DETAIL payload.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)

router = APIRouter()


@router.get(
    "/sites/{site_id}/snmp-settings",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/snmp"],
)
async def get_snmp_settings(
    request: Request,
    site_id: str,
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
            "system_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        settings = await mgr.get_settings("snmp")
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_snmp_settings")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(settings).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_snmp_settings")
        data = serializer.serialize(settings)
        hint = registry.render_hint_for_tool("unifi_get_snmp_settings")
    return {"data": data, "render_hint": hint}
