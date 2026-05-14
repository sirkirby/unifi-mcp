"""GET /v1/sites/{site_id}/{port-profiles,switch-ports,port-stats,switch-capabilities}.

Phase 5A PR1 Cluster 1 — switch-side read endpoints.

Wrapper-dict tools (``switch-ports``, ``port-stats``) return the inner array
of rows for the LIST contract — the manager produces ``{name, model, port_table: [...]}``
which the route unwraps before paginating. The Phase 4A serializer for these
tools is registered as DETAIL on the wrapper, so the route handler does the
row-level serialization inline (matching the wrapper serializer's row shape).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.switch import PortOverrideRow, PortProfile, PortStatRow
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter()


def _profile_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (0, raw.get("_id") or raw.get("id") or "")


def _port_idx_key(p) -> tuple:
    if isinstance(p, dict):
        return (p.get("port_idx") or 0, "")
    return (0, "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


# ---------------- port profiles ----------------


@router.get(
    "/sites/{site_id}/port-profiles",
    response_model=Page[to_pydantic_model(PortProfile)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/switch"],
)
async def list_port_profiles(
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
            "switch_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        all_profiles = await mgr.get_port_profiles()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(all_profiles),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_profile_key,
    )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_list_port_profiles")
    if tool_type is not None:
        type_class, kind = tool_type
        items = [type_class.from_manager_output(p).to_dict() for p in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_list_port_profiles")
        items = [serializer.serialize(p) for p in page]
        hint = registry.render_hint_for_tool("unifi_list_port_profiles")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/port-profiles/{profile_id}",
    response_model=Detail[to_pydantic_model(PortProfile)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/switch"],
)
async def get_port_profile_details(
    request: Request,
    site_id: str,
    profile_id: str,
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
                "switch_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "network")
            if cm.site != site_id:
                await cm.set_site(site_id)
            profile = await mgr.get_port_profile_by_id(profile_id)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if profile is None:
        raise HTTPException(status_code=404, detail="port profile not found")

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_port_profile_details")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(profile).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_port_profile_details")
        data = serializer.serialize(profile)
        hint = registry.render_hint_for_tool("unifi_get_port_profile_details")
    return {"data": data, "render_hint": hint}


# ---------------- switch ports (wrapper-dict → LIST) ----------------


def _normalize_port_override(p: dict) -> dict:
    return {
        "port_idx": p.get("port_idx"),
        "name": p.get("name"),
        "portconf_id": p.get("portconf_id"),
        "poe_mode": p.get("poe_mode"),
        "op_mode": p.get("op_mode"),
    }


@router.get(
    "/sites/{site_id}/switch-ports",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/switch"],
)
async def list_switch_ports(
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
        wrapper = await mgr.get_switch_ports(device_mac)
    if wrapper is None:
        raise HTTPException(status_code=404, detail=f"switch '{device_mac}' not found")

    items_raw = wrapper.get("port_overrides", []) if isinstance(wrapper, dict) else []
    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items_raw),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_port_idx_key,
    )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_switch_ports")
    if tool_type is not None:
        type_class, _kind = tool_type
        items = [PortOverrideRow.from_manager_output(p).to_dict() for p in page]
        hint = {**type_class.render_hint("list"), "kind": "list"}
    else:
        items = [_normalize_port_override(p) for p in page]
        registry = request.app.state.serializer_registry
        hint = registry.render_hint_for_tool("unifi_get_switch_ports")
        # Override kind to list since the route exposes the unwrapped rows.
        hint = {**hint, "kind": "list"}
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


# ---------------- port stats (wrapper-dict → LIST) ----------------


def _normalize_port_stat(p: dict) -> dict:
    return {
        "port_idx": p.get("port_idx"),
        "name": p.get("name"),
        "enable": bool(p.get("enable", True)),
        "speed": p.get("speed"),
        "duplex": p.get("full_duplex"),
        "tx_bytes": p.get("tx_bytes", 0),
        "rx_bytes": p.get("rx_bytes", 0),
        "tx_packets": p.get("tx_packets", 0),
        "rx_packets": p.get("rx_packets", 0),
        "tx_dropped": p.get("tx_dropped", 0),
        "rx_dropped": p.get("rx_dropped", 0),
        "poe_enable": bool(p.get("poe_enable", False)),
        "poe_mode": p.get("poe_mode"),
        "poe_power": p.get("poe_power"),
    }


@router.get(
    "/sites/{site_id}/port-stats",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/switch"],
)
async def list_port_stats(
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
        wrapper = await mgr.get_port_stats(device_mac)
    if wrapper is None:
        raise HTTPException(status_code=404, detail=f"switch '{device_mac}' not found")

    items_raw = wrapper.get("port_table", []) if isinstance(wrapper, dict) else []
    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items_raw),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_port_idx_key,
    )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_port_stats")
    if tool_type is not None:
        type_class, _kind = tool_type
        items = [PortStatRow.from_manager_output(p).to_dict() for p in page]
        hint = {**type_class.render_hint("list"), "kind": "list"}
    else:
        items = [_normalize_port_stat(p) for p in page]
        registry = request.app.state.serializer_registry
        hint = registry.render_hint_for_tool("unifi_get_port_stats")
        hint = {**hint, "kind": "list"}
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


# ---------------- switch capabilities (DETAIL) ----------------


@router.get(
    "/sites/{site_id}/switch-capabilities",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/switch"],
)
async def get_switch_capabilities(
    request: Request,
    site_id: str,
    device_mac: str = Query(..., description="MAC address of the switch"),
    controller=Depends(resolve_controller),
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
        caps = await mgr.get_switch_capabilities(device_mac)
    if caps is None:
        raise HTTPException(status_code=404, detail=f"switch '{device_mac}' not found")

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_switch_capabilities")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(caps).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_switch_capabilities")
        data = serializer.serialize(caps)
        hint = registry.render_hint_for_tool("unifi_get_switch_capabilities")
    return {"data": data, "render_hint": hint}
