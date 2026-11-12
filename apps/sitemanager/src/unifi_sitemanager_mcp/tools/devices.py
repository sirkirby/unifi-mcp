"""Device tools: UniFi devices across every host on the account."""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_sitemanager_mcp.runtime import inventory_manager, server, tool_failure, tool_success
from unifi_sitemanager_mcp.tools.hosts import Cursor, PageSize

logger = logging.getLogger(__name__)


@server.tool(
    name="sitemanager_list_devices",
    title="List Devices",
    description=(
        "Lists UniFi devices grouped by the host that manages them, with model, status, firmware version and "
        "whether an update is available. Returns one page of hosts; pass next_cursor back as cursor for more. These IDs are "
        "scoped to the Site Manager tool family — do not pass them to Network, Protect, or Access tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="device",
    permission_action="read",
    auth="api_key_only",
)
async def sitemanager_list_devices(
    host_ids: Annotated[
        list[str] | None,
        Field(description="Only return devices on these Site Manager host ids (up to 100). Omit for every host."),
    ] = None,
    updated_since: Annotated[
        str | None,
        Field(description="RFC 3339 timestamp; only return hosts whose device list changed after it."),
    ] = None,
    page_size: PageSize = None,
    cursor: Cursor = None,
) -> Dict[str, Any]:
    """List devices grouped by host."""
    logger.info("sitemanager_list_devices tool called")
    try:
        groups, token = await inventory_manager.list_devices(
            host_ids=host_ids, updated_since=updated_since, page_size=page_size, next_token=cursor
        )
        hosts = [group.model_dump(exclude_none=True) for group in groups]
        return tool_success(
            {
                "hosts": hosts,
                "host_count": len(hosts),
                "device_count": sum(len(host.get("devices", [])) for host in hosts),
                "next_cursor": token,
            }
        )
    except Exception as e:
        return tool_failure("list devices", e)
