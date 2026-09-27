"""Read-only V2 NAT rule resources."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.nat import NatRule
from unifi_api.routes.resources._common import require_capability, resolve_controller
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Detail, Page

logger = logging.getLogger(__name__)
router = APIRouter()


def _id_key(obj: dict) -> tuple:
    return (0, obj.get("_id") or obj.get("id") or "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor") from None


@router.get(
    "/sites/{site_id}/nat-rules",
    response_model=Page[to_pydantic_model(NatRule)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/nat"],
    description=(
        "List V2 NAT rules in descending controller ID order. "
        "These IDs are scoped to the V2 NAT tool family — "
        "do not pass them to port-forward or Integration API tools."
    ),
)
async def list_nat_rules(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
) -> dict:
    require_capability(controller, "network")
    cursor_obj = _decode_cursor(cursor)
    try:
        async with request.app.state.sessionmaker() as session:
            mgr = await request.app.state.manager_factory.get_domain_manager(
                session, controller.id, "network", "nat_manager", site=site_id
            )
            rules = await mgr.list_nat_rules()
    except Exception as exc:
        logger.error("Failed to list NAT rules: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=f"Failed to list NAT rules ({type(exc).__name__}).") from None

    try:
        page, next_cursor = paginate(list(rules), limit=limit, cursor=cursor_obj, key_fn=_id_key)
        redact_sensitive = request.app.state.config.policy.response.redact_sensitive_fields
        return {
            "items": [NatRule.from_manager_output(rule, redact_sensitive=redact_sensitive).to_dict() for rule in page],
            "next_cursor": next_cursor.encode() if next_cursor else None,
            "render_hint": NatRule.render_hint("list"),
        }
    except Exception as exc:
        logger.error("Failed to project NAT rule list: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=f"Failed to list NAT rules ({type(exc).__name__}).") from None


@router.get(
    "/sites/{site_id}/nat-rules/{rule_id}",
    response_model=Detail[to_pydantic_model(NatRule)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/nat"],
    description="Get a NAT rule by its V2 NAT-family ID; port-forward and Integration API IDs are not portable.",
)
async def get_nat_rule(
    request: Request,
    site_id: str,
    rule_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "network")
    if not rule_id.strip():
        raise HTTPException(status_code=400, detail="rule_id is required")
    try:
        async with request.app.state.sessionmaker() as session:
            mgr = await request.app.state.manager_factory.get_domain_manager(
                session, controller.id, "network", "nat_manager", site=site_id
            )
            rule = await mgr.get_nat_rule(rule_id)
    except UniFiNotFoundError:
        raise HTTPException(status_code=404, detail="NAT rule not found") from None
    except Exception as exc:
        logger.error("Failed to get NAT rule: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=f"Failed to get NAT rule ({type(exc).__name__}).") from None

    try:
        redact_sensitive = request.app.state.config.policy.response.redact_sensitive_fields
        return {
            "data": NatRule.from_manager_output(rule, redact_sensitive=redact_sensitive).to_dict(),
            "render_hint": NatRule.render_hint("detail"),
        }
    except Exception as exc:
        logger.error("Failed to project NAT rule: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=f"Failed to get NAT rule ({type(exc).__name__}).") from None
