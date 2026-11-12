"""Site tools: the sites across every host on the account."""

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from unifi_sitemanager_mcp.runtime import inventory_manager, server, tool_failure, tool_success
from unifi_sitemanager_mcp.tools.hosts import Cursor, PageSize

logger = logging.getLogger(__name__)


@server.tool(
    name="sitemanager_list_sites",
    title="List Sites",
    description=(
        "Lists the sites on every host the account behind the Site Manager API key can see, with device and "
        "client counts, ISP details and WAN health. Returns one page; pass next_cursor back as cursor for more. These IDs are "
        "scoped to the Site Manager tool family — do not pass them to Network, Protect, or Access tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="site",
    permission_action="read",
    auth="api_key_only",
)
async def sitemanager_list_sites(page_size: PageSize = None, cursor: Cursor = None) -> Dict[str, Any]:
    """List sites."""
    logger.info("sitemanager_list_sites tool called")
    try:
        sites, token = await inventory_manager.list_sites(page_size=page_size, next_token=cursor)
        return tool_success(
            {
                "sites": [site.model_dump(exclude_none=True) for site in sites],
                "count": len(sites),
                "next_cursor": token,
            }
        )
    except Exception as e:
        return tool_failure("list sites", e)
