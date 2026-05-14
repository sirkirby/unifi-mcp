"""Access health + system-info read endpoints (product-prefixed paths).

Two endpoint families:

- ``GET /access/health``        → ``access_get_health`` (DETAIL)
- ``GET /access/system-info``   → ``access_get_system_info`` (DETAIL)

The ``/access/...`` prefix is in the URL path — not a router prefix — to
disambiguate from network's ``/network/...`` and protect's ``/protect/...``
equivalents (PR3 Cluster 2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.routes.resources.access.events import _maybe_set_site

router = APIRouter()


@router.get(
    "/sites/{site_id}/access/health",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/system"],
)
async def get_access_health(
    request: Request,
    site_id: str,
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
                "system_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "access")
            await _maybe_set_site(cm, site_id)
            payload = await mgr.get_health()
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_get_health")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_get_health")
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool("access_get_health")
    return {
        "data": data,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/access/system-info",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/system"],
)
async def get_access_system_info(
    request: Request,
    site_id: str,
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
                "system_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "access")
            await _maybe_set_site(cm, site_id)
            payload = await mgr.get_system_info()
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("access_get_system_info")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("access_get_system_info")
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool("access_get_system_info")
    return {
        "data": data,
        "render_hint": hint,
    }
