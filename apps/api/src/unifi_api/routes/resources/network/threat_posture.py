"""Typed CyberSecure threat posture read."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.threat_posture import ThreatPosture
from unifi_api.routes.resources._common import require_capability, resolve_controller
from unifi_api.services.pydantic_models import Detail

router = APIRouter()


@router.get(
    "/sites/{site_id}/threat-posture",
    response_model=Detail[to_pydantic_model(ThreatPosture)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/threat_posture"],
    description="Read CyberSecure posture. Gateway device IDs belong to the legacy Network device family.",
)
async def get_threat_posture(
    request: Request, site_id: str, period: str = "DAY", controller=Depends(resolve_controller)
) -> dict:
    require_capability(controller, "network")
    async with request.app.state.sessionmaker() as session:
        manager = await request.app.state.manager_factory.get_domain_manager(
            session, controller.id, "network", "system_manager", site=site_id
        )
        try:
            posture = await manager.get_threat_posture(period=period)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid threat posture period; use HOUR, DAY, WEEK, or MONTH"
            ) from None
    data = ThreatPosture.from_manager_output(
        posture,
        redact_sensitive=request.app.state.config.policy.response.redact_sensitive_fields,
    ).to_dict()
    return {"data": data, "render_hint": ThreatPosture.render_hint("detail")}
