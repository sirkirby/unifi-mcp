"""
Dynamic DNS management tools for UniFi Network MCP server.

Provides CRUD for the controller's native Dynamic DNS provider entries via
the V1 REST endpoint /rest/dynamicdns. The provider secret (``x_password``)
is redacted at the egress boundary per the response redaction policy.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.dynamic_dns import (
    MUTABLE_FIELDS,
    DynamicDns,
)
from unifi_core.network.models.dynamic_dns import (
    from_controller as ddns_from_controller,
)
from unifi_core.network.models.dynamic_dns import (
    to_controller_create as ddns_to_create,
)
from unifi_core.network.models.dynamic_dns import (
    to_controller_update as ddns_to_update,
)
from unifi_core.redaction import redact_sensitive_fields
from unifi_network_mcp.runtime import dynamic_dns_manager, server, should_redact_sensitive_fields

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_dynamic_dns",
    description="List all Dynamic DNS provider entries configured on the controller. "
    "Returns hostname, service/provider, WAN interface, login, and options for each entry. "
    "The provider password/token is redacted.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_dynamic_dns() -> Dict[str, Any]:
    """List all Dynamic DNS entries."""
    logger.info("unifi_list_dynamic_dns tool called")
    try:
        entries = await dynamic_dns_manager.list_dynamic_dns()
        formatted = [ddns_from_controller(e).model_dump(exclude_none=True) for e in entries]
        return redact_sensitive_fields(
            {
                "success": True,
                "site": dynamic_dns_manager._connection.site,
                "count": len(formatted),
                "entries": formatted,
            },
            redact_sensitive=should_redact_sensitive_fields(),
        )
    except Exception as e:
        logger.error("Error listing Dynamic DNS entries: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list Dynamic DNS entries: {e}"}


@server.tool(
    name="unifi_get_dynamic_dns_details",
    description="Get details for a specific Dynamic DNS entry by ID. The provider password/token is redacted.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_dynamic_dns_details(
    entry_id: Annotated[str, Field(description="The unique identifier (_id) of the Dynamic DNS entry")],
) -> Dict[str, Any]:
    """Get a specific Dynamic DNS entry."""
    logger.info("unifi_get_dynamic_dns_details tool called (entry_id=%s)", entry_id)
    try:
        entry = await dynamic_dns_manager.get_dynamic_dns(entry_id)
        return redact_sensitive_fields(
            {
                "success": True,
                "entry_id": entry_id,
                "details": ddns_from_controller(entry).model_dump(exclude_none=True),
            },
            redact_sensitive=should_redact_sensitive_fields(),
        )
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting Dynamic DNS entry %s: %s", entry_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get Dynamic DNS entry {entry_id}: {e}"}


@server.tool(
    name="unifi_create_dynamic_dns",
    description="Create a new Dynamic DNS provider entry. "
    "Required: host_name (hostname to keep updated, e.g. 'home.example.com'), "
    "service (provider: 'dyndns'/'noip'/'namecheap'/'cloudflare'/'custom'/...). "
    "Optional: interface ('wan' [default] or 'wan2'), login (username), x_password (password/token), "
    "server + custom_service (for the 'custom' service), options (list of strings). "
    "Requires confirmation.",
    permission_category="dynamic_dns",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_dynamic_dns(
    entry_data: Annotated[
        Dict[str, Any],
        Field(description="Dynamic DNS entry data. See tool description for required and optional fields."),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the entry. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a new Dynamic DNS entry."""
    logger.info("unifi_create_dynamic_dns tool called (confirm=%s)", confirm)

    try:
        model = DynamicDns(**{k: v for k, v in entry_data.items() if k in MUTABLE_FIELDS})
    except Exception as exc:
        return {"success": False, "error": f"Validation error: {exc}"}
    if not model.host_name or not model.service:
        return {"success": False, "error": "Validation error: 'host_name' and 'service' are required"}
    validated_data = ddns_to_create(model)

    if not confirm:
        return redact_sensitive_fields(
            create_preview(
                resource_type="dynamic_dns",
                resource_data=validated_data,
                resource_name=validated_data.get("host_name", "unnamed"),
            ),
            redact_sensitive=should_redact_sensitive_fields(),
        )

    try:
        result = await dynamic_dns_manager.create_dynamic_dns(validated_data)
        if result:
            return redact_sensitive_fields(
                {
                    "success": True,
                    "message": f"Dynamic DNS entry '{validated_data.get('host_name', '')}' created successfully.",
                    "details": json.loads(json.dumps(result, default=str)),
                },
                redact_sensitive=should_redact_sensitive_fields(),
            )
        return {
            "success": False,
            "error": f"Failed to create Dynamic DNS entry '{validated_data.get('host_name', '')}'.",
        }
    except Exception as e:
        logger.error("Error creating Dynamic DNS entry: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create Dynamic DNS entry: {e}"}


@server.tool(
    name="unifi_update_dynamic_dns",
    description="Update an existing Dynamic DNS entry. "
    "Pass only the fields you want to change — current values are automatically preserved. "
    "Fields: host_name (str), service (str), server (str), login (str), x_password (str), "
    "interface ('wan'/'wan2'), custom_service (str), options (list of strings). "
    "Requires confirmation.",
    permission_category="dynamic_dns",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_dynamic_dns(
    entry_id: Annotated[
        str, Field(description="The ID of the Dynamic DNS entry to update (from unifi_list_dynamic_dns)")
    ],
    update_data: Annotated[
        Dict[str, Any],
        Field(description="Dictionary of fields to update. See tool description for supported fields."),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Update an existing Dynamic DNS entry."""
    logger.info("unifi_update_dynamic_dns tool called (entry_id=%s, confirm=%s)", entry_id, confirm)

    if not update_data:
        return {"success": False, "error": "No fields provided to update."}

    validated_data = ddns_to_update(update_data)
    if not validated_data:
        return {"success": False, "error": "No valid fields to update after validation."}

    if not confirm:
        return redact_sensitive_fields(
            update_preview(
                resource_type="dynamic_dns",
                resource_id=entry_id,
                resource_name=entry_id,
                current_state={},
                updates=validated_data,
            ),
            redact_sensitive=should_redact_sensitive_fields(),
        )

    try:
        merged = await dynamic_dns_manager.update_dynamic_dns(entry_id, validated_data)
        return {
            "success": True,
            "message": f"Dynamic DNS entry '{merged.get('host_name', entry_id)}' updated successfully.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating Dynamic DNS entry %s: %s", entry_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update Dynamic DNS entry {entry_id}: {e}"}


@server.tool(
    name="unifi_delete_dynamic_dns",
    description="Delete a Dynamic DNS entry. Use unifi_list_dynamic_dns to find entry IDs. Requires confirmation.",
    permission_category="dynamic_dns",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_dynamic_dns(
    entry_id: Annotated[
        str, Field(description="The ID of the Dynamic DNS entry to delete (from unifi_list_dynamic_dns)")
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the entry. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Delete a Dynamic DNS entry."""
    logger.info("unifi_delete_dynamic_dns tool called (entry_id=%s, confirm=%s)", entry_id, confirm)
    if not confirm:
        return create_preview(
            resource_type="dynamic_dns",
            resource_data={"entry_id": entry_id},
            resource_name=entry_id,
            warnings=["This will permanently delete the Dynamic DNS entry."],
        )

    try:
        success = await dynamic_dns_manager.delete_dynamic_dns(entry_id)
        if success:
            return {"success": True, "message": f"Dynamic DNS entry '{entry_id}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete Dynamic DNS entry '{entry_id}'."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting Dynamic DNS entry %s: %s", entry_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete Dynamic DNS entry '{entry_id}': {e}"}
