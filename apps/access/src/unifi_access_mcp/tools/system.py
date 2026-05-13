"""System tools for UniFi Access MCP server.

Provides read-only tools for querying Access system info, health, and users.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_access_mcp.runtime import server, system_manager
from unifi_core.access.models.users import from_controller as user_from_controller
from unifi_core.access.models.system import (
    health_from_controller,
    system_info_from_controller,
)

logger = logging.getLogger(__name__)


@server.tool(
    name="access_get_system_info",
    description=(
        "Returns Access controller model, firmware version, uptime, and connected device counts. "
        "Use for basic health checks and capacity overview."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="system",
    permission_action="read",
    auth="either",
)
async def access_get_system_info() -> Dict[str, Any]:
    """Get Access system information."""
    logger.info("access_get_system_info tool called")
    try:
        raw = await system_manager.get_system_info()
        info = system_info_from_controller(raw).model_dump(exclude_none=True)
        return {"success": True, "data": info}
    except Exception as e:
        logger.error("Failed to get system info: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get system info: {e}"}


@server.tool(
    name="access_get_health",
    description=(
        "Returns Access system health summary including API client and proxy session status. "
        "Use to verify connectivity and diagnose auth path issues."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="system",
    permission_action="read",
    auth="either",
)
async def access_get_health() -> Dict[str, Any]:
    """Get Access system health metrics."""
    logger.info("access_get_health tool called")
    try:
        raw = await system_manager.get_health()
        health = health_from_controller(raw).model_dump(exclude_none=True)
        return {"success": True, "data": health}
    except Exception as e:
        logger.error("Failed to get health: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get health: {e}"}


@server.tool(
    name="access_list_users",
    description=(
        "Lists all users registered in the Access controller with their access credentials and groups. "
        "Use to audit who has physical access or to look up a specific user."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="system",
    permission_action="read",
    auth="local_only",
)
async def access_list_users(
    limit: Annotated[
        int | None,
        Field(description="Maximum number of users to return. Omit for all users."),
    ] = None,
    compact: Annotated[
        bool,
        Field(
            description=(
                "When true, strips scopes, permissions, groups, roles, and resources fields "
                "(~85% smaller). Recommended for overviews and summaries."
            )
        ),
    ] = False,
) -> Dict[str, Any]:
    """List users with access."""
    logger.info("access_list_users tool called (limit=%s, compact=%s)", limit, compact)
    try:
        page_size = limit if limit and limit > 0 else 25
        raw_users = await system_manager.list_users(page_size=page_size, compact=compact)
        users = [user_from_controller(u).model_dump(exclude_none=True) for u in raw_users]
        return {"success": True, "data": {"users": users, "count": len(users)}}
    except Exception as e:
        logger.error("Failed to list users: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list users: {e}"}


logger.info("System tools registered: access_get_system_info, access_get_health, access_list_users")
