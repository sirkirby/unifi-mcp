"""Access events + activity-summary read endpoints.

Four endpoint families collected here:

- ``GET /access/events``               → ``access_list_events`` (EVENT_LOG)
- ``GET /access/events/{event_id}``    → ``access_get_event`` (DETAIL)
- ``GET /access/recent-events``        → ``access_recent_events`` (buffer
  snapshot — wraps the manager's in-memory ring buffer in the same shape
  as protect's ``/recent-events``)
- ``GET /access/activity-summary``     → ``access_get_activity_summary``
  (DETAIL — passes the histogram payload through ``ActivitySummarySerializer``)

The ``/access/...`` prefix is in the URL path, not a router prefix — so each
@router.get registers the full path. This disambiguates from network's
capability-aware ``/events`` dispatcher (PR2) and protect's ``/events``
(PR3 Cluster 2).
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
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


def _event_key(obj) -> tuple:
    """Sort by (timestamp, id) — newest first via the manifest's
    ``sort_default = "timestamp:desc"``. paginate() sorts ascending; the
    user-facing direction is captured in the serializer metadata.
    """
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (raw.get("timestamp") or raw.get("time") or 0, raw.get("id") or "")


async def _maybe_set_site(cm, site_id: str) -> None:
    """Access is single-controller-no-site; set_site is a no-op when absent."""
    set_site = getattr(cm, "set_site", None)
    if set_site is None:
        return
    if getattr(cm, "site", None) != site_id:
        await set_site(site_id)


@router.get(
    "/sites/{site_id}/access/events",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/events"],
)
async def list_access_events(
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
            "event_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "access")
        await _maybe_set_site(cm, site_id)
        all_events = await mgr.list_events(limit=max(limit, 100))

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(all_events),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_event_key,
    )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_list_events")
    if tool_type is not None:
        type_class, kind = tool_type
        items = [type_class.from_manager_output(e).to_dict() for e in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_list_events")
        items = [serializer.serialize(e) for e in page]
        hint = registry.render_hint_for_tool("access_list_events")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/access/events/{event_id}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/events"],
)
async def get_access_event(
    request: Request,
    site_id: str,
    event_id: str,
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
                "event_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "access")
            await _maybe_set_site(cm, site_id)
            event = await mgr.get_event(event_id)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_get_event")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(event).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_get_event")
        data = serializer.serialize(event)
        hint = registry.render_hint_for_tool("access_get_event")
    return {
        "data": data,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/access/recent-events",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/events"],
)
async def recent_access_events(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    event_type: str | None = Query(None),
    door_id: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=500),
) -> dict:
    """Return a snapshot of the websocket ring buffer.

    Differs from the SSE stream at ``/v1/streams/access/events``: this is
    a buffer-snapshot REST surface, not a tailing stream. Mirrors PR3's
    protect ``/recent-events`` shape: ``{events, count, source, buffer_size}``.
    ``EventManager.get_recent_from_buffer`` is synchronous (in-memory ring
    buffer read).
    """
    require_capability(controller, "access")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "access",
            "event_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "access")
        await _maybe_set_site(cm, site_id)
        # synchronous (in-memory ring buffer read)
        events = mgr.get_recent_from_buffer(
            event_type=event_type,
            door_id=door_id,
            limit=limit,
        )

    buffer_size = getattr(mgr, "buffer_size", len(events) if isinstance(events, list) else 0)
    payload = {
        "events": list(events) if events is not None else [],
        "count": len(events) if events is not None else 0,
        "source": "buffer",
        "buffer_size": buffer_size,
    }

    # access_recent_events is registered as EVENT_LOG but the route surface
    # is a wrapper dict (matches protect's recent-events convention).
    # Return DETAIL kind in the render_hint so consumers render the wrapper
    # rather than treating it as a list.
    registry = request.app.state.serializer_registry
    list_hint = registry.render_hint_for_tool("access_recent_events")
    detail_hint = {**list_hint, "kind": "detail"}
    return {
        "data": payload,
        "render_hint": detail_hint,
    }


@router.get(
    "/sites/{site_id}/access/activity-summary",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/events"],
)
async def get_access_activity_summary(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    door_id: str | None = Query(None),
    days: int = Query(7, ge=1, le=90),
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
                "event_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "access")
            await _maybe_set_site(cm, site_id)
            payload = await mgr.get_activity_summary(door_id=door_id, days=days)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_get_activity_summary")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_get_activity_summary")
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool("access_get_activity_summary")
    return {
        "data": data,
        "render_hint": hint,
    }
