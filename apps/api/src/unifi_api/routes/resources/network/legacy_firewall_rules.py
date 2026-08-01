"""GET /v1/sites/{site_id}/firewall/legacy-rules — legacy firewall rules.

Rules from the pre-zone-based firewall engine, read from V1 ``/rest/firewallrule``.

A site running the legacy engine returns nothing from the zone-based endpoints
(``/firewall/policies``, ``/firewall/zones``), which is indistinguishable from
"no firewall rules configured" unless this route is consulted as well.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.firewall import LegacyFirewallRule
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Page

router = APIRouter()


def _rule_key(obj) -> tuple:
    """Order by ruleset then rule_index, which is how the engine evaluates them."""
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    index = raw.get("rule_index")
    if not isinstance(index, int) or isinstance(index, bool):
        index = 0
    return (raw.get("ruleset") or "", index, raw.get("_id") or raw.get("id") or "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get(
    "/sites/{site_id}/firewall/legacy-rules",
    response_model=Page[to_pydantic_model(LegacyFirewallRule)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/firewall"],
)
async def list_legacy_firewall_rules(
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
        items = await mgr.get_legacy_firewall_rules()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_rule_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_list_legacy_firewall_rules")
    if tool_type is not None:
        type_class, kind = tool_type
        rows = [type_class.from_manager_output(i).to_dict() for i in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_list_legacy_firewall_rules")
        rows = [serializer.serialize(i) for i in page]
        hint = registry.render_hint_for_tool("unifi_list_legacy_firewall_rules")
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }
