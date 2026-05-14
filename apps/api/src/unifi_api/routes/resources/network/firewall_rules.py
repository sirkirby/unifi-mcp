"""GET /v1/sites/{site_id}/firewall/rules[/{rule_id}] — firewall policies."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.firewall import FirewallRule
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter()


def _rule_key(obj) -> tuple:
    """Sort by (0, id) — id-stable order, no time component."""
    raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
    return (0, raw.get("_id") or raw.get("id") or "")


@router.get(
    "/sites/{site_id}/firewall/rules",
    response_model=Page[to_pydantic_model(FirewallRule)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/firewall"],
)
async def list_firewall_rules(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
) -> dict:
    require_capability(controller, "network")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "network",
            "firewall_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        all_rules = await mgr.get_firewall_policies()

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(all_rules),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_rule_key,
    )

    type_class = request.app.state.type_registry.lookup("network", "firewall/rules")
    items = [type_class.from_manager_output(r).to_dict() for r in page]
    hint = type_class.render_hint("list")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/firewall/rules/{rule_id}",
    response_model=Detail[to_pydantic_model(FirewallRule)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/firewall"],
)
async def get_firewall_rule(
    request: Request,
    site_id: str,
    rule_id: str,
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
                "firewall_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "network")
            if cm.site != site_id:
                await cm.set_site(site_id)
            # firewall_manager exposes get_firewall_policies (list) but not a
            # singular get_firewall_policy_details. Fetch the list and filter
            # by id; the manager already caches/normalizes the response.
            all_rules = await mgr.get_firewall_policies(include_predefined=True)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    rule = None
    for r in all_rules:
        raw = getattr(r, "raw", r if isinstance(r, dict) else {})
        rid = raw.get("_id") or raw.get("id")
        if rid == rule_id:
            rule = r
            break
    if rule is None:
        raise HTTPException(status_code=404, detail="firewall rule not found")

    type_class = request.app.state.type_registry.lookup("network", "firewall/rules/{id}")
    data = type_class.from_manager_output(rule).to_dict()
    hint = type_class.render_hint("detail")
    return {
        "data": data,
        "render_hint": hint,
    }
