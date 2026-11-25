"""GET /v1/sites/{site_id}/traffic-matching-lists[/{list_id}] — Integration API traffic matching lists."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.traffic_matching_lists import TrafficMatchingList
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter()


def _redact_sensitive(request: Request) -> bool:
    return request.app.state.config.policy.response.redact_sensitive_fields


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
    "/sites/{site_id}/traffic-matching-lists",
    response_model=Page[to_pydantic_model(TrafficMatchingList)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/traffic_matching_lists"],
    description=(
        "Integration API traffic matching lists. These IDs are scoped to the "
        "traffic-matching-list tool family — do not pass them to firewall group, "
        "firewall policy or MAC ACL tools."
    ),
)
async def list_traffic_matching_lists(
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
            "traffic_matching_list_manager",
            site=site_id,
        )
        items = await mgr.list_all_traffic_matching_lists()

    cursor_obj = _decode_cursor(cursor)
    page_items, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_list_traffic_matching_lists")
    if tool_type is not None:
        type_class, kind = tool_type
        redact_sensitive = _redact_sensitive(request)
        rows = [type_class.from_manager_output(i, redact_sensitive=redact_sensitive).to_dict() for i in page_items]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_list_traffic_matching_lists")
        rows = [serializer.serialize(i) for i in page_items]
        hint = registry.render_hint_for_tool("unifi_list_traffic_matching_lists")
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/traffic-matching-lists/{list_id}",
    response_model=Detail[to_pydantic_model(TrafficMatchingList)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/traffic_matching_lists"],
    description=(
        "One Integration API traffic matching list by its UUID. These IDs are "
        "scoped to the traffic-matching-list tool family — do not pass V1 firewall "
        "group IDs, V2 firewall policy IDs or MAC ACL rule IDs here."
    ),
)
async def get_traffic_matching_list(
    request: Request,
    site_id: str,
    list_id: str,
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
            "traffic_matching_list_manager",
            site=site_id,
        )
        item = await mgr.get_traffic_matching_list(list_id)
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_traffic_matching_list")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(item, redact_sensitive=_redact_sensitive(request)).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_traffic_matching_list")
        data = serializer.serialize(item)
        hint = registry.render_hint_for_tool("unifi_get_traffic_matching_list")
    return {"data": data, "render_hint": hint}
