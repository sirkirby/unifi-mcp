"""GET /v1/sites/{site_id}/available-channels — regulatory-domain channel list."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.device import AvailableChannel
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Page

router = APIRouter()


def _channel_key(row) -> tuple:
    if isinstance(row, dict):
        return (row.get("channel") or 0, "")
    return (0, "")


@router.get(
    "/sites/{site_id}/available-channels",
    response_model=Page[to_pydantic_model(AvailableChannel)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/wireless"],
)
async def list_available_channels(
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
        rows = await mgr.list_available_channels()

    cursor_obj: Cursor | None = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(rows or []),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_channel_key,
    )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_list_available_channels")
    if tool_type is not None:
        type_class, kind = tool_type
        items = [type_class.from_manager_output(r).to_dict() for r in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_list_available_channels")
        items = [serializer.serialize(r) for r in page]
        hint = registry.render_hint_for_tool("unifi_list_available_channels")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }
