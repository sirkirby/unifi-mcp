"""
DNS record management tools for UniFi Network MCP server.

Provides CRUD for static DNS records (A, AAAA, CNAME, MX, TXT, SRV)
via the v2 API endpoint /static-dns.
"""

import json
import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.dns import (
    DnsRecord,
)
from unifi_core.network.models.dns import (
    from_controller as dns_from_controller,
)
from unifi_core.network.models.dns import (
    to_controller_create as dns_to_create,
)
from unifi_core.network.models.dns import (
    to_controller_update as dns_to_update,
)
from unifi_network_mcp.runtime import dns_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_list_dns_records",
    description="List all static DNS records configured on the controller. "
    "Returns hostname, value, record type, enabled state, and TTL for each record.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_dns_records() -> Dict[str, Any]:
    """List all static DNS records."""
    logger.info("unifi_list_dns_records tool called")
    try:
        records = await dns_manager.list_dns_records()
        formatted = [dns_from_controller(r).model_dump(exclude_none=True) for r in records]
        return {
            "success": True,
            "site": dns_manager._connection.site,
            "count": len(formatted),
            "records": formatted,
        }
    except Exception as e:
        logger.error("Error listing DNS records: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list DNS records: {e}"}


@server.tool(
    name="unifi_get_dns_record_details",
    description="Get details for a specific DNS record by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_dns_record_details(
    record_id: Annotated[str, Field(description="The unique identifier (_id) of the DNS record")],
) -> Dict[str, Any]:
    """Get a specific DNS record."""
    logger.info("unifi_get_dns_record_details tool called (record_id=%s)", record_id)
    try:
        record = await dns_manager.get_dns_record(record_id)
        return {
            "success": True,
            "record_id": record_id,
            "details": json.loads(json.dumps(record, default=str)),
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting DNS record %s: %s", record_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get DNS record {record_id}: {e}"}


@server.tool(
    name="unifi_create_dns_record",
    description="Create a new static DNS record. "
    "Required: key (hostname, e.g. 'myhost.example.com'), value (IP or target hostname), "
    "record_type ('A'/'AAAA'/'CNAME'/'MX'/'TXT'/'SRV'). "
    "Optional: enabled (bool, default true), ttl (int, 0=default 300s), "
    "port (int, for SRV), priority (int, for MX/SRV), weight (int, for SRV). "
    "Requires confirmation.",
    permission_category="dns",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_dns_record(
    record_data: Annotated[
        Dict[str, Any],
        Field(description="DNS record data. See tool description for required and optional fields."),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the record. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Create a new static DNS record."""
    logger.info("unifi_create_dns_record tool called (confirm=%s)", confirm)

    try:
        model = DnsRecord(
            **{
                k: v
                for k, v in record_data.items()
                if k in ("key", "value", "record_type", "enabled", "ttl", "port", "priority", "weight")
            }
        )
    except Exception as exc:
        return {"success": False, "error": f"Validation error: {exc}"}
    if not model.key or not model.value or not model.record_type:
        return {"success": False, "error": "Validation error: 'key', 'value', and 'record_type' are required"}
    validated_data = dns_to_create(model)

    if not confirm:
        return create_preview(
            resource_type="dns_record",
            resource_data=validated_data,
            resource_name=validated_data.get("key", "unnamed"),
        )

    try:
        result = await dns_manager.create_dns_record(validated_data)
        if result:
            return {
                "success": True,
                "message": f"DNS record '{validated_data.get('key', '')}' created successfully.",
                "details": json.loads(json.dumps(result, default=str)),
            }
        return {"success": False, "error": f"Failed to create DNS record '{validated_data.get('key', '')}'."}
    except Exception as e:
        logger.error("Error creating DNS record: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create DNS record: {e}"}


@server.tool(
    name="unifi_update_dns_record",
    description="Update an existing DNS record. "
    "Pass only the fields you want to change — current values are automatically preserved. "
    "Fields: key (str), value (str), record_type ('A'/'AAAA'/'CNAME'/'MX'/'TXT'/'SRV'), "
    "enabled (bool), ttl (int), port (int), priority (int), weight (int). "
    "Requires confirmation.",
    permission_category="dns",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_dns_record(
    record_id: Annotated[str, Field(description="The ID of the DNS record to update (from unifi_list_dns_records)")],
    update_data: Annotated[
        Dict[str, Any],
        Field(description="Dictionary of fields to update. See tool description for supported fields."),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Update an existing DNS record."""
    logger.info("unifi_update_dns_record tool called (record_id=%s, confirm=%s)", record_id, confirm)

    if not update_data:
        return {"success": False, "error": "No fields provided to update."}

    validated_data = dns_to_update(update_data)
    if not validated_data:
        return {"success": False, "error": "No valid fields to update after validation."}

    if not confirm:
        return update_preview(
            resource_type="dns_record",
            resource_id=record_id,
            resource_name=record_id,
            current_state={},
            updates=validated_data,
        )

    try:
        merged = await dns_manager.update_dns_record(record_id, validated_data)
        return {
            "success": True,
            "message": f"DNS record '{merged.get('key', record_id)}' updated successfully.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating DNS record %s: %s", record_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update DNS record {record_id}: {e}"}


@server.tool(
    name="unifi_delete_dns_record",
    description="Delete a static DNS record. Use unifi_list_dns_records to find record IDs. Requires confirmation.",
    permission_category="dns",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_dns_record(
    record_id: Annotated[str, Field(description="The ID of the DNS record to delete (from unifi_list_dns_records)")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the record. When false (default), returns a preview"),
    ] = False,
) -> Dict[str, Any]:
    """Delete a DNS record."""
    logger.info("unifi_delete_dns_record tool called (record_id=%s, confirm=%s)", record_id, confirm)
    if not confirm:
        return create_preview(
            resource_type="dns_record",
            resource_data={"record_id": record_id},
            resource_name=record_id,
            warnings=["This will permanently delete the DNS record."],
        )

    try:
        success = await dns_manager.delete_dns_record(record_id)
        if success:
            return {"success": True, "message": f"DNS record '{record_id}' deleted successfully."}
        return {"success": False, "error": f"Failed to delete DNS record '{record_id}'."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting DNS record %s: %s", record_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete DNS record '{record_id}': {e}"}
