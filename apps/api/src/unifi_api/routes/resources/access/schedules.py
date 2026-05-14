"""GET /v1/sites/{site_id}/schedules — access schedules (LIST only).

PolicyManager owns ``list_schedules`` (no separate schedule manager). Access
is single-controller-no-site; ``site_id`` is accepted for URL symmetry.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

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


@router.get(
    "/sites/{site_id}/schedules",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/schedules"],
)
async def list_schedules(
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
            "policy_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "access")
        await _maybe_set_site(cm, site_id)
        items = await mgr.list_schedules()

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_list_schedules")
    if tool_type is not None:
        type_class, kind = tool_type
        items = [type_class.from_manager_output(s).to_dict() for s in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_list_schedules")
        items = [serializer.serialize(s) for s in page]
        hint = registry.render_hint_for_tool("access_list_schedules")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }
