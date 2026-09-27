"""Typed site-wide mDNS settings read."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.mdns import MdnsSettings
from unifi_api.routes.resources._common import require_capability, resolve_controller
from unifi_api.services.pydantic_models import Detail

router = APIRouter()


@router.get(
    "/sites/{site_id}/mdns-settings",
    response_model=Detail[to_pydantic_model(MdnsSettings)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/mdns"],
)
async def get_mdns_settings(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    require_capability(controller, "network")
    async with request.app.state.sessionmaker() as session:
        manager = await request.app.state.manager_factory.get_domain_manager(
            session, controller.id, "network", "system_manager", site=site_id
        )
        settings = await manager.get_mdns_settings()
    data = MdnsSettings.from_manager_output(
        settings,
        redact_sensitive=request.app.state.config.policy.response.redact_sensitive_fields,
    ).to_dict()
    return {"data": data, "render_hint": MdnsSettings.render_hint("detail")}
