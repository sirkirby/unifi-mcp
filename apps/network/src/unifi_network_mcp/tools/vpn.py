"""
VPN configuration tools for Unifi Network MCP server.

This module provides MCP tools to interact with a Unifi Network Controller's VPN functions,
including managing VPN clients and servers.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.redaction import redact_sensitive_fields
from unifi_network_mcp.runtime import server, should_redact_sensitive_fields, vpn_manager

logger = logging.getLogger(__name__)


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
    description="Enable or disable a specific VPN client by ID.",
    permission_category="vpn_clients",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_vpn_client_state(
    client_id: Annotated[
        str, Field(description="Unique identifier (_id) of the VPN client to update (from unifi_list_vpn_clients)")
    ],
    enabled: Annotated[bool, Field(description="Set to true to enable the VPN client, false to disable it")],
) -> Dict[str, Any]:
    """Implementation for updating VPN client state."""
    try:
        success = await vpn_manager.update_vpn_client_state(client_id, enabled)
        state = "enabled" if enabled else "disabled"
        if success:
            return {
                "success": True,
                "message": f"VPN client '{client_id}' {state}.",
            }
        return {
            "success": False,
            "error": f"Failed to update state for VPN client '{client_id}'.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating state for VPN client %s: %s", client_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update state for VPN client {client_id}: {e}"}


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
                "vpn_servers": servers,
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
                "details": server,
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
    description="Enable or disable a specific VPN server by ID.",
    permission_category="vpn_servers",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_vpn_server_state(
    server_id: Annotated[
        str, Field(description="Unique identifier (_id) of the VPN server to update (from unifi_list_vpn_servers)")
    ],
    enabled: Annotated[bool, Field(description="Set to true to enable the VPN server, false to disable it")],
) -> Dict[str, Any]:
    """Implementation for updating VPN server state."""
    try:
        success = await vpn_manager.update_vpn_server_state(server_id, enabled)
        state = "enabled" if enabled else "disabled"
        if success:
            return {
                "success": True,
                "message": f"VPN server '{server_id}' {state}.",
            }
        return {
            "success": False,
            "error": f"Failed to update state for VPN server '{server_id}'.",
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating state for VPN server %s: %s", server_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update state for VPN server {server_id}: {e}"}
