"""
UniFi Network MCP static routing tools.

This module provides MCP tools to manage static routes on a UniFi Network Controller.
"""

import logging
import re
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.models.route import (
    active_route_from_controller,
    route_from_controller,
)
from unifi_network_mcp.runtime import routing_manager, server

logger = logging.getLogger(__name__)


def _validate_cidr(network: str) -> bool:
    """Validate a CIDR network notation."""
    pattern = r"^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$"
    if not re.match(pattern, network):
        return False
    parts = network.split("/")
    ip_parts = parts[0].split(".")
    prefix = int(parts[1])
    return all(0 <= int(p) <= 255 for p in ip_parts) and 0 <= prefix <= 32


def _validate_ip(ip: str) -> bool:
    """Validate an IP address."""
    pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
    if not re.match(pattern, ip):
        return False
    return all(0 <= int(p) <= 255 for p in ip.split("."))


@server.tool(
    name="unifi_list_routes",
    description="""List all user-defined static routes for the current site.

Returns route names, destination networks, next-hop addresses, and status.
These are manually configured routes, not dynamic or system routes.""",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_routes() -> Dict[str, Any]:
    """List all user-defined static routes."""
    try:
        routes = await routing_manager.get_routes()
        shaped = [route_from_controller(r).model_dump(exclude_none=False) for r in routes]
        return {
            "success": True,
            "site": routing_manager._connection.site,
            "count": len(shaped),
            "routes": shaped,
        }
    except Exception as e:
        logger.error("Error listing routes: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list routes: {e}"}


@server.tool(
    name="unifi_list_active_routes",
    description="""List all active routes from the device routing table.

Includes both user-defined and system routes currently in effect.
This shows the actual routing table state on the gateway device.

Note: This endpoint may not be available on all controller versions.
Returns empty list if unavailable.""",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_active_routes() -> Dict[str, Any]:
    """List all active routes from the routing table."""
    try:
        routes = await routing_manager.get_active_routes()
        shaped = [active_route_from_controller(r).model_dump(exclude_none=False) for r in routes]
        return {
            "success": True,
            "site": routing_manager._connection.site,
            "count": len(shaped),
            "active_routes": shaped,
        }
    except Exception as e:
        logger.error("Error listing active routes: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list active routes: {e}"}


@server.tool(
    name="unifi_get_route_details",
    description="Get detailed information about a specific static route by its ID",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_route_details(
    route_id: Annotated[str, Field(description="Unique identifier (_id) of the static route (from unifi_list_routes)")],
) -> Dict[str, Any]:
    """Get details for a specific route."""
    try:
        route = await routing_manager.get_route_details(route_id)
        return {
            "success": True,
            "site": routing_manager._connection.site,
            "route": route,
        }
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting route details for %s: %s", route_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get route details for {route_id}: {e}"}


@server.tool(
    name="unifi_create_route",
    description="""Create a new static route for advanced routing configuration.

Specify destination network in CIDR format (e.g., "10.0.0.0/24") and
next-hop IP address (e.g., "192.168.1.1").""",
    permission_category="routes",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_route(
    name: Annotated[str, Field(description="Descriptive name for the static route (e.g., 'Office subnet via VPN')")],
    network: Annotated[
        str, Field(description="Destination network in CIDR notation (e.g., '10.0.0.0/24', '172.16.0.0/16')")
    ],
    nexthop: Annotated[str, Field(description="Next-hop gateway IP address (e.g., '192.168.1.1')")],
    distance: Annotated[
        int, Field(description="Administrative distance / route metric (1-255, default 1, lower = preferred)")
    ] = 1,
    enabled: Annotated[bool, Field(description="Whether the route is active (default true)")] = True,
    confirm: Annotated[
        bool,
        Field(description="When true, creates the route. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Create a new static route."""
    if not name or not name.strip():
        return {"success": False, "error": "Name is required."}

    if not _validate_cidr(network):
        return {
            "success": False,
            "error": f"Invalid network format: {network}. Use CIDR notation (e.g., 10.0.0.0/24).",
        }

    if not _validate_ip(nexthop):
        return {
            "success": False,
            "error": f"Invalid nexthop IP: {nexthop}. Use valid IP address.",
        }

    if distance < 1 or distance > 255:
        return {"success": False, "error": "Distance must be between 1 and 255."}

    if not confirm:
        return create_preview(
            resource_type="static_route",
            resource_data={
                "name": name.strip(),
                "network": network,
                "nexthop": nexthop,
                "distance": distance,
                "enabled": enabled,
            },
            resource_name=name.strip(),
        )

    try:
        route = await routing_manager.create_route(
            name=name.strip(),
            static_route_network=network,
            static_route_nexthop=nexthop,
            static_route_distance=distance,
            enabled=enabled,
        )

        if route:
            return {
                "success": True,
                "message": f"Route '{name}' created successfully.",
                "site": routing_manager._connection.site,
                "route": route,
            }
        return {"success": False, "error": "Failed to create route."}
    except Exception as e:
        logger.error("Error creating route: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create route: {e}"}


@server.tool(
    name="unifi_update_route",
    description="""Update an existing static route's properties.

Can modify name, destination network, next-hop, distance, or enabled status.""",
    permission_category="routes",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_route(
    route_id: Annotated[
        str, Field(description="Unique identifier (_id) of the static route to update (from unifi_list_routes)")
    ],
    name: Annotated[Optional[str], Field(description="New descriptive name for the route")] = None,
    network: Annotated[
        Optional[str], Field(description="New destination network in CIDR notation (e.g., '10.0.0.0/24')")
    ] = None,
    nexthop: Annotated[
        Optional[str], Field(description="New next-hop gateway IP address (e.g., '192.168.1.1')")
    ] = None,
    distance: Annotated[
        Optional[int], Field(description="New administrative distance (1-255, lower = preferred)")
    ] = None,
    enabled: Annotated[Optional[bool], Field(description="New enabled state (true/false)")] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Update an existing static route."""
    # Validate that at least one update is provided
    if all(v is None for v in [name, network, nexthop, distance, enabled]):
        return {
            "success": False,
            "error": "At least one field must be provided.",
        }

    # Validate formats if provided
    if network is not None and not _validate_cidr(network):
        return {
            "success": False,
            "error": f"Invalid network format: {network}. Use CIDR notation.",
        }

    if nexthop is not None and not _validate_ip(nexthop):
        return {
            "success": False,
            "error": f"Invalid nexthop IP: {nexthop}.",
        }

    if distance is not None and (distance < 1 or distance > 255):
        return {"success": False, "error": "Distance must be between 1 and 255."}

    updates = {
        k: v
        for k, v in {
            "name": name.strip() if name else None,
            "network": network,
            "nexthop": nexthop,
            "distance": distance,
            "enabled": enabled,
        }.items()
        if v is not None
    }

    if not confirm:
        return update_preview(
            resource_type="static_route",
            resource_id=route_id,
            resource_name=route_id,
            current_state={},
            updates=updates,
        )

    try:
        success = await routing_manager.update_route(
            route_id=route_id,
            name=name.strip() if name else None,
            static_route_network=network,
            static_route_nexthop=nexthop,
            static_route_distance=distance,
            enabled=enabled,
        )

        if success:
            return {
                "success": True,
                "message": f"Route {route_id} updated successfully.",
                "updates": updates,
            }
        return {"success": False, "error": f"Failed to update route {route_id}."}
    except UniFiNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating route %s: %s", route_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update route {route_id}: {e}"}
