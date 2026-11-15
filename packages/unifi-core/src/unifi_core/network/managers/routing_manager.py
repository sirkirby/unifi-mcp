"""Routing Manager for UniFi Network MCP server.

Manages static route operations for advanced routing configuration.
"""

import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequest, ApiRequestV2

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.request_paths import object_id

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_ROUTES = "routes"


def _legacy_active_route(route: Dict[str, Any]) -> Dict[str, Any]:
    """Express a V2 ``/routes`` row in the ``/stat/routing`` row shape.

    V2 names the outbound interface by network ID, not by interface name, and
    lists every candidate next hop; only the ones in use are kept.
    """
    nexthops = [hop for hop in route.get("nexthops") or [] if isinstance(hop, dict)]
    in_use = [hop for hop in nexthops if hop.get("in_use")] or nexthops
    row: Dict[str, Any] = {
        "pfx": route.get("destination"),
        "nh": [{"via": hop.get("gateway"), "intf": hop.get("interface")} for hop in in_use],
        "metric": route.get("distance"),
    }
    for source, target in (("origin", "origin"), ("type", "route_type")):
        if route.get(source) is not None:
            row[target] = route[source]
    return row


class RoutingManager:
    """Manages static route operations on the UniFi Controller."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the Routing Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def get_routes(self) -> List[Dict[str, Any]]:
        """Get all user-defined static routes for the current site.

        Uses GET /rest/routing endpoint.

        Returns:
            List of route objects containing network, nexthop, and settings.
        """
        cache_key = f"{CACHE_PREFIX_ROUTES}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequest(method="get", path="/rest/routing")
            response = await self._connection.request(api_request)

            routes = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )

            self._connection._update_cache(cache_key, routes)
            return routes
        except Exception as e:
            logger.error("Error getting routes: %s", e)
            raise

    async def get_active_routes(self) -> List[Dict[str, Any]]:
        """Get all active routes (including system routes) from the device.

        Reads the undocumented ``/stat/routing`` endpoint first. Newer
        controllers still answer it, with an empty list, and serve the table
        from the V2 ``/routes`` endpoint instead, so that is read when the
        legacy endpoint has no rows or is missing. V2 rows are returned in the
        legacy row shape (``pfx``, ``nh``, ``metric``).

        Returns:
            List of active route objects from the routing table; empty when
            neither endpoint reports any.
        """
        legacy_error: Optional[Exception] = None
        routes: List[Dict[str, Any]] = []
        try:
            response = await self._connection.request(ApiRequest(method="get", path="/stat/routing"))
            routes = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
        except Exception as e:
            legacy_error = e
            # This endpoint may not exist on all controllers
            if "404" in str(e) or "Not Found" in str(e):
                logger.debug("Active routes endpoint /stat/routing not available on this controller")
            else:
                logger.error("Error getting active routes: %s", e)
        if routes:
            return routes

        try:
            response = await self._connection.request(ApiRequestV2(method="get", path="/routes"))
        except Exception as e:
            logger.debug("V2 routing table /routes not available (%s)", type(e).__name__)
            if legacy_error is not None:
                raise legacy_error
            return routes
        items = response.get("items", []) if isinstance(response, dict) else response
        return [_legacy_active_route(item) for item in items or [] if isinstance(item, dict)]

    async def get_route_details(self, route_id: str) -> Dict[str, Any]:
        """Get details for a specific route by ID.

        Raises:
            UniFiNotFoundError: If the route does not exist.
        """
        all_routes = await self.get_routes()
        route = next((r for r in all_routes if r.get("_id") == route_id), None)
        if route is None:
            raise UniFiNotFoundError("route", route_id)
        return route

    async def create_route(
        self,
        name: str,
        static_route_network: str,
        static_route_nexthop: str,
        static_route_distance: int = 1,
        enabled: bool = True,
        route_type: str = "nexthop-route",
    ) -> Optional[Dict[str, Any]]:
        """Create a new static route.

        Uses POST to /rest/routing endpoint.

        Args:
            name: Name/description for the route.
            static_route_network: Destination network in CIDR format (e.g., "10.0.0.0/24").
            static_route_nexthop: Next-hop IP address or interface.
            static_route_distance: Administrative distance (default 1).
            enabled: Whether the route is enabled (default True).
            route_type: Route type (default "nexthop-route").

        Returns:
            Created route object, or None on failure.
        """
        try:
            payload: Dict[str, Any] = {
                "name": name,
                "static-route_network": static_route_network,
                "static-route_nexthop": static_route_nexthop,
                "static-route_distance": static_route_distance,
                "enabled": enabled,
                "type": route_type,
            }

            api_request = ApiRequest(
                method="post",
                path="/rest/routing",
                data=payload,
            )
            response = await self._connection.request(api_request)

            logger.info("Created route: %s -> %s via %s", name, static_route_network, static_route_nexthop)

            # Invalidate cache
            self._connection._invalidate_cache(f"{CACHE_PREFIX_ROUTES}_{self._connection.site}")

            # Return the created route
            if isinstance(response, list) and len(response) > 0:
                return response[0]
            elif isinstance(response, dict):
                return response.get("data", [response])[0] if response else None

            return None

        except Exception as e:
            logger.error("Error creating route: %s", e, exc_info=True)
            raise

    async def update_route(
        self,
        route_id: str,
        name: Optional[str] = None,
        static_route_network: Optional[str] = None,
        static_route_nexthop: Optional[str] = None,
        static_route_distance: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> bool:
        """Update an existing static route.

        Uses PUT to /rest/routing/{route_id} endpoint.
        Sends the full merged object (not partial updates) as required by the API.

        Args:
            route_id: The _id of the route to update.
            name: Optional new name for the route.
            static_route_network: Optional new destination network.
            static_route_nexthop: Optional new next-hop address.
            static_route_distance: Optional new administrative distance.
            enabled: Optional enable/disable setting.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Existence check; raises UniFiNotFoundError on miss.
            current = await self.get_route_details(route_id)

            # Start with the full existing route and apply updates
            payload: Dict[str, Any] = current.copy()

            # Apply updates to the full object
            if name is not None:
                payload["name"] = name
            if static_route_network is not None:
                payload["static-route_network"] = static_route_network
            if static_route_nexthop is not None:
                payload["static-route_nexthop"] = static_route_nexthop
            if static_route_distance is not None:
                payload["static-route_distance"] = static_route_distance
            if enabled is not None:
                payload["enabled"] = enabled

            api_request = ApiRequest(
                method="put",
                path=f"/rest/routing/{object_id(route_id, 'static route')}",
                data=payload,
            )
            await self._connection.request(api_request)

            logger.info("Updated route %s", route_id)

            # Invalidate cache
            self._connection._invalidate_cache(f"{CACHE_PREFIX_ROUTES}_{self._connection.site}")

            return True

        except Exception as e:
            logger.error("Error updating route %s: %s", route_id, e, exc_info=True)
            raise
