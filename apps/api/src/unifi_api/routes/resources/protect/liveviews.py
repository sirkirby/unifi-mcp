"""GET /v1/sites/{site_id}/liveviews[/{liveview_id}] — protect liveviews.

LiveviewManager exposes ``list_liveviews`` only as a read surface; there
is no ``protect_get_liveview`` tool in the manifest. The DETAIL endpoint
filters from the LIST response (mirrors the lights/sensors pattern).
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
    "/sites/{site_id}/liveviews",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/liveviews"],
)
async def list_liveviews(
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
            "liveview_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "protect")
        await _maybe_set_site(cm, site_id)
        items = await mgr.list_liveviews()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_list_liveviews")
    if tool_type is not None:
        type_class, kind = tool_type
        rows = [type_class.from_manager_output(i).to_dict() for i in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_list_liveviews")
        rows = [serializer.serialize(i) for i in page]
        hint = registry.render_hint_for_tool("protect_list_liveviews")
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/liveviews/{liveview_id}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/liveviews"],
)
async def get_liveview(
    request: Request,
    site_id: str,
    liveview_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    """No native ``protect_get_liveview`` tool — filter from LIST."""
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "protect",
                "liveview_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "protect")
            await _maybe_set_site(cm, site_id)
            all_lvs = await mgr.list_liveviews()
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    found = None
    for lv in all_lvs:
        raw = lv if isinstance(lv, dict) else getattr(lv, "raw", {}) or {}
        if raw.get("id") == liveview_id:
            found = lv
            break
    if found is None:
        raise HTTPException(status_code=404, detail=f"liveview {liveview_id} not found")

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_list_liveviews")
    if tool_type is not None:
        type_class, _ = tool_type
        data = type_class.from_manager_output(found).to_dict()
        list_hint = type_class.render_hint("list")
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_list_liveviews")
        data = serializer.serialize(found)
        list_hint = registry.render_hint_for_tool("protect_list_liveviews")
    detail_hint = {**list_hint, "kind": "detail"}
    return {
        "data": data,
        "render_hint": detail_hint,
    }
