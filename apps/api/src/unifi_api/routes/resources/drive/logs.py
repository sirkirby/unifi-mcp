"""GET /v1/sites/{site_id}/drive/logs — the NAS's system log, newest first, one page at a time."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from unifi_core.drive.models.logs import DEFAULT_LOG_LIMIT, MAX_LOG_LIMIT

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.drive._common import SITE_NOTE, detail, read
from unifi_api.services.drive import log_query

router = APIRouter()


# The bounds and choices are stated in the schema only: the core log query validates them, so a bad
# value gets Drive's fixed-text 422 rather than the generic request-validation answer.
@router.get(
    "/sites/{site_id}/drive/logs",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/logs"],
    summary="List Drive system log entries",
    description=(
        "The NAS's system log, newest first, as the Drive UI's System Log shows it: time, severity, category, "
        "type, event and message. Messages name the users, client addresses, drives and pools involved. One "
        "page per call; pass next_cursor back as cursor, with the same filters, for the next. An unknown "
        f"category or type is a 422. {SITE_NOTE}"
    ),
)
async def list_drive_logs(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(
        DEFAULT_LOG_LIMIT,
        description=f"Most entries per page, 1 to {MAX_LOG_LIMIT}",
        json_schema_extra={"minimum": 1, "maximum": MAX_LOG_LIMIT},
    ),
    severities: list[str] | None = Query(
        None,
        description="Only entries at these severities; repeat the parameter for more than one. Omit for all.",
        json_schema_extra={"items": {"type": "string", "enum": ["low", "medium", "high", "very_high"]}},
    ),
    category: str | None = Query(
        None, description="Only entries in this category: activity, storage or settings on current firmware"
    ),
    types: list[str] | None = Query(
        None,
        description=(
            "Only entries of these types, such as storagePool, drive, hotSpare, userAccess or fanMode; repeat the "
            "parameter for more than one"
        ),
    ),
    keyword: str | None = Query(None, description="Only entries whose text matches this keyword"),
    scope: str | None = Query(
        None,
        description="audit: user and admin actions; flow: file activity; all (default): everything",
        json_schema_extra={"enum": ["all", "audit", "flow"]},
    ),
    after: str | None = Query(
        None, description="Only entries after this ISO 8601 time with offset, e.g. 2026-11-20T00:00:00Z"
    ),
    before: str | None = Query(None, description="Only entries before this ISO 8601 time with offset"),
    cursor: str | None = Query(None, description="next_cursor from the previous page"),
) -> dict:
    operation = "list Drive system log entries"
    query = log_query(
        operation,
        limit=limit,
        severities=severities,
        category=category,
        types=types,
        keyword=keyword,
        scope=scope,
        after=after,
        before=before,
        cursor=cursor,
    )
    result = await read(
        request, controller, manager_attr="log_manager", method="list_logs", operation=operation, args=(query,)
    )
    return detail(request, "drive_list_logs", result, operation=operation)
