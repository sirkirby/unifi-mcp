"""
Content filtering tools for UniFi Network MCP server.

Content filtering uses DNS-based category blocking and safe search
enforcement. Profiles can target specific clients (by MAC address)
or entire networks (by network ID).

Creation uses the Network UI's /content-filtering/create endpoint.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import create_preview, delete_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.content_filter import (
    MUTABLE_FIELDS as CF_MUTABLE_FIELDS,
)
from unifi_core.network.models.content_filter import (
    from_controller as cf_from_controller,
)
from unifi_core.network.models.content_filter import to_controller_create as cf_to_create
from unifi_core.network.models.content_filter import (
    to_controller_update as cf_to_update,
)
from unifi_core.network.models.content_filter import with_create_defaults
from unifi_core.redaction import redact_sensitive_fields
from unifi_network_mcp.runtime import content_filter_manager, server, should_redact_sensitive_fields

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_content_filters",
    description="List content filtering profiles. "
    "Profiles control DNS-based category blocking, safe search enforcement "
    "(GOOGLE, YOUTUBE, BING), and domain allow/block lists. "
    "Profiles can target specific clients by MAC or entire networks by ID. "
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
    name="unifi_create_content_filter",
    description="Create a content filtering profile with a non-empty blocked_categories list and exactly one "
    "non-empty client_macs or network_ids scope. Profiles start disabled with an ALWAYS all-day schedule unless "
    "those fields are explicitly set. "
    "Requires confirmation.",
    permission_category="content_filter",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_content_filter(
    filter_data: Annotated[
        dict,
        Field(
            description="Profile fields: non-empty name and blocked_categories list; exactly one non-empty "
            "client_macs or network_ids list; optional enabled, safe_search, and flattened schedule fields"
        ),
    ],
    confirm: Annotated[
        bool, Field(description="When true, creates the profile. When false, returns a preview")
    ] = False,
) -> Dict[str, Any]:
    """Validate and preview or create a scoped content filter."""
    try:
        cf_to_create(filter_data)
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        return {"success": False, "error": f"Invalid content filter creation fields: {fields}"}
    except ValueError as exc:
        return {"success": False, "error": f"Invalid content filter creation: {exc}"}
    if not confirm:
        preview_data = with_create_defaults(filter_data)
        return create_preview(
            resource_type="content_filter", resource_data=preview_data, resource_name=filter_data["name"].strip()
        )
    try:
        result = await content_filter_manager.create_content_filter(filter_data)
        if result.get("uncertain") is True:
            return result
        return redact_sensitive_fields(
            {"success": True, "data": cf_from_controller(result).model_dump(exclude_none=True)},
            redact_sensitive=should_redact_sensitive_fields(),
        )
    except Exception as exc:
        logger.error("Failed to create content filter: %s", type(exc).__name__)
        return {"success": False, "error": f"Failed to create content filter: {type(exc).__name__}"}


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
            "client_macs (list of MACs), network_ids (list), "
            "schedule_mode ('ALWAYS'/'EVERY_DAY'/'EVERY_WEEK'/'CUSTOM'/'ONE_TIME_ONLY'), "
            "schedule_days (lowercase mon..sun), schedule_time_all_day (bool), "
            "schedule_time_start/end (HH:MM), schedule_date_start/end (YYYY-MM-DD)"
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

    # Keep the preview in the caller-facing dialect; translate to the controller
    # dialect only on the write path.
    unknown = set(filter_data) - CF_MUTABLE_FIELDS - {"categories"}
    if unknown:
        return {"success": False, "error": f"Unknown or read-only content filter fields: {sorted(unknown)}"}
    public_updates = {k: v for k, v in filter_data.items() if k in CF_MUTABLE_FIELDS | {"categories"} and v is not None}
    if not public_updates:
        return {"success": False, "error": "Update data is effectively empty or invalid."}
    try:
        controller_updates = cf_to_update(public_updates)
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        return {"success": False, "error": f"Invalid content filter update fields: {fields}"}
    except ValueError as exc:
        return {"success": False, "error": f"Invalid content filter update: {exc}"}

    if not confirm:
        try:
            existing = await content_filter_manager.get_content_filter_by_id(filter_id)
            current = cf_from_controller(existing).model_dump(exclude_none=True)
            if "categories" in public_updates:
                current["categories"] = current["blocked_categories"]
            preview = update_preview(
                resource_type="content_filter",
                resource_id=filter_id,
                resource_name=current.get("name") or filter_id,
                current_state=current,
                updates=public_updates,
            )
            return redact_sensitive_fields(preview, redact_sensitive=should_redact_sensitive_fields())
        except UniFiNotFoundError:
            return {"success": False, "error": "Failed to preview content filter update: profile not found"}
        except Exception as exc:
            logger.error("Failed to read content filter for update preview: %s", type(exc).__name__)
            return {"success": False, "error": f"Failed to preview content filter update: {type(exc).__name__}"}

    try:
        merged = await content_filter_manager.update_content_filter(filter_id, controller_updates)
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
        return delete_preview(
            resource_type="content_filter",
            resource_id=filter_id,
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
