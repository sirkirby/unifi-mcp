"""Status tool: whether InnerSpace is installed and running on the console."""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_innerspace_mcp.runtime import server, system_manager, tool_failure, tool_success

logger = logging.getLogger(__name__)


@server.tool(
    name="innerspace_get_status",
    title="Get InnerSpace Status",
    description=(
        "Reports whether the InnerSpace application is installed and running on the UniFi OS console, with its "
        "installed version and any update available. Read-only. Run this first when other InnerSpace tools "
        "report that the application is not installed or not running."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="status",
    permission_action="read",
    auth="local_only",
)
async def innerspace_get_status() -> Dict[str, Any]:
    """Get the InnerSpace application status."""
    logger.info("innerspace_get_status tool called")
    try:
        status = await system_manager.get_status()
        return tool_success(status.model_dump())
    except Exception as e:
        return tool_failure("get InnerSpace status", e)
