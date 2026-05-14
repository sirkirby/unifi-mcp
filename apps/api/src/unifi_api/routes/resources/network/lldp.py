"""GET /v1/sites/{site_id}/lldp-neighbors — LLDP discovery (wrapper-dict → LIST).

Manager returns ``{name, model, lldp_table: [...]}`` per device. The route
unwraps the ``lldp_table`` array and exposes it as a paginated LIST.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


def _lldp_key(row) -> tuple:
    if isinstance(row, dict):
        return (row.get("local_port_idx") or 0, row.get("chassis_id") or "")
    return (0, "")


def _normalize_lldp_row(r: dict) -> dict:
    return {
        "local_port_idx": r.get("local_port_idx"),
        "chassis_id": r.get("chassis_id"),
        "port_id": r.get("port_id"),
        "system_name": r.get("system_name"),
        "capabilities": r.get("capabilities", []) or [],
    }


@router.get(
    "/sites/{site_id}/lldp-neighbors",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/lldp"],
)
async def list_lldp_neighbors(
    request: Request,
    site_id: str,
    device_mac: str = Query(..., description="MAC address of the switch"),
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
            "switch_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        wrapper = await mgr.get_lldp_neighbors(device_mac)
    if wrapper is None:
        raise HTTPException(status_code=404, detail=f"switch '{device_mac}' not found")

    items_raw = wrapper.get("lldp_table", []) if isinstance(wrapper, dict) else []

    cursor_obj: Cursor | None = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(items_raw),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_lldp_key,
    )

    items = [_normalize_lldp_row(r) for r in page]
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_lldp_neighbors")
    if tool_type is not None:
        type_class, _kind = tool_type
        # The route exposes lldp_table rows as a paginated LIST regardless of
        # the upstream tool's DETAIL kind on the wrapper-dict.
        hint = {**type_class.render_hint("list"), "kind": "list"}
    else:
        registry = request.app.state.serializer_registry
        hint = registry.render_hint_for_tool("unifi_get_lldp_neighbors")
        hint = {**hint, "kind": "list"}
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }
