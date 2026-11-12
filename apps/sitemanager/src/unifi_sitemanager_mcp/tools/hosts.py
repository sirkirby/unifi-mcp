"""Host tools: the consoles and self-hosted servers linked to the account."""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_sitemanager_mcp.runtime import inventory_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)

PageSize = Annotated[
    int | None,
    Field(description="Maximum entries in this page (1-500). Omit for the API default."),
]
Cursor = Annotated[
    str | None,
    Field(
        description=(
            "The next_cursor from a previous page. Omit for the first page. A page can hold fewer entries than "
            "page_size, even none: keep paging until next_cursor is absent."
        )
    ),
]


@server.tool(
    name="sitemanager_list_hosts",
    title="List Hosts",
    description=(
        "Lists the UniFi consoles and self-hosted servers linked to the account behind the Site Manager API key, "
        "with connection state, OS version, hardware model and installed applications. Returns one page; pass "
        "next_cursor back as cursor for more. These IDs are scoped to the Site Manager tool family — do not pass them to "
        "Network, Protect, or Access tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="host",
    permission_action="read",
    auth="api_key_only",
)
async def sitemanager_list_hosts(page_size: PageSize = None, cursor: Cursor = None) -> Dict[str, Any]:
    """List hosts."""
    logger.info("sitemanager_list_hosts tool called")
    try:
        hosts, token = await inventory_manager.list_hosts(page_size=page_size, next_token=cursor)
        return tool_success(
            {
                "hosts": [host.model_dump(exclude_none=True) for host in hosts],
                "count": len(hosts),
                "next_cursor": token,
            }
        )
    except Exception as e:
        return tool_failure("list hosts", e)


@server.tool(
    name="sitemanager_get_host",
    title="Get Host",
    description=(
        "Returns one host by its Site Manager host id. Set include_reported_state for the full state the host "
        "reports (large). These IDs are scoped to the Site Manager tool family — do not pass them to "
        "Network, Protect, or Access tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="host",
    permission_action="read",
    auth="api_key_only",
)
async def sitemanager_get_host(
    host_id: Annotated[str, Field(description="Site Manager host id, from sitemanager_list_hosts.")],
    include_reported_state: Annotated[
        bool,
        Field(description="When true, also returns the host's full reported state. Account data is left out."),
    ] = False,
) -> Dict[str, Any]:
    """Get one host."""
    logger.info("sitemanager_get_host tool called")
    try:
        host = await inventory_manager.get_host(host_id, include_reported_state=include_reported_state)
        return tool_success({"host": host.model_dump(exclude_none=True)})
    except Exception as e:
        return tool_failure("get host", e)
