"""GET /v1/sites/{site_id}/blocked-clients — clients currently blocked from network.

Phase 5A PR1 Cluster 2 — clients & user groups.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.client import BlockedClient
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Page

router = APIRouter()


def _blocked_key(obj) -> tuple:
    raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
    return (raw.get("last_seen") or 0, raw.get("mac") or "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get(
    "/sites/{site_id}/blocked-clients",
    response_model=Page[to_pydantic_model(BlockedClient)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/clients"],
)
async def list_blocked_clients(
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
            "client_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        if cm.site != site_id:
            await cm.set_site(site_id)
        all_blocked = await mgr.get_blocked_clients()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(all_blocked),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_blocked_key,
    )

    type_class = request.app.state.type_registry.lookup("network", "blocked_clients")
    items = [type_class.from_manager_output(c).to_dict() for c in page]
    hint = type_class.render_hint("list")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }
