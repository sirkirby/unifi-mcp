"""System log tools for the UniFi Drive MCP server. Read-only."""

import logging
from typing import Annotated, Any, Dict, List, Literal, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.drive.models.logs import DEFAULT_LOG_LIMIT, MAX_LOG_LIMIT, DriveLogQuery
from unifi_drive_mcp.runtime import log_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)


def _invalid(exc: ValidationError) -> Dict[str, Any]:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first.get("loc", ()))
    return {"success": False, "error": f"Invalid input{f' ({where})' if where else ''}: {first['msg']}"}


@server.tool(
    name="drive_list_logs",
    description=(
        "Lists the NAS's system log, newest first, as the Drive UI's System Log shows it: time, severity, "
        "category, type, event and message. Messages name the users, client addresses, drives and pools "
        "involved. Returns one page; pass next_cursor back as cursor, with the same filters, for more."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="log",
    permission_action="read",
)
async def drive_list_logs(
    limit: Annotated[
        int, Field(ge=1, le=MAX_LOG_LIMIT, description=f"Most entries per page, 1-{MAX_LOG_LIMIT} (default 50)")
    ] = DEFAULT_LOG_LIMIT,
    severities: Annotated[
        Optional[List[Literal["low", "medium", "high", "very_high"]]],
        Field(description="Only entries at these severities. Omit for all."),
    ] = None,
    category: Annotated[
        Optional[str],
        Field(description="Only entries in this category: activity, storage or settings on current firmware."),
    ] = None,
    types: Annotated[
        Optional[List[str]],
        Field(
            description=(
                "Only entries of these types, such as storagePool, drive, hotSpare, userAccess or fanMode. "
                "An unknown type is an error that lists the valid ones."
            )
        ),
    ] = None,
    keyword: Annotated[Optional[str], Field(description="Only entries whose text matches this keyword")] = None,
    scope: Annotated[
        Optional[Literal["all", "audit", "flow"]],
        Field(description="audit: user and admin actions; flow: file activity; all (default): everything"),
    ] = None,
    after: Annotated[
        Optional[str], Field(description="Only entries after this ISO 8601 time with offset, e.g. 2026-11-20T00:00:00Z")
    ] = None,
    before: Annotated[Optional[str], Field(description="Only entries before this ISO 8601 time with offset")] = None,
    cursor: Annotated[Optional[str], Field(description="next_cursor from the previous page")] = None,
) -> Dict[str, Any]:
    """List system log entries."""
    try:
        query = DriveLogQuery(
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
    except ValidationError as exc:
        return _invalid(exc)
    try:
        page = await log_manager.list_logs(query)
        entries = [entry.model_dump(exclude_none=True) for entry in page.entries]
        return tool_success({"entries": entries, "count": len(entries), "next_cursor": page.next_cursor})
    except Exception as exc:
        return tool_failure("list logs", exc)
