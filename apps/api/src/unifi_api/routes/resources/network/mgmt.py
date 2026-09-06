"""GET /v1/sites/{site_id}/mgmt-settings — device management posture (single GET, read-only).

SystemManager.get_settings("mgmt") returns a list[dict]; the MgmtSettings
type unwraps the first element as the DETAIL payload and reduces the stored
credentials and the authorised-key list to presence flags and a count.
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
    "/sites/{site_id}/mgmt-settings",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/mgmt"],
)
async def get_mgmt_settings(
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
            site=site_id,
        )
        settings = await mgr.get_settings("mgmt")
    # Registered in type_registry_init; there is no serializer fallback for this tool.
    type_class, kind = request.app.state.type_registry.lookup_tool("unifi_get_mgmt_settings")
    data = type_class.from_manager_output(settings).to_dict()
    return {"data": data, "render_hint": type_class.render_hint(kind)}
