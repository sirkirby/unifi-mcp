"""GET /v1/sites/{site_id}/gateway-settings — the gateway (USG) settings singleton."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.gateway_settings import GatewaySettings
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pydantic_models import Detail

router = APIRouter()


@router.get(
    "/sites/{site_id}/gateway-settings",
    response_model=Detail[to_pydantic_model(GatewaySettings)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/gateway_settings"],
)
async def get_gateway_settings(
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
            "gateway_settings_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        settings = await mgr.get_gateway_settings()

    type_class = request.app.state.type_registry.lookup("network", "gateway_settings")
    data = type_class.from_manager_output(settings).to_dict()
    hint = type_class.render_hint("detail")
    return {
        "data": data,
        "render_hint": hint,
    }
