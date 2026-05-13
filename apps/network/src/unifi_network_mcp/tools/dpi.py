"""
DPI (Deep Packet Inspection) application lookup tools for UniFi Network MCP server.

Provides read-only access to the UniFi DPI application and category database
via the official integration API. Use these to find application IDs for use
in OON policies and firewall rules.

Requires an API key (UNIFI_API_KEY or UNIFI_NETWORK_API_KEY).

NOTE: As of Network App 10.1.85, the official API only returns categories 0-1
(instant messengers, P2P — ~2,100 apps). Categories 4+ (streaming, social
media, gaming) are not yet populated by Ubiquiti. For apps not found here,
add via the UniFi UI and read back the IDs from the policy.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.network.models.dpi import (
    dpi_application_from_controller,
    dpi_category_from_controller,
)
from unifi_network_mcp.runtime import dpi_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_dpi_applications",
    description="List DPI applications available for use in firewall rules and OON policies. "
    "Returns application names and their compound IDs. Supports name-based search. "
    "NOTE: The official API currently only returns categories 0-1 (IM, P2P). "
    "Streaming, social media, and other categories are not yet populated by Ubiquiti. "
    "For apps not found here, add via the UniFi UI and read back the IDs from the policy. "
    "Requires UNIFI_API_KEY or UNIFI_NETWORK_API_KEY.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_dpi_applications(
    search: Annotated[
        Optional[str],
        Field(description="Search for apps by name (case-insensitive, client-side filter). E.g., 'slack', 'telegram'"),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max results per page (default 100, max 2500)"),
    ] = 100,
    offset: Annotated[
        int,
        Field(description="Pagination offset (default 0)"),
    ] = 0,
) -> Dict[str, Any]:
    """
    Lists DPI applications from the official UniFi API.

    Args:
        search: Optional name search filter.
        limit: Max results per page.
        offset: Pagination offset.

    Returns:
        A dictionary with applications, count, and pagination info.
    """
    try:
        result = await dpi_manager.get_dpi_applications(
            limit=min(limit, 2500),
            offset=offset,
            search=search,
        )

        apps = result.get("data", [])
        formatted = [dpi_application_from_controller(a).model_dump(exclude_none=True) for a in apps]

        response = {
            "success": True,
            "count": len(formatted),
            "total_count": result.get("totalCount", len(formatted)),
            "offset": result.get("offset", offset),
            "limit": result.get("limit", limit),
            "applications": formatted,
        }

        if result.get("filtered_from"):
            response["filtered_from"] = result["filtered_from"]
            response["note"] = f"Filtered {result['filtered_from']} total apps by search term '{search}'"

        return response
    except Exception as e:
        logger.error("Error listing DPI applications: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list DPI applications: {e}"}


@server.tool(
    name="unifi_list_dpi_categories",
    description="List DPI application categories (e.g., 'Instant messengers', 'Peer-to-peer networks', "
    "'Media streaming services'). Categories group applications for DPI classification. "
    "Requires UNIFI_API_KEY or UNIFI_NETWORK_API_KEY.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_dpi_categories(
    limit: Annotated[
        int,
        Field(description="Max results per page (default 100)"),
    ] = 100,
    offset: Annotated[
        int,
        Field(description="Pagination offset (default 0)"),
    ] = 0,
) -> Dict[str, Any]:
    """
    Lists DPI application categories from the official UniFi API.

    Args:
        limit: Max results per page.
        offset: Pagination offset.

    Returns:
        A dictionary with categories, count, and pagination info.
    """
    try:
        result = await dpi_manager.get_dpi_categories(limit=limit, offset=offset)

        categories = result.get("data", [])
        formatted = [dpi_category_from_controller(c).model_dump(exclude_none=True) for c in categories]

        return {
            "success": True,
            "count": len(formatted),
            "total_count": result.get("totalCount", len(formatted)),
            "categories": formatted,
        }
    except Exception as e:
        logger.error("Error listing DPI categories: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list DPI categories: {e}"}
