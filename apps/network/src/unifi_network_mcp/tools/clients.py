"""
Unifi Network MCP client management tools.

This module provides MCP tools to manage network clients/devices on a Unifi Network Controller.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import toggle_preview, update_preview
from unifi_core.network.models._actions import (
    AuthorizeGuestInput,
    BlockClientInput,
    ForceReconnectClientInput,
    ForgetClientInput,
    RenameClientInput,
    SetClientIpSettingsInput,
    UnauthorizeGuestInput,
    UnblockClientInput,
)
from unifi_core.network.models.clients import blocked_client_from_controller, client_lookup_from_controller
from unifi_core.network.read_views import shape_client_details, shape_client_list

# Import the global FastMCP server instance, config, and managers
from unifi_mcp_shared.argument_aliases import mac_aliases
from unifi_network_mcp.runtime import client_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="unifi_lookup_by_ip",
    description="Quick IP-to-client lookup. Returns essential fields (hostname, name, mac, is_online, last_seen) to minimize token usage.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def lookup_by_ip(
    ip_address: Annotated[str, Field(description="IPv4 address to look up (e.g., '192.168.1.100')")],
) -> Dict[str, Any]:
    """Lookup client by IP address - returns only essential fields to minimize token usage.

    Args:
        ip_address: IPv4 address to search for (e.g. '192.168.1.100').
    """
    try:
        client_obj = await client_manager.get_client_by_ip(ip_address)
        if client_obj:
            shaped = client_lookup_from_controller(client_obj)
            result = shaped.model_dump(exclude_none=True)
            return {
                "success": True,
                "site": client_manager._connection.site,
                **result,
            }
        return {
            "success": False,
            "error": f"No client found with IP: {ip_address}",
        }
    except Exception as e:
        logger.error("Error looking up client by IP [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to look up client by IP {ip_address}: {e}"}


@server.tool(
    name="unifi_list_clients",
    description=(
        "Returns connected clients with mac, name, hostname, ip, status (online/offline), "
        "connection type (wired/wireless), and for wireless clients: ssid, signal_dbm, "
        "channel, radio. Filter by filter_type (all/wired/wireless), set "
        "include_offline=true for historical clients. Use search to filter by "
        "name/hostname/IP/MAC (case-insensitive). For a single client's full raw "
        "object, use unifi_get_client_details. For IP-to-client lookup, use "
        "unifi_lookup_by_ip."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_clients(
    filter_type: Annotated[
        str, Field(description="Filter clients by connection type: 'all' (default), 'wired', or 'wireless'")
    ] = "all",
    include_offline: Annotated[
        bool,
        Field(description="When true, includes offline/disconnected clients from controller history. Default false"),
    ] = False,
    search: Annotated[
        Optional[str],
        Field(description="Filter by name, hostname, IP, or MAC (case-insensitive substring match)"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of clients to return (default 100)")] = 100,
    fields: Annotated[
        Optional[str],
        Field(
            description=(
                "Comma-separated list of fields to return per client (default: all). "
                "Available: mac, name, hostname, ip, connection_type, status, last_seen, _id. "
                "Wireless-only: essid, signal_dbm, channel, radio. "
                "Example: fields='mac,name,ip' returns only those 3 fields."
            )
        ),
    ] = None,
) -> Dict[str, Any]:
    """Implementation for listing clients."""
    try:
        clients = await client_manager.get_clients(include_offline=include_offline)
        return shape_client_list(
            clients,
            site=client_manager._connection.site,
            filter_type=filter_type,
            search=search,
            limit=limit,
            fields=fields,
        )
    except Exception as e:
        logger.error("Error listing clients: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to list clients: {e}"}


@server.tool(
    name="unifi_get_client_details",
    argument_aliases=mac_aliases("mac_address"),
    description=(
        "Returns client data for one client by MAC address. By default (summary=false) "
        "returns the full raw client object — all controller-reported fields, with the "
        "typed/normalized shape (ISO timestamps, derived status, null-safe name/hostname) "
        "layered on top of the merged live /stat/sta + /rest/user data. Set summary=true to "
        "trim to selected sections via include (basic, network, wireless, traffic, "
        "fingerprint, all). For a summary of all clients, use unifi_list_clients."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_client_details(
    mac_address: Annotated[
        str, Field(description="Client MAC address in format AA:BB:CC:DD:EE:FF (from unifi_list_clients)")
    ],
    include: Annotated[
        str,
        Field(
            description=(
                "Comma-separated sections to return when summary=true (default 'basic'). "
                "Sections: basic, network, wireless, traffic, fingerprint, all."
            )
        ),
    ] = "basic",
    summary: Annotated[
        bool,
        Field(
            description=(
                "When false (default), returns the full raw client object. "
                "When true, trims the response to the sections named in include."
            )
        ),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for getting client details."""
    try:
        client_obj = await client_manager.get_client_details(mac_address)
        return shape_client_details(
            client_obj,
            site=client_manager._connection.site,
            mac_address=mac_address,
            include=include,
            summary=summary,
        )
    except Exception as e:
        logger.error("Error getting client details for [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to get client details for {mac_address}: {e}"}


