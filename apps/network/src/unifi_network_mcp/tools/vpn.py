"""
VPN configuration tools for Unifi Network MCP server.

This module provides MCP tools to interact with a Unifi Network Controller's VPN functions,
including managing VPN clients and servers.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field, WithJsonSchema

from unifi_core.confirmation import delete_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.vpn import (
    VpnAlternateAddressError,
    VpnAlternateAddressToolInput,
    alternate_address_view,
    vpn_alternate_address_input_schema,
)
from unifi_core.redaction import redact_sensitive_fields
from unifi_core.write_verification import format_tool_payload
from unifi_network_mcp.runtime import server, should_redact_sensitive_fields, vpn_manager

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_update_vpn_server_alternate_address",
    input_schema=vpn_alternate_address_input_schema(VpnAlternateAddressToolInput),
    description=(
        "Update the advertised alternate hostname or IPv4 address for a WireGuard VPN server. "
        "Pass only the fields you want to change — current values are automatically preserved. "
        "Requires Network session authentication and confirmation; verifies persistence after applying. "
        "MCP previews read live state; API action previews show submitted arguments only."
    ),
    permission_category="vpn_servers",
    permission_action="update",
    auth="local_only",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_vpn_server_alternate_address(
    server_id: Annotated[str, Field(description="VPN server networkconf _id from unifi_list_vpn_servers")],
    update_data: Annotated[
        Dict[str, Any],
        WithJsonSchema(vpn_alternate_address_input_schema()),
    ],
    confirm: Annotated[
        bool, Field(description="Apply when true; otherwise return a live before/after preview")
    ] = False,
) -> Dict[str, Any]:
    """Preview or apply the narrow alternate-address update through the Core manager."""
    try:
        if not confirm:
            before, after = await vpn_manager.prepare_vpn_server_alternate_address(server_id, update_data)
            payload = update_preview(
                resource_type="vpn_server",
                resource_id=server_id,
                resource_name=server_id,
                current_state=before,
                updates=after,
            )
        else:
            result = await vpn_manager.update_vpn_server_alternate_address(server_id, update_data)
            payload = format_tool_payload(
                result, site=vpn_manager._connection.site, success_message="VPN server alternate address verified."
            )
        return redact_sensitive_fields(payload, redact_sensitive=should_redact_sensitive_fields())
    except VpnAlternateAddressError as exc:
        return {"success": False, "error": f"Failed to update VPN server alternate address: {exc}"}
    except Exception as exc:
        logger.error("Failed to update VPN server alternate address: %s", type(exc).__name__)
        return {
            "success": False,
            "error": "Failed to update VPN server alternate address: check the server, session authentication, "
            "and alternate_address_enabled (boolean) / alternate_address (hostname or IPv4) fields",
        }


@server.tool(
    name="unifi_list_vpn_clients",
    description="List all configured VPN clients (Wireguard, OpenVPN, etc).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_vpn_clients() -> Dict[str, Any]:
    """Implementation for listing VPN clients."""
    redact_sensitive = should_redact_sensitive_fields()
    try:
        clients = await vpn_manager.get_vpn_clients()
        return redact_sensitive_fields(
            {
                "success": True,
                "site": vpn_manager._connection.site,
                "count": len(clients),
                "vpn_clients": clients,
            },
            redact_sensitive=redact_sensitive,
        )
    except Exception as e:
        logger.error("Error listing VPN clients: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list VPN clients: {e}"}


@server.tool(
    name="unifi_get_vpn_client_details",
    description="Get details for a specific VPN client by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_vpn_client_details(
    client_id: Annotated[
        str, Field(description="Unique identifier (_id) of the VPN client (from unifi_list_vpn_clients)")
    ],
) -> Dict[str, Any]:
    """Implementation for getting VPN client details."""
    redact_sensitive = should_redact_sensitive_fields()
    try:
        client = await vpn_manager.get_vpn_client_details(client_id)
        return redact_sensitive_fields(
            {
                "success": True,
                "site": vpn_manager._connection.site,
                "client_id": client_id,
                "details": client,
            },
            redact_sensitive=redact_sensitive,
        )
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting VPN client details for %s: %s", client_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get VPN client details for {client_id}: {e}"}


@server.tool(
    name="unifi_update_vpn_client_state",
    description="Enable or disable a specific VPN client by ID. Requires confirmation.",
    permission_category="vpn_clients",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_vpn_client_state(
    client_id: Annotated[
        str, Field(description="Unique identifier (_id) of the VPN client to update (from unifi_list_vpn_clients)")
    ],
    enabled: Annotated[bool, Field(description="Set to true to enable the VPN client, false to disable it")],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the state change. When false (default), returns a live-state preview"),
    ] = False,
) -> Dict[str, Any]:
    """Preview or update a VPN client's enabled state."""
    redact_sensitive = should_redact_sensitive_fields()
    try:
        current = await vpn_manager.get_vpn_client_details(client_id)
        if not confirm:
            return redact_sensitive_fields(
                update_preview(
                    resource_type="vpn_client",
                    resource_id=client_id,
                    resource_name=current.get("name", client_id),
                    current_state=current,
                    updates={"enabled": enabled},
                ),
                redact_sensitive=redact_sensitive,
            )

        write_result = await vpn_manager.update_vpn_client_state(client_id, enabled)
        payload = format_tool_payload(
            write_result,
            site=vpn_manager._connection.site,
            success_message=f"VPN client '{client_id}' {'enabled' if enabled else 'disabled'}.",
        )
        payload["client_id"] = client_id
        if not write_result.success:
            payload["error"] = f"Failed to update state for VPN client {client_id}: {write_result.error}"
        return redact_sensitive_fields(payload, redact_sensitive=redact_sensitive)
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating state for VPN client %s: %s", client_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update state for VPN client {client_id}: {e}"}


