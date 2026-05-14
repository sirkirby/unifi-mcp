"""GET /v1/sites/{site_id}/wlans[/{wlan_id}] — WLAN/SSID definitions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.wlan import Wlan
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter()


def _wlan_key(obj) -> tuple:
    """Sort by (0, id) — id-stable order, no time component."""
    raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
    return (0, raw.get("_id") or raw.get("id") or "")


@router.get(
    "/sites/{site_id}/wlans",
    response_model=Page[to_pydantic_model(Wlan)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/wlans"],
)
async def list_wlans(
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
        # WLANs live on network_manager (see managers.py builder map).
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "network",
            "network_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        all_wlans = await mgr.get_wlans()

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(all_wlans),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_wlan_key,
    )

    type_class = request.app.state.type_registry.lookup("network", "wlans")
    items = [type_class.from_manager_output(w).to_dict() for w in page]
    hint = type_class.render_hint("list")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/wlans/{wlan_id}",
    response_model=Detail[to_pydantic_model(Wlan)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/wlans"],
)
async def get_wlan(
    request: Request,
    site_id: str,
    wlan_id: str,
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
                "network_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "network")
            if cm.site != site_id:
                await cm.set_site(site_id)
            wlan = await mgr.get_wlan_details(wlan_id)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if wlan is None:
        raise HTTPException(status_code=404, detail="wlan not found")

    type_class = request.app.state.type_registry.lookup("network", "wlans/{id}")
    data = type_class.from_manager_output(wlan).to_dict()
    hint = type_class.render_hint("detail")
    return {
        "data": data,
        "render_hint": hint,
    }
