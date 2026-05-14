"""GET /v1/sites/{site_id}/lights[/{light_id}] — protect lights.

The protect ``LightManager`` exposes only ``list_lights``; there is no
dedicated ``get_light`` summary helper, and the manifest does not register
a ``protect_get_light`` tool. The DETAIL endpoint therefore filters from
the LIST response (mirrors the network firewall_rules pattern).

Protect is a single-controller, no-site product: the protect connection
manager has no ``set_site`` method, so we guard the call via ``getattr``
through the shared ``_maybe_set_site`` helper.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.routes.resources.protect.cameras import _maybe_set_site
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


def _id_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (0, raw.get("id") or "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get(
    "/sites/{site_id}/lights",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/lights"],
)
async def list_lights(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "protect",
            "light_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "protect")
        await _maybe_set_site(cm, site_id)
        items = await mgr.list_lights()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_list_lights")
    if tool_type is not None:
        type_class, kind = tool_type
        rows = [type_class.from_manager_output(i).to_dict() for i in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_list_lights")
        rows = [serializer.serialize(i) for i in page]
        hint = registry.render_hint_for_tool("protect_list_lights")
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/lights/{light_id}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/lights"],
)
async def get_light_details(
    request: Request,
    site_id: str,
    light_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    """No native ``protect_get_light`` tool exists — filter from LIST.

    LightManager._get_light raises UniFiNotFoundError, but list_lights
    does not invoke that helper. We wrap the manager call defensively
    so any future refactor that surfaces UniFiNotFoundError keeps mapping
    cleanly to a 404.
    """
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "protect",
                "light_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "protect")
            await _maybe_set_site(cm, site_id)
            all_lights = await mgr.list_lights()
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    found = None
    for light in all_lights:
        raw = light if isinstance(light, dict) else getattr(light, "raw", {}) or {}
        if raw.get("id") == light_id:
            found = light
            break
    if found is None:
        raise HTTPException(status_code=404, detail=f"light {light_id} not found")

    # No protect_get_light tool exists; reuse the LIST projection + emit a
    # detail render hint so consumers can render a single-row detail card.
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_list_lights")
    if tool_type is not None:
        type_class, _ = tool_type
        data = type_class.from_manager_output(found).to_dict()
        list_hint = type_class.render_hint("list")
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_list_lights")
        data = serializer.serialize(found)
        list_hint = registry.render_hint_for_tool("protect_list_lights")
    detail_hint = {**list_hint, "kind": "detail"}
    return {
        "data": data,
        "render_hint": detail_hint,
    }
