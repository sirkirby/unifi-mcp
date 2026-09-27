"""
UniFi Network MCP traffic route tools.

This module provides MCP tools to manage traffic routes (policy-based routing)
on a UniFi Network Controller using the V2 API.
"""

import logging
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.confirmation import create_preview, toggle_preview, update_preview
from unifi_core.exceptions import UniFiAuthError, UniFiNotFoundError
from unifi_core.network.managers.traffic_route_manager import (
    TrafficRoutePreflightError,
    internet_route_requires_target_validation,
)
from unifi_core.network.models.traffic_routes import (
    TrafficRouteValidationError,
    from_controller,
    validate_create_payload,
    validate_update_fields,
)
from unifi_network_mcp.runtime import server, traffic_route_manager

logger = logging.getLogger(__name__)


async def _validate_internet_route_target(target_devices: Any, network_id: Any) -> Optional[Dict[str, Any]]:
    """Translate canonical manager validation failures for the MCP response contract."""
    try:
        await traffic_route_manager.validate_internet_route_target(target_devices, network_id)
    except UniFiNotFoundError:
        return {"success": False, "error": "Target network was not found."}
    except UniFiAuthError:
        return {
            "success": False,
            "error": (
                "INTERNET Traffic Routes require Network session authentication. "
                "Configure UNIFI_NETWORK_USERNAME and UNIFI_NETWORK_PASSWORD."
            ),
        }
    except TrafficRouteValidationError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Unable to verify INTERNET Traffic Route target (%s)", type(exc).__name__)
        return {"success": False, "error": "Unable to verify target network."}
    return None


