"""GET /v1/sites/{site_id}/content-filters[/{filter_id}] — content filters.

Phase 5A PR2 Cluster 4 — network filtering routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.content_filter import ContentFilter
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter()


def _id_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (0, raw.get("_id") or raw.get("id") or "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get(
    "/sites/{site_id}/content-filters",
    response_model=Page[to_pydantic_model(ContentFilter)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/policy"],
)
async def list_content_filters(
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
            "content_filter_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        items = await mgr.get_content_filters()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_list_content_filters")
    if tool_type is not None:
        type_class, kind = tool_type
        rows = [type_class.from_manager_output(i).to_dict() for i in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_list_content_filters")
        rows = [serializer.serialize(i) for i in page]
        hint = registry.render_hint_for_tool("unifi_list_content_filters")
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/content-filters/{filter_id}",
    response_model=Detail[to_pydantic_model(ContentFilter)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/policy"],
)
async def get_content_filter_details(
    request: Request,
    site_id: str,
    filter_id: str,
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
                "content_filter_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "network")
            if cm.site != site_id:
                await cm.set_site(site_id)
            item = await mgr.get_content_filter_by_id(filter_id)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"content filter {filter_id} not found",
        )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_content_filter_details")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(item).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_content_filter_details")
        data = serializer.serialize(item)
        hint = registry.render_hint_for_tool("unifi_get_content_filter_details")
    return {"data": data, "render_hint": hint}