@server.tool(
    name="unifi_delete_vpn_client",
    description="Delete a VPN client configuration by ID. Requires confirmation.",
    permission_category="vpn_clients",
    permission_action="delete",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def delete_vpn_client(
    client_id: Annotated[
        str, Field(description="Unique identifier (_id) of the VPN client to delete (from unifi_list_vpn_clients)")
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the VPN client. When false (default), returns a live-state preview"),
    ] = False,
) -> Dict[str, Any]:
    """Preview or delete a VPN client configuration."""
    redact_sensitive = should_redact_sensitive_fields()
    try:
        current = await vpn_manager.get_vpn_client_details(client_id)
        if not confirm:
            return redact_sensitive_fields(
                delete_preview(
                    resource_type="vpn_client",
                    resource_id=client_id,
                    resource_data=current,
                    resource_name=current.get("name", client_id),
                    warnings=["Deleting the client removes its tunnel configuration and may interrupt routed traffic"],
                ),
                redact_sensitive=redact_sensitive,
            )

        success = await vpn_manager.delete_vpn_client(client_id)
        if success:
            return {"success": True, "client_id": client_id, "message": f"VPN client '{client_id}' deleted."}
        return {"success": False, "error": f"Failed to delete VPN client '{client_id}'."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting VPN client %s: %s", client_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete VPN client {client_id}: {e}"}


@server.tool(
    name="unifi_list_vpn_servers",
    description="List all configured VPN servers (Wireguard, OpenVPN, L2TP, etc).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_vpn_servers() -> Dict[str, Any]:
    """Implementation for listing VPN servers."""
    redact_sensitive = should_redact_sensitive_fields()
    try:
        servers = await vpn_manager.get_vpn_servers()
        return redact_sensitive_fields(
            {
                "success": True,
                "site": vpn_manager._connection.site,
                "count": len(servers),
                "vpn_servers": [{**record, **alternate_address_view(record)} for record in servers],
            },
            redact_sensitive=redact_sensitive,
        )
    except Exception as e:
        logger.error("Error listing VPN servers: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list VPN servers: {e}"}


@server.tool(
    name="unifi_get_vpn_server_details",
    description="Get details for a specific VPN server by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_vpn_server_details(
    server_id: Annotated[
        str, Field(description="Unique identifier (_id) of the VPN server (from unifi_list_vpn_servers)")
    ],
) -> Dict[str, Any]:
    """Implementation for getting VPN server details."""
    redact_sensitive = should_redact_sensitive_fields()
    try:
        server = await vpn_manager.get_vpn_server_details(server_id)
        return redact_sensitive_fields(
            {
                "success": True,
                "site": vpn_manager._connection.site,
                "server_id": server_id,
                "details": {**server, **alternate_address_view(server)},
            },
            redact_sensitive=redact_sensitive,
        )
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting VPN server details for %s: %s", server_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get VPN server details for {server_id}: {e}"}


@server.tool(
    name="unifi_update_vpn_server_state",
    description="Enable or disable a specific VPN server by ID. Requires confirmation.",
    permission_category="vpn_servers",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_vpn_server_state(
    server_id: Annotated[
        str, Field(description="Unique identifier (_id) of the VPN server to update (from unifi_list_vpn_servers)")
    ],
    enabled: Annotated[bool, Field(description="Set to true to enable the VPN server, false to disable it")],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the state change. When false (default), returns a live-state preview"),
    ] = False,
) -> Dict[str, Any]:
    """Preview or update a VPN server's enabled state."""
    redact_sensitive = should_redact_sensitive_fields()
    try:
        current = await vpn_manager.get_vpn_server_details(server_id)
        if not confirm:
            return redact_sensitive_fields(
                update_preview(
                    resource_type="vpn_server",
                    resource_id=server_id,
                    resource_name=current.get("name", server_id),
                    current_state=current,
                    updates={"enabled": enabled},
                ),
                redact_sensitive=redact_sensitive,
            )

        write_result = await vpn_manager.update_vpn_server_state(server_id, enabled)
        payload = format_tool_payload(
            write_result,
            site=vpn_manager._connection.site,
            success_message=f"VPN server '{server_id}' {'enabled' if enabled else 'disabled'}.",
        )
        payload["server_id"] = server_id
        if not write_result.success:
            payload["error"] = f"Failed to update state for VPN server {server_id}: {write_result.error}"
        return redact_sensitive_fields(payload, redact_sensitive=redact_sensitive)
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating state for VPN server %s: %s", server_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update state for VPN server {server_id}: {e}"}


