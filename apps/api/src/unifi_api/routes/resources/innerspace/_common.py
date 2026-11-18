"""Shared InnerSpace route plumbing: capability check, the shared read, and response shaping.

The path ``site_id`` is the controller site of the other console products and
is ignored here. The InnerSpace site filter is the ``innerspace_site_id`` query
parameter.
"""

from __future__ import annotations

from typing import Any

from fastapi import Query, Request

from unifi_api.db.models import Controller
from unifi_api.routes.resources._common import require_capability
from unifi_api.services.innerspace import DEFAULT_LIMIT, ID_FAMILY, PRODUCT, map_innerspace_error, read_innerspace

SITE_NOTE = (
    "The path site_id is ignored; filter by InnerSpace site with innerspace_site_id. Read-only, through the console "
    f"session. {ID_FAMILY}"
)

SiteQuery = Query(
    None,
    description=f"InnerSpace site id to filter by; omit for every site. {ID_FAMILY}",
)
UnitQuery = Query(
    None,
    description="Length unit of the result: 'metric' or 'imperial'. Omit to use the project's own unit.",
)
LimitQuery = Query(
    DEFAULT_LIMIT,
    description="Maximum entries to return, 1 to 2000. The result reports the total and whether it was cut.",
)


async def read(
    request: Request,
    controller: Controller,
    *,
    manager_attr: str,
    method: str,
    operation: str,
    args: tuple[Any, ...] = (),
    **kwargs: Any,
) -> Any:
    require_capability(controller, PRODUCT)
    state = request.app.state
    return await read_innerspace(
        sessionmaker=state.sessionmaker,
        factory=state.manager_factory,
        controller_id=controller.id,
        manager_attr=manager_attr,
        method=method,
        operation=operation,
        args=args,
        kwargs=kwargs,
    )


def _projection(request: Request, tool: str) -> tuple[type, str, bool]:
    type_class, kind = request.app.state.type_registry.lookup_tool(tool)
    return type_class, kind, request.app.state.config.policy.response.redact_sensitive_fields


def detail(request: Request, tool: str, result: Any, *, operation: str) -> dict:
    """One result, projected; a result it cannot project maps like any other read failure."""
    type_class, kind, redact = _projection(request, tool)
    try:
        data = type_class.from_manager_output(result, redact_sensitive=redact).to_dict()
    except Exception as exc:
        raise map_innerspace_error(exc, operation) from None
    return {"data": data, "render_hint": type_class.render_hint(kind)}


def items(request: Request, tool: str, result: list[Any], *, operation: str) -> dict:
    """The whole list: InnerSpace lists are not paged, so there is no cursor."""
    type_class, kind, redact = _projection(request, tool)
    try:
        data = [type_class.from_manager_output(item, redact_sensitive=redact).to_dict() for item in result]
    except Exception as exc:
        raise map_innerspace_error(exc, operation) from None
    return {"items": data, "render_hint": type_class.render_hint(kind)}
