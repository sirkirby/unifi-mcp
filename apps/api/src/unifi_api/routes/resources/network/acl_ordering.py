"""Integration API ACL rule reads.

GET /v1/sites/{site_id}/integration-acl-rules — the Integration UUID rule list.
GET /v1/sites/{site_id}/acl-rules/ordering — the controller ordering those IDs address.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.acl_ordering import AclRuleOrdering, IntegrationAclRule
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
    return (0, str(raw.get("id") or ""))


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get(
    "/sites/{site_id}/integration-acl-rules",
    response_model=Page[to_pydantic_model(IntegrationAclRule)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/acl_ordering"],
    description=(
        "MAC ACL rules as the Integration API lists them. These IDs are scoped to the "
        "ACL-ordering tool family — do not pass V2 MAC ACL rule Mongo _id values here."
    ),
)
async def list_integration_acl_rules(
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
            "acl_manager",
            site=site_id,
        )
        items = await mgr.list_integration_acl_rules()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_list_integration_acl_rules")
    if tool_type is not None:
        type_class, kind = tool_type
        redact_sensitive = _redact_sensitive(request)
        rows = [type_class.from_manager_output(i, redact_sensitive=redact_sensitive).to_dict() for i in page]
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_list_integration_acl_rules")
        rows = [serializer.serialize(i) for i in page]
        hint = registry.render_hint_for_tool("unifi_list_integration_acl_rules")
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/acl-rules/ordering",
    response_model=Detail[to_pydantic_model(AclRuleOrdering)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/acl_ordering"],
    description=(
        "User-defined ACL rule ordering. These IDs are scoped to the ACL-ordering "
        "tool family — do not pass V2 MAC ACL rule Mongo _id values here."
    ),
)
async def get_acl_rule_ordering(
    request: Request,
    site_id: str,
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
            "acl_manager",
            site=site_id,
        )
        ordering = await mgr.get_acl_rule_ordering()
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_acl_rule_ordering")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(ordering).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_acl_rule_ordering")
        data = serializer.serialize(ordering)
        hint = registry.render_hint_for_tool("unifi_get_acl_rule_ordering")
    return {"data": data, "render_hint": hint}
