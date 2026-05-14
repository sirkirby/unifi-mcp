"""GET /v1/sites/{site_id}/{alarms,backups,event-types,...} — network system endpoints.

Phase 5A PR2 Cluster 6. Per-tool kind dispatched via the serializer registry:

- LIST: alarms, backups, top-clients, client-sessions, network-health,
  speedtest-results
- DETAIL: event-types, autobackup-settings, site-settings, system-info,
  client-wifi-details (per-resource with `mac` path param)
"""

from __future__ import annotations

import inspect

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


def _id_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    ts = raw.get("time") or raw.get("timestamp") or raw.get("assoc_time") or 0
    eid = raw.get("_id") or raw.get("id") or raw.get("mac") or raw.get("subsystem") or ""
    return (ts, eid)


async def _maybe_set_site(cm, site_id: str) -> None:
    if getattr(cm, "site", None) != site_id:
        await cm.set_site(site_id)


def _list_response(request, items, tool_name, *, limit, cursor):
    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool(tool_name)
    if tool_type is not None:
        type_class, kind = tool_type
        rows = [type_class.from_manager_output(i).to_dict() for i in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool(tool_name)
        rows = [serializer.serialize(i) for i in page]
        hint = registry.render_hint_for_tool(tool_name)
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


def _detail_response(request, payload, tool_name):
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool(tool_name)
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool(tool_name)
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool(tool_name)
    return {"data": data, "render_hint": hint}


# ---------- LIST ----------


@router.get(
    "/sites/{site_id}/alarms",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/system"],
)
async def list_alarms(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=500),
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
            "event_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        items = await mgr.get_alarms()
    return _list_response(
        request,
        items,
        "unifi_list_alarms",
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/sites/{site_id}/backups",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/system"],
)
async def list_backups(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=500),
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
            "system_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        items = await mgr.list_backups()
    return _list_response(
        request,
        items,
        "unifi_list_backups",
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/sites/{site_id}/top-clients",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/system"],
)
async def get_top_clients(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=500),
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
            "stats_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        items = await mgr.get_top_clients()
    return _list_response(
        request,
        items,
        "unifi_get_top_clients",
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/sites/{site_id}/client-sessions",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/clients"],
)
async def get_client_sessions(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=500),
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
            "stats_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        items = await mgr.get_client_sessions()
    return _list_response(
        request,
        items,
        "unifi_get_client_sessions",
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/sites/{site_id}/network-health",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/system"],
)
async def get_network_health(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
) -> dict:
    """LIST kind per Phase 4A — manager returns multi-element list of subsystems."""
    require_capability(controller, "network")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "network",
            "system_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        items = await mgr.get_network_health()
    return _list_response(
        request,
        items,
        "unifi_get_network_health",
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/sites/{site_id}/speedtest-results",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/observability"],
)
async def get_speedtest_results(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=500),
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
            "stats_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        items = await mgr.get_speedtest_results()
    return _list_response(
        request,
        items,
        "unifi_get_speedtest_results",
        limit=limit,
        cursor=cursor,
    )


# ---------- DETAIL ----------


@router.get(
    "/sites/{site_id}/event-types",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/system"],
)
async def get_event_types(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    """DETAIL — event_manager.get_event_type_prefixes (sync method, returns list)."""
    require_capability(controller, "network")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "network",
            "event_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        result = mgr.get_event_type_prefixes()
        if inspect.isawaitable(result):
            result = await result
    return _detail_response(request, result, "unifi_get_event_types")


@router.get(
    "/sites/{site_id}/autobackup-settings",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/system"],
)
async def get_autobackup_settings(
    request: Request,
    site_id: str,
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
            "system_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        payload = await mgr.get_autobackup_settings()
    return _detail_response(request, payload, "unifi_get_autobackup_settings")


@router.get(
    "/sites/{site_id}/site-settings",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/system"],
)
async def get_site_settings(
    request: Request,
    site_id: str,
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
            "system_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        payload = await mgr.get_site_settings()
    return _detail_response(request, payload, "unifi_get_site_settings")


@router.get(
    "/sites/{site_id}/system-info",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/system"],
)
async def get_system_info(
    request: Request,
    site_id: str,
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
            "system_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        payload = await mgr.get_system_info()
    return _detail_response(request, payload, "unifi_get_system_info")


@router.get(
    "/sites/{site_id}/client-wifi-details/{mac}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/clients"],
)
async def get_client_wifi_details(
    request: Request,
    site_id: str,
    mac: str,
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
            "stats_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        await _maybe_set_site(cm, site_id)
        payload = await mgr.get_client_wifi_details(mac)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"client {mac} wifi details not found",
        )
    return _detail_response(request, payload, "unifi_get_client_wifi_details")
