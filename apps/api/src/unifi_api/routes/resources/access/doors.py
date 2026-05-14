"""GET /v1/sites/{site_id}/doors[/{door_id}] — access doors.

Access is a single-controller, no-site product: the access connection
manager has no ``set_site`` method. We guard the call with ``getattr``
so the endpoint shape stays consistent with the network resources.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.access.doors import Door
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter()


def _door_key(obj) -> tuple:
    """Sort by (0, id) — id-stable order, no time component."""
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {})
    return (0, raw.get("id") or "")


async def _maybe_set_site(cm, site_id: str) -> None:
    """Call cm.set_site(site_id) only if the CM exposes it.

    Access's connection manager is single-controller-no-site and does not
    define set_site; network's does. Sharing the resource path means we
    accept ``site_id`` for URL symmetry but no-op on access.
    """
    set_site = getattr(cm, "set_site", None)
    if set_site is None:
        return
    if getattr(cm, "site", None) != site_id:
        await set_site(site_id)


@router.get(
    "/sites/{site_id}/doors",
    response_model=Page[to_pydantic_model(Door)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/doors"],
)
async def list_doors(
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
            "door_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "access")
        await _maybe_set_site(cm, site_id)
        all_doors = await mgr.list_doors()

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(all_doors),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_door_key,
    )

    type_class = request.app.state.type_registry.lookup("access", "doors")
    items = [type_class.from_manager_output(d).to_dict() for d in page]
    hint = type_class.render_hint("list")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/doors/{door_id}",
    response_model=Detail[to_pydantic_model(Door)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/doors"],
)
async def get_door(
    request: Request,
    site_id: str,
    door_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "access")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "access",
            "door_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "access")
        await _maybe_set_site(cm, site_id)
        try:
            door = await mgr.get_door(door_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="door not found")

    type_class = request.app.state.type_registry.lookup("access", "doors/{id}")
    data = type_class.from_manager_output(door).to_dict()
    hint = type_class.render_hint("detail")
    return {
        "data": data,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/doors/{door_id}/status",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/doors"],
)
async def get_door_status(
    request: Request,
    site_id: str,
    door_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    """Per-door status (nested under /doors/{door_id}/status).

    Mirrors the protect /cameras/{id}/analytics nested-detail pattern.
    DoorManager.get_door_status raises UniFiNotFoundError on miss → 404.
    """
    require_capability(controller, "access")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "access",
                "door_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "access")
            await _maybe_set_site(cm, site_id)
            status = await mgr.get_door_status(door_id)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if status is None:
        raise HTTPException(status_code=404, detail=f"door {door_id} not found")

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_get_door_status")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(status).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_get_door_status")
        data = serializer.serialize(status)
        hint = registry.render_hint_for_tool("access_get_door_status")
    return {
        "data": data,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/door-groups",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/doors"],
)
async def list_door_groups(
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
            "door_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "access")
        await _maybe_set_site(cm, site_id)
        all_groups = await mgr.list_door_groups()

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(all_groups),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_door_key,
    )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_list_door_groups")
    if tool_type is not None:
        type_class, kind = tool_type
        items = [type_class.from_manager_output(g).to_dict() for g in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_list_door_groups")
        items = [serializer.serialize(g) for g in page]
        hint = registry.render_hint_for_tool("access_list_door_groups")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }
