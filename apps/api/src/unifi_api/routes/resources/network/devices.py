"""GET /v1/sites/{site_id}/devices[/{mac}] — network devices (UniFi APs/switches/gateways)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.device import Device
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter()


def _device_key(obj) -> tuple:
    """Sort by (uptime, mac) descending — most-recently-up devices first."""
    raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
    return (raw.get("uptime") or 0, raw.get("mac") or "")


@router.get(
    "/sites/{site_id}/devices",
    response_model=Page[to_pydantic_model(Device)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/devices"],
)
async def list_devices(
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
            "device_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        all_devices = await mgr.get_devices()

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(all_devices),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_device_key,
    )

    type_class = request.app.state.type_registry.lookup("network", "devices")
    items = [type_class.from_manager_output(d).to_dict() for d in page]
    hint = type_class.render_hint("list")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/devices/{mac}",
    response_model=Detail[to_pydantic_model(Device)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/devices"],
)
async def get_device(
    request: Request,
    site_id: str,
    mac: str,
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
                "device_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "network")
            if cm.site != site_id:
                await cm.set_site(site_id)
            device = await mgr.get_device_details(mac)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    type_class = request.app.state.type_registry.lookup("network", "devices/{mac}")
    data = type_class.from_manager_output(device).to_dict()
    hint = type_class.render_hint("detail")
    return {"data": data, "render_hint": hint}


@router.get(
    "/sites/{site_id}/devices/{mac}/radio",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/devices"],
)
async def get_device_radio(
    request: Request,
    site_id: str,
    mac: str,
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
                "device_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "network")
            if cm.site != site_id:
                await cm.set_site(site_id)
            radio = await mgr.get_device_radio(mac)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if radio is None:
        raise HTTPException(
            status_code=404,
            detail=f"device radio config for {mac} not found",
        )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_device_radio")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(radio).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_device_radio")
        data = serializer.serialize(radio)
        hint = registry.render_hint_for_tool("unifi_get_device_radio")
    return {"data": data, "render_hint": hint}


@router.get(
    "/sites/{site_id}/devices/{mac}/outlets",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/devices"],
)
async def get_pdu_outlets(
    request: Request,
    site_id: str,
    mac: str,
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
                "device_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "network")
            if cm.site != site_id:
                await cm.set_site(site_id)
            outlets = await mgr.get_pdu_outlets(mac)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if outlets is None:
        raise HTTPException(
            status_code=404,
            detail=f"device {mac} is not a Smart Power PDU",
        )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_pdu_outlets")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(outlets).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_pdu_outlets")
        data = serializer.serialize(outlets)
        hint = registry.render_hint_for_tool("unifi_get_pdu_outlets")
    return {"data": data, "render_hint": hint}
