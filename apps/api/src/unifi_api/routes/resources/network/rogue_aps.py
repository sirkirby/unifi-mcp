"""GET /v1/sites/{site_id}/{rogue-aps,rf-scan-results}.

RF environment LIST endpoints. ``rogue-aps`` enumerates every detected
neighbouring AP; the project does not maintain a separate "known/
acknowledged" classification because the controller does not expose a
backing API for one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.device import RfScanResult
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Page

router = APIRouter()


def _bssid_key(row) -> tuple:
    if isinstance(row, dict):
        return (row.get("last_seen") or 0, row.get("bssid") or "")
    return (0, "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


def _serialize_rogue(row, *, is_known: bool) -> dict:
    """Mirror RogueApSerializer._row — kept inline because the serializer's
    tool-name-aware path is `serialize_action`, not `serialize`."""
    if not isinstance(row, dict):
        return {}
    return {
        "bssid": row.get("bssid"),
        "ssid": row.get("essid") or row.get("ssid"),
        "channel": row.get("channel"),
        "signal_dbm": row.get("rssi") or row.get("signal"),
        "last_seen": row.get("last_seen"),
        "is_known": is_known,
    }


@router.get(
    "/sites/{site_id}/rogue-aps",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/wireless"],
)
async def list_rogue_aps(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    within_hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
) -> dict:
    require_capability(controller, "network")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session, controller.id, "network", "device_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        rows = await mgr.list_rogue_aps(within_hours)

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(rows), limit=limit, cursor=cursor_obj, key_fn=_bssid_key,
    )

    items = [_serialize_rogue(r, is_known=False) for r in page]
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_list_rogue_aps")
    if tool_type is not None:
        type_class, kind = tool_type
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        hint = registry.render_hint_for_tool("unifi_list_rogue_aps")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/rf-scan-results",
    response_model=Page[to_pydantic_model(RfScanResult)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/wireless"],
)
async def list_rf_scan_results(
    request: Request,
    site_id: str,
    ap_mac: str = Query(..., description="MAC address of the access point"),
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
) -> dict:
    require_capability(controller, "network")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session, controller.id, "network", "device_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        rows = await mgr.get_rf_scan_results(ap_mac)

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(rows or []), limit=limit, cursor=cursor_obj, key_fn=_bssid_key,
    )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_rf_scan_results")
    if tool_type is not None:
        type_class, kind = tool_type
        items = [type_class.from_manager_output(r).to_dict() for r in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_rf_scan_results")
        items = [serializer.serialize(r) for r in page]
        hint = registry.render_hint_for_tool("unifi_get_rf_scan_results")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }
