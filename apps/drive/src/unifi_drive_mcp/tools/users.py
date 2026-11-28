"""User and group tools for the UniFi Drive MCP server. Read-only: no tool invites, changes or removes anyone."""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_drive_mcp.runtime import server, tool_failure, tool_success, user_manager

logger = logging.getLogger(__name__)


@server.tool(
    name="drive_list_users",
    description=(
        "Lists the NAS's users with username, full name, email, status, access level (owner, admin or "
        "user), console roles, personal drive and Active Directory flags, and last login. These user IDs "
        "are scoped to UniFi Drive users; do not pass them as shared drive or group IDs, or to other "
        "products' tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="user",
    permission_action="read",
)
async def drive_list_users() -> Dict[str, Any]:
    """List users."""
    try:
        users = await user_manager.list_users()
        return tool_success({"users": [user.model_dump(exclude_none=True) for user in users], "count": len(users)})
    except Exception as exc:
        return tool_failure("list users", exc)


@server.tool(
    name="drive_list_groups",
    description=(
        "Lists the UniFi OS user groups that shared drive access can be granted to, with id and name. "
        "These group IDs are scoped to UniFi Drive user groups; do not pass them as user or shared drive IDs."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="user",
    permission_action="read",
)
async def drive_list_groups() -> Dict[str, Any]:
    """List user groups."""
    try:
        groups = await user_manager.list_groups()
        return tool_success({"groups": [group.model_dump(exclude_none=True) for group in groups], "count": len(groups)})
    except Exception as exc:
        return tool_failure("list groups", exc)
