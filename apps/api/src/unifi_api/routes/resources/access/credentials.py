"""GET /v1/sites/{site_id}/credentials[/{credential_id}] — access credentials.

Access is a single-controller, no-site product: the access connection
manager has no ``set_site`` method. ``site_id`` is accepted for URL
symmetry but no-ops on access.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.access.credentials import Credential
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter()


def _credential_key(obj) -> tuple:
    """Sort by (0, id) — id-stable order, no time component."""
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {})
    return (0, raw.get("id") or "")


async def _maybe_set_site(cm, site_id: str) -> None:
    set_site = getattr(cm, "set_site", None)
    if set_site is None:
        return
    if getattr(cm, "site", None) != site_id:
        await set_site(site_id)


@router.get(
    "/sites/{site_id}/credentials",
    response_model=Page[to_pydantic_model(Credential)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/credentials"],
)
async def list_credentials(
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
            "credential_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "access")
        await _maybe_set_site(cm, site_id)
        all_credentials = await mgr.list_credentials()

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(all_credentials),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_credential_key,
    )

    type_class = request.app.state.type_registry.lookup("access", "credentials")
    items = [type_class.from_manager_output(c).to_dict() for c in page]
    hint = type_class.render_hint("list")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/credentials/{credential_id}",
    response_model=Detail[to_pydantic_model(Credential)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["access/credentials"],
)
async def get_credential(
    request: Request,
    site_id: str,
    credential_id: str,
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
            "credential_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "access")
        await _maybe_set_site(cm, site_id)
        try:
            credential = await mgr.get_credential(credential_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="credential not found")

    type_class = request.app.state.type_registry.lookup("access", "credentials/{id}")
    data = type_class.from_manager_output(credential).to_dict()
    hint = type_class.render_hint("detail")
    return {
        "data": data,
        "render_hint": hint,
    }
