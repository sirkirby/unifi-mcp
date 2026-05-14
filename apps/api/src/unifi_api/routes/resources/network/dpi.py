"""GET /v1/sites/{site_id}/dpi-{applications,categories} — DPI lookups.

Phase 5A PR2 Cluster 4 — network filtering routes.

``DpiManager`` calls the official integration API and returns paginated
wrapper dicts: ``{"data": [...], "totalCount": int, "offset": int, "limit": int}``.
The route unwraps ``wrapper["data"]`` before paginating + serializing.

DPI category id ``0`` is real and falsy — pagination/sort handles it via
the ``or "" `` fallback only on missing keys, not on present-but-falsy values.
"""

from __future__ import annotations

from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.dpi import DpiApplication, DpiCategory
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Page

router = APIRouter()


def _require_dpi_auth(cm: Any, controller_id: str) -> None:
    """Raise 501 with a clear hint when the controller has no API token.

    DPI lookups go through UniFi's integration API which requires a
    bearer API key separate from the session-based auth used for
    everything else. The api_token field on the controller record carries
    it; when unset, the manager's `_request_integration_api` returns None
    and the manager normalizes that to an empty wrapper — which would
    silently look like 'no DPI apps found' rather than a configuration
    issue. Surface the actual cause instead.
    """
    auth = getattr(cm, "unifi_auth", None)
    if auth is None or not auth.has_api_key:
        raise HTTPException(
            status_code=501,
            detail={
                "kind": "api_key_required",
                "missing": "controller_api_token",
                "controller": controller_id,
                "hint": (
                    "The DPI integration endpoint requires a UniFi API "
                    "token. Add one via Settings → Control Plane → "
                    "Integrations on the controller, then update this "
                    "controller via PATCH /v1/controllers/{id} (or the "
                    "Controllers tab in the admin UI) with the token."
                ),
            },
        )


def _id_key(obj) -> tuple:
    """Sort by id; treats `None` (missing) as `0` so present 0s order naturally."""
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    ident = raw.get("id")
    if ident is None:
        ident = raw.get("_id")
    if ident is None:
        ident = 0
    return (0, ident)


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


def _unwrap(result: Any) -> list:
    """Extract bare list from a paginated DPI wrapper or pass through."""
    if isinstance(result, dict) and "data" in result:
        data = result.get("data") or []
        return list(data) if isinstance(data, Iterable) else []
    if isinstance(result, list):
        return result
    return []


@router.get(
    "/sites/{site_id}/dpi-applications",
    response_model=Page[to_pydantic_model(DpiApplication)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/policy"],
)
async def list_dpi_applications(
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
            "dpi_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        _require_dpi_auth(cm, controller.id)
        if cm.site != site_id:
            await cm.set_site(site_id)
        # Manager returns the integration-API wrapper. Ask for a wide page so
        # cursor-based pagination on the client side has the full set.
        result = await mgr.get_dpi_applications(limit=2500, offset=0)

    items_raw = _unwrap(result)
    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        items_raw,
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_list_dpi_applications")
    if tool_type is not None:
        type_class, kind = tool_type
        rows = [type_class.from_manager_output(i).to_dict() for i in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_list_dpi_applications")
        rows = [serializer.serialize(i) for i in page]
        hint = registry.render_hint_for_tool("unifi_list_dpi_applications")
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/dpi-categories",
    response_model=Page[to_pydantic_model(DpiCategory)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/policy"],
)
async def list_dpi_categories(
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
            "dpi_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "network")
        _require_dpi_auth(cm, controller.id)
        if cm.site != site_id:
            await cm.set_site(site_id)
        result = await mgr.get_dpi_categories(limit=500, offset=0)

    items_raw = _unwrap(result)
    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        items_raw,
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_list_dpi_categories")
    if tool_type is not None:
        type_class, kind = tool_type
        rows = [type_class.from_manager_output(i).to_dict() for i in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_list_dpi_categories")
        rows = [serializer.serialize(i) for i in page]
        hint = registry.render_hint_for_tool("unifi_list_dpi_categories")
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }
