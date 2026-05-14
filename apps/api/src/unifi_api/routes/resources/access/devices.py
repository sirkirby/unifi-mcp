"""GET /v1/sites/{site_id}/access-devices[/{device_id}] — access devices.

Path uses ``/access-devices`` (product-prefixed) to disambiguate from the
network ``/devices`` endpoint at /v1/sites/{id}/devices. Same controller
can serve both products on the same site path; the prefix prevents
ambiguity.

DeviceManager.get_device raises UniFiNotFoundError on miss → 404.
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
from unifi_api.routes.resources.access.doors import _maybe_set_site
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


def _id_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (0, raw.get("id") or raw.get("_id") or "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get(
    "/sites/{site_id}/access-devices",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/devices"],
)
async def list_access_devices(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
) -> dict:
    require_capability(controller, "access")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "access",
            "device_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "access")
        await _maybe_set_site(cm, site_id)
        items = await mgr.list_devices()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_list_devices")
    if tool_type is not None:
        type_class, kind = tool_type
        items_out = [type_class.from_manager_output(d).to_dict() for d in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_list_devices")
        items_out = [serializer.serialize(d) for d in page]
        hint = registry.render_hint_for_tool("access_list_devices")
    return {
        "items": items_out,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/access-devices/{device_id}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/devices"],
)
async def get_access_device(
    request: Request,
    site_id: str,
    device_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "access")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "access",
                "device_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "access")
            await _maybe_set_site(cm, site_id)
            device = await mgr.get_device(device_id)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_get_device")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(device).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_get_device")
        data = serializer.serialize(device)
        hint = registry.render_hint_for_tool("access_get_device")
    return {
        "data": data,
        "render_hint": hint,
    }
