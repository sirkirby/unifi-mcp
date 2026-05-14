"""GET /v1/sites/{site_id}/events[/{id}] + thumbnails + smart-detections + recent-events.

Phase 3 landed the LIST endpoint. Phase 5A PR3 Cluster 2 extends with:

- ``GET /events/{event_id}``           → ``protect_get_event``
- ``GET /event-thumbnails/{event_id}`` → ``protect_get_event_thumbnail``
- ``GET /smart-detections``            → ``protect_list_smart_detections`` (EVENT_LOG)
- ``GET /recent-events``               → ``protect_recent_events`` (buffer snapshot)

The path ``/events/{id}`` does not collide with PR2's network/events.py
capability-aware dispatcher — that one only owns the bare ``/events`` path.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.protect.events import Event
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Page

router = APIRouter()


def _event_key(obj) -> tuple:
    """Sort by (start, id) descending — most recent first.

    EventManager.list_events already sorts desc server-side, but we
    re-sort here so paginate() can drive a stable cursor regardless of
    upstream ordering. The pagination helper sorts ascending, then the
    manifest's ``sort_default = "start:desc"`` reflects the intended
    user-facing direction.
    """
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {})
    return (raw.get("start") or 0, raw.get("id") or "")


async def _maybe_set_site(cm, site_id: str) -> None:
    set_site = getattr(cm, "set_site", None)
    if set_site is None:
        return
    if getattr(cm, "site", None) != site_id:
        await set_site(site_id)


@router.get(
    "/sites/{site_id}/events",
    response_model=Page[to_pydantic_model(Event)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/events"],
)
async def list_events(
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
            "event_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "protect")
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

    type_class = request.app.state.type_registry.lookup("protect", "events")
    items = [type_class.from_manager_output(e).to_dict() for e in page]
    hint = type_class.render_hint("event_log")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/events/{event_id}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/events"],
)
async def get_event(
    request: Request,
    site_id: str,
    event_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "protect",
                "event_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "protect")
            await _maybe_set_site(cm, site_id)
            event = await mgr.get_event(event_id)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_get_event")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(event).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_get_event")
        data = serializer.serialize(event)
        hint = registry.render_hint_for_tool("protect_get_event")
    return {
        "data": data,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/event-thumbnails/{event_id}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/events"],
)
async def get_event_thumbnail(
    request: Request,
    site_id: str,
    event_id: str,
    controller=Depends(resolve_controller),
    width: int | None = Query(None, ge=1, le=4096),
    height: int | None = Query(None, ge=1, le=4096),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "protect",
                "event_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "protect")
            await _maybe_set_site(cm, site_id)
            payload = await mgr.get_event_thumbnail(event_id, width=width, height=height)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_get_event_thumbnail")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_get_event_thumbnail")
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool("protect_get_event_thumbnail")
    return {
        "data": data,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/smart-detections",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/events"],
)
async def list_smart_detections(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    camera_id: str | None = Query(None),
    detection_type: str | None = Query(None),
    min_confidence: int | None = Query(None, ge=0, le=100),
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
            "event_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "protect")
        await _maybe_set_site(cm, site_id)
        all_events = await mgr.list_smart_detections(
            camera_id=camera_id,
            detection_type=detection_type,
            min_confidence=min_confidence,
            limit=max(limit, 100),
        )

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
    tool_type = type_registry.lookup_tool("protect_list_smart_detections")
    if tool_type is not None:
        type_class, kind = tool_type
        items = [type_class.from_manager_output(e).to_dict() for e in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_list_smart_detections")
        items = [serializer.serialize(e) for e in page]
        hint = registry.render_hint_for_tool("protect_list_smart_detections")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/recent-events",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/events"],
)
async def recent_events(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    event_type: str | None = Query(None),
    camera_id: str | None = Query(None),
    min_confidence: int | None = Query(None, ge=0, le=100),
    limit: int | None = Query(None, ge=1, le=500),
) -> dict:
    """Return a snapshot of the websocket ring buffer.

    Differs from the SSE stream at ``/v1/streams/protect/events``: this is
    a buffer-snapshot REST surface, not a tailing stream. ``DETAIL`` render
    kind — the manager's wrapper dict (events / count / source / buffer_size)
    is itself the payload.
    """
    require_capability(controller, "protect")
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
        await _maybe_set_site(cm, site_id)
        # get_recent_from_buffer is synchronous (in-memory ring buffer read)
        events = mgr.get_recent_from_buffer(
            event_type=event_type,
            camera_id=camera_id,
            min_confidence=min_confidence,
            limit=limit,
        )

    buffer_size = getattr(mgr, "buffer_size", len(events) if isinstance(events, list) else 0)
    payload = {
        "events": list(events) if events is not None else [],
        "count": len(events) if events is not None else 0,
        "source": "buffer",
        "buffer_size": buffer_size,
    }

    registry = request.app.state.serializer_registry
    serializer = registry.serializer_for_tool("protect_recent_events")
    return {
        "data": serializer.serialize(payload),
        "render_hint": registry.render_hint_for_tool("protect_recent_events"),
    }