_TELEPORT_CLIENT_WARNING = (
    "Teleport clients that are already registered keep the address the controller recorded for them; "
    "whether they move into the new range on their next connection depends on the controller. "
    "Re-invite a client if it keeps its old address. Firewall rules or allow-lists that name the "
    "old range need the new one."
)


@server.tool(
    name="unifi_get_teleport_settings",
    auth="local_only",
    description=(
        "Get the site's Teleport VPN settings: whether Teleport is enabled and its client address range "
        "(subnet_cidr, gateway-address form such as '192.168.2.1/24'). The UniFi UI does not show the range; "
        "the gateway picks it when Teleport is first enabled."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_teleport_settings() -> Dict[str, Any]:
    """Read the Teleport site setting through the Core manager."""
    try:
        settings = await vpn_manager.get_teleport_settings()
        return {"success": True, "site": vpn_manager._connection.site, "teleport_settings": settings.model_dump()}
    except Exception as exc:
        logger.error("Failed to get Teleport settings: %s", type(exc).__name__)
        return {"success": False, "error": "Failed to get Teleport settings"}


@server.tool(
    name="unifi_update_teleport_settings",
    auth="local_only",
    description=(
        "Change the Teleport VPN client address range (subnet_cidr), for example to move it off a range that "
        "collides with networks remote clients visit. Pass only the fields you want to change — current values "
        "are automatically preserved; subnet_cidr is the only writable field. The value is a private IPv4 gateway "
        "address with prefix length (e.g. '10.201.0.1/24', /16 to /29); a range that overlaps any configured "
        "network is refused. Teleport stays enabled or disabled as it was. Already-registered clients keep their "
        "recorded addresses and may need re-inviting. Requires Network session authentication and confirmation; "
        "verifies persistence after applying."
    ),
    permission_category="vpn_servers",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_teleport_settings(
    subnet_cidr: Annotated[
        str,
        Field(description="New Teleport client range as a gateway address with prefix length, e.g. '10.201.0.1/24'"),
    ],
    confirm: Annotated[
        bool, Field(description="Apply when true; otherwise return a live before/after preview")
    ] = False,
) -> Dict[str, Any]:
    """Preview or apply a Teleport range change through the Core manager."""
    update_data = {"subnet_cidr": subnet_cidr}
    try:
        if not confirm:
            current, updates, conflicts = await vpn_manager.prepare_teleport_settings_update(update_data)
            if conflicts:
                return {
                    "success": False,
                    "error": f"Teleport range overlaps configured network(s): {', '.join(conflicts)}",
                }
            return update_preview(
                resource_type="teleport_settings",
                resource_id=current.get("id") or "teleport",
                resource_name="Teleport Settings",
                current_state=current,
                updates=updates,
                warnings=[_TELEPORT_CLIENT_WARNING],
            )
        result = await vpn_manager.update_teleport_settings(update_data)
        payload = format_tool_payload(
            result, site=vpn_manager._connection.site, success_message="Teleport range updated and verified."
        )
        if result.success and result.mutation_applied:
            payload["warnings"] = [_TELEPORT_CLIENT_WARNING]
        return payload
    except ValueError as exc:
        # Validation messages name the broken rule, never the submitted value.
        return {"success": False, "error": f"Failed to update Teleport settings: {exc}"}
    except Exception as exc:
        logger.error("Failed to update Teleport settings: %s", type(exc).__name__)
        return {
            "success": False,
            "error": "Failed to update Teleport settings: check session authentication and that Teleport has been "
            "enabled once on this site",
        }
