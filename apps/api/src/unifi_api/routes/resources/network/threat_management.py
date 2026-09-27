"""Typed site-wide threat management (IDS/IPS) settings read."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.threat_management import ThreatManagementSettings
from unifi_api.routes.resources._common import require_capability, resolve_controller
from unifi_api.services.pydantic_models import Detail

router = APIRouter()


@router.get(
    "/sites/{site_id}/threat-management-settings",
    response_model=Detail[to_pydantic_model(ThreatManagementSettings)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/threat_management"],
)
async def get_threat_management_settings(
    request: Request, site_id: str, controller=Depends(resolve_controller)
) -> dict:
    require_capability(controller, "network")
    async with request.app.state.sessionmaker() as session:
        manager = await request.app.state.manager_factory.get_domain_manager(
            session, controller.id, "network", "system_manager", site=site_id
        )
        settings = await manager.get_threat_management_settings()
    data = ThreatManagementSettings.from_manager_output(
        settings,
        redact_sensitive=request.app.state.config.policy.response.redact_sensitive_fields,
    ).to_dict()
    return {"data": data, "render_hint": ThreatManagementSettings.render_hint("detail")}
