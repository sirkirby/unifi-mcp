"""
Content filtering tools for UniFi Network MCP server.

Content filtering uses DNS-based category blocking and safe search
enforcement. Profiles can target specific clients (by MAC address)
or entire networks (by network ID).

NOTE: The UniFi API does not support creating content filtering profiles
via POST (returns 405). Profiles must be created through the UniFi UI
first, then managed (list, update, delete) via these tools.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.content_filter import (
    from_controller as cf_from_controller,
)
from unifi_core.network.models.content_filter import (
    to_controller_update as cf_to_update,
)
from unifi_network_mcp.runtime import content_filter_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_content_filters",
    description="List content filtering profiles. "
    "Profiles control DNS-based category blocking, safe search enforcement "
    "(GOOGLE, YOUTUBE, BING), and domain allow/block lists. "
    "Profiles can target specific clients by MAC or entire networks by ID. "
    "NOTE: Profiles must be created in the UniFi UI — the API only supports list, update, and delete. "
    "Common categories: FAMILY, ADVERTISEMENT, MALWARE, PHISHING, BOTNETS, SPAM, SPYWARE, "
    "HACKING, ANONYMIZERS, DNS_TUNNELING, ADULT, ALCOHOL, DRUGS, GAMBLING, VIOLENCE, "
    "PORNOGRAPHY, NUDITY, WEAPONS, DATING, HATE_SPEECH_AND_EXTREMISM, CHILD_ABUSE, CIPA, "
    "EMPTY_DOMAINS, NEWLY_DISCOVERED_DOMAINS, PARKED_DOMAINS, UNREACHABLE_DOMAINS.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_content_filters() -> Dict[str, Any]:
    """
    Lists all content filtering profiles configured on the controller.

    Returns:
        A dictionary containing:
        - success (bool): Indicates if the operation was successful.
        - count (int): Number of profiles found.
        - filters (List[Dict]): List of profiles with summary info.
    """
    try:
        filters = await content_filter_manager.get_content_filters()
        formatted = [cf_from_controller(f).model_dump(exclude_none=True) for f in filters]
        return {
            "success": True,
            "site": content_filter_manager._connection.site,
            "count": len(formatted),
            "filters": formatted,
        }
    except Exception as e:
        logger.error("Error listing content filters: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list content filters: {e}"}


@server.tool(
    name="unifi_get_content_filter_details",
    description="Get detailed configuration for a specific content filtering profile by ID. "
    "Returns the full profile including categories, client MACs, network IDs, "
    "safe search settings, and allow/block lists.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_content_filter_details(
    filter_id: Annotated[str, Field(description="The unique identifier (_id) of the content filtering profile")],
) -> Dict[str, Any]:
    """
    Gets the detailed configuration of a specific content filtering profile.

    Args:
        filter_id (str): The unique identifier of the profile.

    Returns:
        A dictionary containing the full profile configuration.
    """
    try:
        if not filter_id:
            return {"success": False, "error": "filter_id is required"}

        profile = await content_filter_manager.get_content_filter_by_id(filter_id)
        return {
            "success": True,
            "filter_id": filter_id,
            "details": json.loads(json.dumps(profile, default=str)),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting content filter %s: %s", filter_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get content filter {filter_id}: {e}"}


@server.tool(
    name="unifi_update_content_filter",
    description="Update an existing content filtering profile. Pass only the fields you want to change — "
    "current values are automatically preserved. "
    "client_macs and network_ids are additive — both can be set and the filter applies to all. "
    "Safe search valid values: GOOGLE, YOUTUBE, BING (only these three are supported). "
    "Requires confirmation.",
    permission_category="content_filter",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_content_filter(
    filter_id: Annotated[str, Field(description="The ID of the profile to update")],
    filter_data: Annotated[
        dict,
        Field(
            description="Dictionary of fields to update. Pass only the fields you want to change — "
            "current values are automatically preserved. "
            "Allowed keys: name, enabled (bool), blocked_categories (list), "
            "safe_search (list: 'GOOGLE'/'YOUTUBE'/'BING'), "
            "client_macs (list of MACs), network_ids (list)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, updates the profile. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Updates an existing content filtering profile with partial data."""
    if not filter_id:
        return {"success": False, "error": "filter_id is required"}
    if not filter_data:
        return {"success": False, "error": "filter_data cannot be empty"}

    validated_data = cf_to_update(filter_data)
    if not validated_data:
        return {"success": False, "error": "Update data is effectively empty or invalid."}

    if not confirm:
        return update_preview(
            resource_type="content_filter",
            resource_id=filter_id,
            resource_name=filter_id,
            current_state={},
            updates=validated_data,
        )

    try:
        merged = await content_filter_manager.update_content_filter(filter_id, validated_data)
        return {
            "success": True,
            "message": f"Content filter '{merged.get('name', filter_id)}' updated successfully.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating content filter %s: %s", filter_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update content filter '{filter_id}': {e}"}


@server.tool(
    name="unifi_delete_content_filter",
    description="Delete a content filtering profile. Requires confirmation. "
    "WARNING: Deleting a profile removes DNS-based blocking for all targeted clients/networks.",
    permission_category="content_filter",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_content_filter(
    filter_id: Annotated[str, Field(description="The ID of the profile to delete")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the profile. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """
    Deletes a content filtering profile.

    Args:
        filter_id (str): The ID of the profile to delete.
        confirm (bool): Must be True to execute.

    Returns:
        Preview or success/failure status.
    """
    if not confirm:
        return create_preview(
            resource_type="content_filter",
            resource_data={"filter_id": filter_id},
            resource_name=filter_id,
            warnings=["Deleting a content filter removes DNS-based blocking for all targeted clients/networks."],
        )

    try:
        success = await content_filter_manager.delete_content_filter(filter_id)
        if success:
            return {"success": True, "message": f"Content filter '{filter_id}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete content filter '{filter_id}'."}
    except Exception as e:
        logger.error("Error deleting content filter %s: %s", filter_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete content filter '{filter_id}': {e}"}
