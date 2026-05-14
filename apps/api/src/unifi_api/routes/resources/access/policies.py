"""GET /v1/sites/{site_id}/policies[/{policy_id}] — access policies.

Access is a single-controller, no-site product. ``site_id`` is accepted for
URL symmetry but no-ops on access. PolicyManager.get_policy may raise
UniFiNotFoundError post-#175 when proxy returns a miss.
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
from unifi_api.routes.resources.access.doors import _maybe_set_site
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


def _id_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (0, raw.get("id") or raw.get("_id") or "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get(
    "/sites/{site_id}/policies",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/policies"],
)
async def list_policies(
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
        items = await mgr.list_policies()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_list_policies")
    if tool_type is not None:
        type_class, kind = tool_type
        items = [type_class.from_manager_output(p).to_dict() for p in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_list_policies")
        items = [serializer.serialize(p) for p in page]
        hint = registry.render_hint_for_tool("access_list_policies")
    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/policies/{policy_id}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/policies"],
)
async def get_policy(
    request: Request,
    site_id: str,
    policy_id: str,
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
                "policy_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "access")
            await _maybe_set_site(cm, site_id)
            policy = await mgr.get_policy(policy_id)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not policy:
        raise HTTPException(status_code=404, detail=f"policy {policy_id} not found")

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_get_policy")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(policy).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_get_policy")
        data = serializer.serialize(policy)
        hint = registry.render_hint_for_tool("access_get_policy")
    return {
        "data": data,
        "render_hint": hint,
    }