@server.tool(
    name="unifi_create_traffic_route",
    description="""Create a narrowly scoped Traffic Route (policy-based route). Requires confirmation.

An explicit matching_target and target network/VPN are required. DOMAIN routes
require at least one domain. INTERNET routes are allowed only for one explicit
CLIENT with a valid unicast MAC address when the target is a verified WAN network.""",
    permission_category="traffic_routes",
    permission_action="create",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def create_traffic_route(
    name: Annotated[str, Field(description="Human-readable route name (maximum 128 characters)")],
    matching_target: Annotated[str, Field(description="Destination match type: DOMAIN, IP, REGION, or INTERNET")],
    network_id: Annotated[str, Field(description="Target network or VPN client ID")],
    domains: Annotated[
        Optional[List[Dict[str, Any]]], Field(description='DOMAIN entries, e.g. [{"domain": "youtube.com"}]')
    ] = None,
    ip_addresses: Annotated[Optional[List[Dict[str, Any]]], Field(description="IP route entries")] = None,
    ip_ranges: Annotated[Optional[List[Dict[str, Any]]], Field(description="IP-range route entries")] = None,
    regions: Annotated[Optional[List[str]], Field(description="REGION route country codes")] = None,
    target_devices: Annotated[
        Optional[List[Dict[str, Any]]], Field(description="Source targets: CLIENT, NETWORK, or ALL_CLIENTS")
    ] = None,
    kill_switch_enabled: Annotated[
        bool, Field(description="Block matched traffic if target VPN/network is unavailable")
    ] = False,
    enabled: Annotated[bool, Field(description="Create enabled")] = True,
    confirm: Annotated[bool, Field(description="When true, creates; when false, previews")] = False,
) -> Dict[str, Any]:
    """Create a validated V2 Traffic Route with an explicit confirmation gate."""
    payload = {
        "description": name,
        "matching_target": matching_target,
        "network_id": network_id,
        "domains": domains if domains is not None else [],
        "ip_addresses": ip_addresses if ip_addresses is not None else [],
        "ip_ranges": ip_ranges if ip_ranges is not None else [],
        "regions": regions if regions is not None else [],
        "kill_switch_enabled": kill_switch_enabled,
        "enabled": enabled,
        "next_hop": "",
    }
    if target_devices is not None:
        payload["target_devices"] = target_devices
    try:
        payload = validate_create_payload(payload)
    except TrafficRouteValidationError as exc:
        return {"success": False, "error": str(exc)}
    if target_devices is None and payload["matching_target"] in {"DOMAIN", "IP", "REGION"}:
        payload["target_devices"] = [{"type": "ALL_CLIENTS"}]
    if payload["matching_target"] == "INTERNET":
        validation_error = await _validate_internet_route_target(payload.get("target_devices"), payload["network_id"])
        if validation_error:
            return validation_error
    if not confirm:
        return create_preview("traffic_route", payload, name)
    try:
        created = await traffic_route_manager.create_traffic_route(payload)
        return {
            "success": True,
            "data": from_controller(created).model_dump(exclude_none=True),
            "message": f"Traffic route '{name}' created.",
        }
    except TrafficRoutePreflightError as exc:
        return {"success": False, "error": f"Failed to create traffic route: {exc}"}
    except Exception as e:
        logger.error("Traffic route create failed (%s)", type(e).__name__)
        return {
            "success": False,
            "error": (
                "Failed to create traffic route; it may have been created. "
                "List routes before retrying, then check controller connectivity and permissions."
            ),
        }


@server.tool(
    name="unifi_list_traffic_routes",
    description="""List all traffic routes (policy-based routing rules) for the current site.

Traffic routes define how specific traffic is routed based on domains,
IP addresses, regions, or target devices. Often used for VPN routing.""",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def list_traffic_routes() -> Dict[str, Any]:
    """List all traffic routes."""
    try:
        routes = await traffic_route_manager.get_traffic_routes()

        # Format routes for readability
        formatted_routes = []
        for r in routes:
            formatted = {
                "_id": r.get("_id"),
                "description": r.get("description"),
                "enabled": r.get("enabled", True),
                "network_id": r.get("network_id"),
                "next_hop": r.get("next_hop"),
                "matching_target": r.get("matching_target"),
                "kill_switch_enabled": r.get("kill_switch_enabled", False),
                "domains": len(r.get("domains", [])),
                "ip_addresses": len(r.get("ip_addresses", [])),
                "ip_ranges": len(r.get("ip_ranges", [])),
                "regions": len(r.get("regions", [])),
                "target_devices": len(r.get("target_devices", [])),
            }
            formatted_routes.append(formatted)

        return {
            "success": True,
            "site": traffic_route_manager._connection.site,
            "count": len(formatted_routes),
            "traffic_routes": formatted_routes,
        }
    except Exception as e:
        logger.error("Traffic route list failed (%s)", type(e).__name__)
        return {
            "success": False,
            "error": "Failed to list traffic routes. Check controller connectivity and permissions.",
        }


@server.tool(
    name="unifi_get_traffic_route_details",
    description="Get detailed information for a specific traffic route by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_traffic_route_details(
    route_id: Annotated[
        str,
        Field(description="Unique identifier (_id) of the traffic route (from unifi_list_traffic_routes)"),
    ],
) -> Dict[str, Any]:
    """Get details for a specific traffic route."""
    try:
        route = await traffic_route_manager.get_traffic_route_details(route_id)
        return {
            "success": True,
            "site": traffic_route_manager._connection.site,
            "route_id": route_id,
            "details": route,
        }
    except UniFiNotFoundError:
        return {"success": False, "error": "Traffic route was not found."}
    except Exception as e:
        logger.error("Traffic route detail lookup failed (%s)", type(e).__name__)
        return {
            "success": False,
            "error": "Failed to get traffic route details. Check controller connectivity and permissions.",
        }


@server.tool(
    name="unifi_update_traffic_route",
    description="""Update a traffic route's settings.

Pass only the fields you want to change — current values are automatically preserved.

Toggle fields:
- enabled: Enable or disable the traffic route
- kill_switch_enabled: Enable/disable the kill switch (blocks traffic if VPN is down)

Routing-match fields (each REPLACES the whole existing list/value — read the route
first with unifi_get_traffic_route_details, then send the full desired value):
- target_devices: Which clients/networks the route applies to. For INTERNET routes, this must remain one explicit CLIENT target.
  [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}],
  [{"type": "NETWORK", "network_id": "<id>"}], or [{"type": "ALL_CLIENTS"}].
- domains: List of domain objects, e.g. [{"domain": "example.com", "ports": [], "port_ranges": []}].
- ip_addresses: List of IP/subnet objects (for matching_target=IP routes).
- ip_ranges: List of IP-range objects.
- regions: List of ISO country/region codes, e.g. ["US", "CA"].
- network_id: Replace the target network/VPN. INTERNET routes require a verified WAN target.
- next_hop: Next-hop IP address (string) for static next-hop routes.

For INTERNET routes, a target update is allowed only when the resulting route still
has exactly one explicit CLIENT target with a valid unicast MAC address and a freshly
verified WAN target. Broad targets and non-WAN targets are rejected.

At least one field must be provided.""",
    permission_category="traffic_routes",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
async def update_traffic_route(
    route_id: Annotated[
        str,
        Field(description="Unique identifier (_id) of the traffic route to update (from unifi_list_traffic_routes)"),
    ],
    enabled: Annotated[Optional[bool], Field(description="Enable (true) or disable (false) the traffic route")] = None,
    kill_switch_enabled: Annotated[
        Optional[bool],
        Field(
            description="Enable (true) or disable (false) the kill switch, which blocks traffic if the VPN goes down"
        ),
    ] = None,
    target_devices: Annotated[
        Optional[List[Dict[str, Any]]],
        Field(
            description=(
                "Replace the route's target devices. List of objects, e.g. "
                '[{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}], '
                '[{"type": "NETWORK", "network_id": "<id>"}], or [{"type": "ALL_CLIENTS"}].'
            )
        ),
    ] = None,
    domains: Annotated[
        Optional[List[Dict[str, Any]]],
        Field(
            description=(
                "Replace the route's domains. List of objects, e.g. "
                '[{"domain": "example.com", "ports": [], "port_ranges": []}].'
            )
        ),
    ] = None,
    ip_addresses: Annotated[
        Optional[List[Dict[str, Any]]],
        Field(description="Replace the route's IP addresses/subnets (for matching_target=IP routes)."),
    ] = None,
    ip_ranges: Annotated[
        Optional[List[Dict[str, Any]]],
        Field(description="Replace the route's IP ranges."),
    ] = None,
    regions: Annotated[
        Optional[List[str]],
        Field(description='Replace the route\'s regions. List of ISO country/region codes, e.g. ["US", "CA"].'),
    ] = None,
    network_id: Annotated[
        Optional[str],
        Field(description="Replace the target network or VPN. INTERNET routes require a verified WAN network."),
    ] = None,
    next_hop: Annotated[
        Optional[str],
        Field(description="Next-hop IP address (string) for static next-hop routes."),
    ] = None,
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Update a traffic route's settings."""
    field_values: Dict[str, Any] = {
        "enabled": enabled,
        "kill_switch_enabled": kill_switch_enabled,
        "target_devices": target_devices,
        "domains": domains,
        "ip_addresses": ip_addresses,
        "ip_ranges": ip_ranges,
        "regions": regions,
        "network_id": network_id,
        "next_hop": next_hop,
    }
    updates: Dict[str, Any] = {k: v for k, v in field_values.items() if v is not None}

    if not updates:
        return {
            "success": False,
            "error": (
                "At least one updatable field must be provided: enabled, kill_switch_enabled, "
                "target_devices, domains, ip_addresses, ip_ranges, regions, network_id, next_hop."
            ),
        }

    # Validate list-shaped fields client-side before touching the controller.
    for field in ("target_devices", "domains", "ip_addresses", "ip_ranges", "regions"):
        if field in updates and not isinstance(updates[field], list):
            return {"success": False, "error": f"'{field}' must be a list."}
    for entry in updates.get("target_devices", []):
        if not isinstance(entry, dict) or "type" not in entry:
            return {
                "success": False,
                "error": (
                    "Each target_devices entry must be an object with a 'type', e.g. "
                    '{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}, '
                    '{"type": "NETWORK", "network_id": "<id>"}, or {"type": "ALL_CLIENTS"}.'
                ),
            }

    try:
        # Fetch current route so the preview can show what is being replaced.
        current = await traffic_route_manager.get_traffic_route_details(route_id)
        updates = validate_update_fields(updates, current=current)
        route_name = current.get("description", route_id)

        proposed = {**current, **updates}
        if internet_route_requires_target_validation(proposed, current):
            validation_error = await _validate_internet_route_target(
                proposed.get("target_devices"), proposed.get("network_id")
            )
            if validation_error:
                return validation_error

        if not confirm:
            return update_preview(
                resource_type="traffic_route",
                resource_id=route_id,
                resource_name=route_name,
                current_state=current,
                updates=updates,
            )

        success = await traffic_route_manager.update_traffic_route(route_id, **updates)
        if success:
            return {
                "success": True,
                "message": f"Traffic route '{route_name}' updated: {', '.join(sorted(updates.keys()))}.",
            }
        return {
            "success": False,
            "error": "Failed to update traffic route.",
        }
    except UniFiNotFoundError:
        return {"success": False, "error": "Traffic route was not found."}
    except (TrafficRouteValidationError, TrafficRoutePreflightError) as exc:
        return {"success": False, "error": f"Failed to update traffic route: {exc}"}
    except Exception as e:
        logger.error("Traffic route update failed (%s)", type(e).__name__)
        return {
            "success": False,
            "error": "Failed to update traffic route. Check controller connectivity and permissions.",
        }


@server.tool(
    name="unifi_toggle_traffic_route",
    description="""Toggle a traffic route on/off by ID.

Enabling an INTERNET route requires one explicit CLIENT target with a valid unicast MAC
address and a verified WAN network.""",
    permission_category="traffic_routes",
    permission_action="update",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
async def toggle_traffic_route(
    route_id: Annotated[
        str,
        Field(description="Unique identifier (_id) of the traffic route to toggle (from unifi_list_traffic_routes)"),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the toggle. When false (default), returns a preview of the changes"),
    ] = False,
) -> Dict[str, Any]:
    """Toggle a traffic route's enabled state."""
    try:
        # Use a fresh read for preview/message so the reported target state
        # corresponds to the controller state that will be toggled.
        current = await traffic_route_manager.get_traffic_route_details(route_id, force_refresh=True)
        if not current:
            return {"success": False, "error": "Traffic route was not found."}

        current_enabled = current.get("enabled", True)
        route_name = current.get("description", route_id)

        if not current_enabled and current.get("matching_target") == "INTERNET":
            validation_error = await _validate_internet_route_target(
                current.get("target_devices"), current.get("network_id")
            )
            if validation_error:
                return validation_error

        # Return preview when confirm=false
        if not confirm:
            return toggle_preview(
                resource_type="traffic_route",
                resource_id=route_id,
                resource_name=route_name,
                current_enabled=current_enabled,
                additional_info={
                    "network_id": current.get("network_id"),
                    "kill_switch_enabled": current.get("kill_switch_enabled"),
                },
            )

        success = await traffic_route_manager.toggle_traffic_route(route_id)

        if success:
            return {
                "success": True,
                "message": f"Traffic route '{route_name}' toggle submitted. Read route details to confirm its current state.",
            }
        else:
            return {
                "success": False,
                "error": "Failed to toggle traffic route.",
            }
    except UniFiNotFoundError:
        return {"success": False, "error": "Traffic route was not found."}
    except Exception as e:
        logger.error("Traffic route toggle failed (%s)", type(e).__name__)
        return {
            "success": False,
            "error": "Failed to toggle traffic route. Check controller connectivity and permissions.",
        }
