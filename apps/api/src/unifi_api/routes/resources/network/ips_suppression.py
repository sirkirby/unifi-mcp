"""GET /v1/sites/{site_id}/ips-suppressions: IPS signature suppressions and detection exclusions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.ips_suppression import IpsSuppressions
from unifi_api.routes.resources._common import require_capability, resolve_controller
from unifi_api.services.pydantic_models import Detail

router = APIRouter()


@router.get(
    "/sites/{site_id}/ips-suppressions",
    response_model=Detail[to_pydantic_model(IpsSuppressions)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/ips_suppression"],
)
async def list_ips_suppressions(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    require_capability(controller, "network")
    async with request.app.state.sessionmaker() as session:
        manager = await request.app.state.manager_factory.get_domain_manager(
            session, controller.id, "network", "system_manager", site=site_id
        )
        suppressions = await manager.list_ips_suppressions()
    data = IpsSuppressions.from_manager_output(
        suppressions,
        redact_sensitive=request.app.state.config.policy.response.redact_sensitive_fields,
    ).to_dict()
    return {"data": data, "render_hint": IpsSuppressions.render_hint("detail")}