@server.tool(
    name="unifi_list_blocked_clients",
    description="Lists clients/devices currently blocked from the network. Each entry includes mac, hostname, name, last_seen, blocked.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_blocked_clients() -> Dict[str, Any]:
    """Implementation for listing blocked clients."""
    try:
        clients = await client_manager.get_blocked_clients()

        formatted_clients = []
        for c in clients:
            shaped = blocked_client_from_controller(c)
            formatted_clients.append(shaped.model_dump(exclude_none=True))

        return {
            "success": True,
            "site": client_manager._connection.site,
            "count": len(formatted_clients),
            "blocked_clients": formatted_clients,
        }
    except Exception as e:
        logger.error("Error listing blocked clients: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to list blocked clients: {e}"}


@server.tool(
    name="unifi_block_client",
    argument_aliases=mac_aliases("mac_address"),
    description="Block a client/device from the network by MAC address",
    permission_category="clients",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def block_client(
    mac_address: Annotated[
        str,
        Field(description="MAC address of the client to block, in format AA:BB:CC:DD:EE:FF (from unifi_list_clients)"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the block. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for blocking a client."""
    try:
        BlockClientInput(mac_address=mac_address)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    try:
        # Fetch client details first
        client_obj = await client_manager.get_client_details(mac_address)
        if not client_obj:
            return {
                "success": False,
                "error": f"Client not found with MAC address: {mac_address}",
            }

        client = client_obj.raw if hasattr(client_obj, "raw") else client_obj
        client_name = client.get("name") or client.get("hostname", "Unknown")
        is_blocked = client.get("blocked", False)

        # Return preview when confirm=false
        if not confirm:
            return toggle_preview(
                resource_type="client",
                resource_id=mac_address,
                resource_name=client_name,
                current_enabled=not is_blocked,  # enabled = not blocked
                additional_info={
                    "ip": client.get("ip"),
                    "hostname": client.get("hostname"),
                    "action": "block",
                },
            )

        success = await client_manager.block_client(mac_address)
        if success:
            return {
                "success": True,
                "message": f"Client {mac_address} blocked successfully.",
            }
        return {"success": False, "error": f"Failed to block client {mac_address}."}
    except Exception as e:
        logger.error("Error blocking client [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to block client {mac_address}: {e}"}


@server.tool(
    name="unifi_unblock_client",
    argument_aliases=mac_aliases("mac_address"),
    description="Unblock a previously blocked client/device by MAC address",
    permission_category="clients",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def unblock_client(
    mac_address: Annotated[
        str,
        Field(
            description="MAC address of the client to unblock, in format AA:BB:CC:DD:EE:FF (from unifi_list_blocked_clients)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the unblock. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for unblocking a client."""
    try:
        UnblockClientInput(mac_address=mac_address)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    try:
        # Fetch client details first
        client_obj = await client_manager.get_client_details(mac_address)
        if not client_obj:
            return {
                "success": False,
                "error": f"Client not found with MAC address: {mac_address}",
            }

        client = client_obj.raw if hasattr(client_obj, "raw") else client_obj
        client_name = client.get("name") or client.get("hostname", "Unknown")
        is_blocked = client.get("blocked", False)

        # Return preview when confirm=false
        if not confirm:
            return toggle_preview(
                resource_type="client",
                resource_id=mac_address,
                resource_name=client_name,
                current_enabled=not is_blocked,  # enabled = not blocked
                additional_info={
                    "ip": client.get("ip"),
                    "hostname": client.get("hostname"),
                    "action": "unblock",
                },
            )

        success = await client_manager.unblock_client(mac_address)
        if success:
            return {
                "success": True,
                "message": f"Client {mac_address} unblocked successfully.",
            }
        return {"success": False, "error": f"Failed to unblock client {mac_address}."}
    except Exception as e:
        logger.error("Error unblocking client [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to unblock client {mac_address}: {e}"}


@server.tool(
    name="unifi_rename_client",
    argument_aliases=mac_aliases("mac_address"),
    description="Rename a client/device in the Unifi Network controller by MAC address",
    permission_category="clients",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def rename_client(
    mac_address: Annotated[
        str,
        Field(description="MAC address of the client to rename, in format AA:BB:CC:DD:EE:FF (from unifi_list_clients)"),
    ],
    name: Annotated[str, Field(description="New display name for the client (e.g., 'Living Room TV')")],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the rename. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for renaming a client."""
    try:
        RenameClientInput(mac_address=mac_address, name=name)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    try:
        # Fetch client details first
        client_obj = await client_manager.get_client_details(mac_address)
        if not client_obj:
            return {
                "success": False,
                "error": f"Client not found with MAC address: {mac_address}",
            }

        client = client_obj.raw if hasattr(client_obj, "raw") else client_obj
        current_name = client.get("name") or client.get("hostname", "Unknown")

        # Return preview when confirm=false
        if not confirm:
            return update_preview(
                resource_type="client",
                resource_id=mac_address,
                resource_name=current_name,
                current_state={"name": current_name},
                updates={"name": name},
            )

        success = await client_manager.rename_client(mac_address, name)
        if success:
            return {
                "success": True,
                "message": f"Client {mac_address} renamed to '{name}' successfully.",
            }
        return {"success": False, "error": f"Failed to rename client {mac_address}."}
    except Exception as e:
        logger.error("Error renaming client [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to rename client {mac_address}: {e}"}


@server.tool(
    name="unifi_force_reconnect_client",
    argument_aliases=mac_aliases("mac_address"),
    description="Force a client to reconnect to the network (kick) by MAC address",
    permission_category="clients",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
)
async def force_reconnect_client(
    mac_address: Annotated[
        str,
        Field(
            description="MAC address of the client to force reconnect, in format AA:BB:CC:DD:EE:FF (from unifi_list_clients)"
        ),
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, executes the forced reconnect. When false (default), returns a preview of the changes"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for forcing a client to reconnect."""
    try:
        ForceReconnectClientInput(mac_address=mac_address)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    try:
        # Fetch client details first
        client_obj = await client_manager.get_client_details(mac_address)
        if not client_obj:
            return {
                "success": False,
                "error": f"Client not found with MAC address: {mac_address}",
            }

        client = client_obj.raw if hasattr(client_obj, "raw") else client_obj
        client_name = client.get("name") or client.get("hostname", "Unknown")

        # Return preview when confirm=false
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "force_reconnect",
                "resource_type": "client",
                "resource_id": mac_address,
                "resource_name": client_name,
                "preview": {
                    "current": {
                        "ip": client.get("ip"),
                        "hostname": client.get("hostname"),
                        "connection_type": "Wired" if client.get("is_wired") else "Wireless",
                    },
                    "action": "Client will be disconnected and forced to reconnect",
                },
                "message": f"Will force reconnect for client '{client_name}'. Set confirm=true to execute.",
            }

        success = await client_manager.force_reconnect_client(mac_address)
        if success:
            return {
                "success": True,
                "message": f"Client {mac_address} reconnection forced successfully.",
            }
        return {
            "success": False,
            "error": f"Failed to force reconnect for client {mac_address}.",
        }
    except Exception as e:
        logger.error("Error forcing reconnect for client [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to force reconnect for client {mac_address}: {e}"}


@server.tool(
    name="unifi_forget_client",
    argument_aliases=mac_aliases("mac_address"),
    description="Remove/forget a client from the controller's known client history by MAC address. This permanently deletes the client record including its name, notes, fixed IP settings, and historical stats. The client will reappear as a new unknown device if it reconnects.",
    permission_category="clients",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def forget_client(
    mac_address: Annotated[
        str,
        Field(description="MAC address of the client to forget, in format AA:BB:CC:DD:EE:FF (from unifi_list_clients)"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the forget. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for forgetting/removing a client from the controller."""
    try:
        ForgetClientInput(mac_address=mac_address)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    try:
        # Fetch client details first
        client_obj = await client_manager.get_client_details(mac_address)
        if not client_obj:
            return {
                "success": False,
                "error": f"Client not found with MAC address: {mac_address}",
            }

        client = client_obj.raw if hasattr(client_obj, "raw") else client_obj
        client_name = client.get("name") or client.get("hostname", "Unknown")

        # Return preview when confirm=false
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "forget_client",
                "resource_type": "client",
                "resource_id": mac_address,
                "resource_name": client_name,
                "preview": {
                    "current": {
                        "ip": client.get("ip"),
                        "hostname": client.get("hostname"),
                        "connection_type": "Wired" if client.get("is_wired") else "Wireless",
                    },
                    "action": "Client will be permanently removed from controller history. Name, notes, fixed IP settings, and historical stats will be deleted.",
                },
                "message": f"Will forget client '{client_name}' ({mac_address}). Set confirm=true to execute.",
            }

        success = await client_manager.forget_client(mac_address)
        if success:
            return {
                "success": True,
                "message": f"Client {mac_address} ('{client_name}') forgotten successfully.",
            }
        return {"success": False, "error": f"Failed to forget client {mac_address}."}
    except Exception as e:
        logger.error("Error forgetting client [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to forget client {mac_address}: {e}"}


@server.tool(
    name="unifi_authorize_guest",
    argument_aliases=mac_aliases("mac_address"),
    description="Authorize a guest client to access the guest network by MAC address",
    permission_category="clients",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def authorize_guest(
    mac_address: Annotated[
        str,
        Field(description="MAC address of the guest client to authorize, in format AA:BB:CC:DD:EE:FF"),
    ],
    minutes: Annotated[
        int, Field(description="Duration in minutes the guest is authorized (default 1440 = 24 hours)")
    ] = 1440,
    up_kbps: Annotated[
        Optional[int], Field(description="Upload bandwidth limit in Kbps (e.g., 5000 for 5 Mbps). Omit for unlimited")
    ] = None,
    down_kbps: Annotated[
        Optional[int],
        Field(description="Download bandwidth limit in Kbps (e.g., 10000 for 10 Mbps). Omit for unlimited"),
    ] = None,
    bytes_quota: Annotated[
        Optional[int], Field(description="Total data transfer quota in bytes. Omit for unlimited")
    ] = None,
    confirm: Annotated[
        bool,
        Field(
            description="When true, executes the authorization. When false (default), returns a preview of the changes"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for authorizing a guest."""
    try:
        AuthorizeGuestInput(
            mac_address=mac_address,
            minutes=minutes,
            up_kbps=up_kbps,
            down_kbps=down_kbps,
            bytes_quota=bytes_quota,
        )
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    try:
        # Fetch client details first
        client_obj = await client_manager.get_client_details(mac_address)
        if not client_obj:
            return {
                "success": False,
                "error": f"Client not found with MAC address: {mac_address}",
            }

        client = client_obj.raw if hasattr(client_obj, "raw") else client_obj
        client_name = client.get("name") or client.get("hostname", "Unknown")

        # Return preview when confirm=false
        if not confirm:
            settings = {"minutes": minutes}
            if up_kbps is not None:
                settings["up_kbps"] = up_kbps
            if down_kbps is not None:
                settings["down_kbps"] = down_kbps
            if bytes_quota is not None:
                settings["bytes_quota"] = bytes_quota

            return {
                "success": True,
                "requires_confirmation": True,
                "action": "authorize_guest",
                "resource_type": "client",
                "resource_id": mac_address,
                "resource_name": client_name,
                "preview": {
                    "current": {
                        "ip": client.get("ip"),
                        "hostname": client.get("hostname"),
                    },
                    "proposed": settings,
                },
                "message": f"Will authorize guest '{client_name}' for {minutes} minutes. Set confirm=true to execute.",
            }

        success = await client_manager.authorize_guest(mac_address, minutes, up_kbps, down_kbps, bytes_quota)
        if success:
            return {
                "success": True,
                "message": f"Guest {mac_address} authorized successfully for {minutes} minutes.",
            }
        return {"success": False, "error": f"Failed to authorize guest {mac_address}."}
    except Exception as e:
        logger.error("Error authorizing guest [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to authorize guest {mac_address}: {e}"}


@server.tool(
    name="unifi_unauthorize_guest",
    argument_aliases=mac_aliases("mac_address"),
    description="Revoke authorization for a guest client by MAC address",
    permission_category="clients",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def unauthorize_guest(
    mac_address: Annotated[
        str,
        Field(description="MAC address of the guest client to unauthorize, in format AA:BB:CC:DD:EE:FF"),
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, revokes guest authorization. When false (default), returns a preview of the changes"
        ),
    ] = False,
) -> Dict[str, Any]:
    """Implementation for unauthorizing a guest."""
    try:
        UnauthorizeGuestInput(mac_address=mac_address)
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    try:
        # Fetch client details first
        client_obj = await client_manager.get_client_details(mac_address)
        if not client_obj:
            return {
                "success": False,
                "error": f"Client not found with MAC address: {mac_address}",
            }

        client = client_obj.raw if hasattr(client_obj, "raw") else client_obj
        client_name = client.get("name") or client.get("hostname", "Unknown")

        # Return preview when confirm=false
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "unauthorize_guest",
                "resource_type": "client",
                "resource_id": mac_address,
                "resource_name": client_name,
                "preview": {
                    "current": {
                        "ip": client.get("ip"),
                        "hostname": client.get("hostname"),
                    },
                    "action": "Guest authorization will be revoked",
                },
                "message": f"Will revoke guest authorization for '{client_name}'. Set confirm=true to execute.",
            }

        success = await client_manager.unauthorize_guest(mac_address)
        if success:
            return {
                "success": True,
                "message": f"Guest {mac_address} authorization revoked successfully.",
            }
        return {
            "success": False,
            "error": f"Failed to unauthorize guest {mac_address}.",
        }
    except Exception as e:
        logger.error("Error unauthorizing guest [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to unauthorize guest {mac_address}: {e}"}


@server.tool(
    name="unifi_set_client_ip_settings",
    argument_aliases=mac_aliases("mac_address"),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    description="""Set fixed IP address and/or local DNS record for a client device.

Allows configuring:
- Fixed IP: Assign a static IP address to a client (DHCP reservation)
- Local DNS: Create a local DNS hostname for the client (UniFi Network 7.2+)

Either setting can be enabled/disabled independently.""",
    permission_category="clients",
    permission_action="update",
)
async def set_client_ip_settings(
    mac_address: Annotated[
        str,
        Field(
            description="MAC address of the client to configure, in format AA:BB:CC:DD:EE:FF (from unifi_list_clients)"
        ),
    ],
    use_fixedip: Annotated[
        Optional[bool],
        Field(description="Enable (true) or disable (false) fixed IP / DHCP reservation for this client"),
    ] = None,
    fixed_ip: Annotated[
        Optional[str],
        Field(description="Static IP address to assign (e.g., '192.168.1.50'). Only used when use_fixedip is true"),
    ] = None,
    local_dns_record_enabled: Annotated[
        Optional[bool],
        Field(description="Enable (true) or disable (false) local DNS record for this client (UniFi Network 7.2+)"),
    ] = None,
    local_dns_record: Annotated[
        Optional[str],
        Field(
            description="Local DNS hostname for this client (e.g., 'mydevice.local'). Only used when local_dns_record_enabled is true"
        ),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, applies the IP settings. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Set fixed IP and/or local DNS record for a client."""
    try:
        SetClientIpSettingsInput(
            mac_address=mac_address,
            use_fixedip=use_fixedip,
            fixed_ip=fixed_ip,
            local_dns_record_enabled=local_dns_record_enabled,
            local_dns_record=local_dns_record,
        )
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

    # Validate that at least one setting is provided
    if all(v is None for v in [use_fixedip, fixed_ip, local_dns_record_enabled, local_dns_record]):
        return {
            "success": False,
            "error": "At least one setting must be provided (use_fixedip, fixed_ip, local_dns_record_enabled, or local_dns_record).",
        }

    try:
        # Fetch client details first
        client_obj = await client_manager.get_client_details(mac_address)
        if not client_obj:
            return {
                "success": False,
                "error": f"Client not found with MAC address: {mac_address}",
            }

        client = client_obj.raw if hasattr(client_obj, "raw") else client_obj
        client_name = client.get("name") or client.get("hostname", "Unknown")

        # Return preview when confirm=false
        if not confirm:
            # Build current state from the client object
            current_state = {
                "use_fixedip": client.get("use_fixedip", False),
                "fixed_ip": client.get("fixed_ip"),
                "local_dns_record_enabled": client.get("local_dns_record_enabled", False),
                "local_dns_record": client.get("local_dns_record"),
            }

            # Build updates dict with only provided values
            updates = {}
            if use_fixedip is not None:
                updates["use_fixedip"] = use_fixedip
            if fixed_ip is not None:
                updates["fixed_ip"] = fixed_ip
            if local_dns_record_enabled is not None:
                updates["local_dns_record_enabled"] = local_dns_record_enabled
            if local_dns_record is not None:
                updates["local_dns_record"] = local_dns_record

            return update_preview(
                resource_type="client",
                resource_id=mac_address,
                resource_name=client_name,
                current_state=current_state,
                updates=updates,
            )

        success = await client_manager.set_client_ip_settings(
            client_mac=mac_address,
            use_fixedip=use_fixedip,
            fixed_ip=fixed_ip,
            local_dns_record_enabled=local_dns_record_enabled,
            local_dns_record=local_dns_record,
        )
        if success:
            return {
                "success": True,
                "message": f"IP settings updated for client {mac_address}.",
                "settings": {
                    k: v
                    for k, v in {
                        "use_fixedip": use_fixedip,
                        "fixed_ip": fixed_ip,
                        "local_dns_record_enabled": local_dns_record_enabled,
                        "local_dns_record": local_dns_record,
                    }.items()
                    if v is not None
                },
            }
        return {
            "success": False,
            "error": f"Failed to update IP settings for client {mac_address}.",
        }
    except Exception as e:
        logger.error("Error setting IP settings for [redacted]: %s", type(e).__name__)
        return {"success": False, "error": f"Failed to set IP settings for client {mac_address}: {e}"}
