"""GET /v1/sites/{site_id}/{events,alerts,anomalies,ips-events} — network EVENT_LOG.

Phase 5A PR2 Cluster 6. Each endpoint paginates per-event using time/_id keys.

The ``/events`` path coexists with the protect events route at the same path —
the network event-manager handles network controllers; protect event-manager
handles protect. The capability check (``require_capability``) ensures the
correct module serves each request based on the controller's product_kinds.
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


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


def _event_key(obj) -> tuple:
    """Sort by (time, id) descending; tolerate dict or model objects."""
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    ts = raw.get("time") or raw.get("timestamp") or 0
    eid = raw.get("_id") or raw.get("id") or ""
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
        key_fn=_event_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool(tool_name)
    if tool_type is not None:
        type_class, kind = tool_type
        rows = [type_class.from_manager_output(e).to_dict() for e in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool(tool_name)
        rows = [serializer.serialize(e) for e in page]
        hint = registry.render_hint_for_tool(tool_name)
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


def _controller_products(controller) -> list[str]:
    return [p for p in controller.product_kinds.split(",") if p]


@router.get(
    "/sites/{site_id}/events",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/observability"],
)
async def list_events_dispatch(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
) -> dict:
    """Dispatch to network or protect events based on the controller's products.

    The /events path is shared between network and protect controllers. We
    select the manager + serializer based on the controller's product_kinds
    so a single FastAPI route handles both cases without path collision.
    Network is preferred when the controller supports both (which is rare —
    multi-product controllers are typically network + access).
    """
    products = _controller_products(controller)
    if "network" in products:
        return await _list_network_events(
            request,
            site_id,
            controller,
            limit=limit,
            cursor=cursor,
        )
    if "protect" in products:
        return await _list_protect_events(
            request,
            site_id,
            controller,
            limit=limit,
            cursor=cursor,
        )
    # Neither — surface a clean capability mismatch (network is the canonical
    # owner of the path; the message reflects that).
    require_capability(controller, "network")
    return {}  # unreachable


async def _list_network_events(
    request: Request,
    site_id: str,
    controller,
    *,
    limit: int,
    cursor: str | None,
) -> dict:
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
        events = await mgr.get_events(limit=max(limit, 100))
    return _list_response(
        request,
        events,
        "unifi_list_events",
        limit=limit,
        cursor=cursor,
    )


async def _list_protect_events(
    request: Request,
    site_id: str,
    controller,
    *,
    limit: int,
    cursor: str | None,
) -> dict:
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "protect",
            "event_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "protect")
        set_site = getattr(cm, "set_site", None)
        if set_site is not None and getattr(cm, "site", None) != site_id:
            await set_site(site_id)
        events = await mgr.list_events(limit=max(limit, 100))

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(events),
        limit=limit,
        cursor=cursor_obj,
        key_fn=lambda e: (
            (e.get("start") if isinstance(e, dict) else getattr(e, "raw", {}).get("start")) or 0,
            (e.get("id") if isinstance(e, dict) else getattr(e, "raw", {}).get("id")) or "",
        ),
    )
    type_class = request.app.state.type_registry.lookup("protect", "events")
    items = [type_class.from_manager_output(e).to_dict() for e in page]
    hint = type_class.render_hint("event_log")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/alerts",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/observability"],
)
async def get_alerts(
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
        events = await mgr.get_alerts()
    return _list_response(
        request,
        events,
        "unifi_get_alerts",
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/sites/{site_id}/anomalies",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/observability"],
)
async def get_anomalies(
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
        events = await mgr.get_anomalies()
    return _list_response(
        request,
        events,
        "unifi_get_anomalies",
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/sites/{site_id}/ips-events",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/observability"],
)
async def get_ips_events(
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
        events = await mgr.get_ips_events()
    return _list_response(
        request,
        events,
        "unifi_get_ips_events",
        limit=limit,
        cursor=cursor,
    )
