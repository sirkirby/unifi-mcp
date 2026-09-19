"""Traffic Route Manager for UniFi Network MCP server.

Manages policy-based traffic routing (V2 API) for VPN routing,
domain-based routing, and other advanced routing scenarios.
"""

import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.models.traffic_routes import build_traffic_route_create_payload, validate_update

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_TRAFFIC_ROUTES = "traffic_routes"


class TrafficRouteManager:
    """Manages traffic route operations on the UniFi Controller.

    Traffic routes are policy-based routing rules that can route traffic
    based on domains, IP addresses, regions, or target devices through
    specific networks (like VPNs).
    """

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the Traffic Route Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def get_traffic_routes(self) -> List[Dict[str, Any]]:
        """Get all traffic routes for the current site.

        Uses GET /trafficroutes endpoint (V2 API).

        Returns:
            List of traffic route objects.
        """
        cache_key = f"{CACHE_PREFIX_TRAFFIC_ROUTES}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data
        get_cache_generation = getattr(self._connection, "_get_cache_generation", None)
        update_cache_if_current = getattr(self._connection, "_update_cache_if_current", None)
        cache_generation = get_cache_generation(cache_key) if callable(get_cache_generation) else None

        try:
            api_request = ApiRequestV2(method="get", path="/trafficroutes", data=None)
            response = await self._connection.request(api_request)

            routes = (
                response.get("data", [])
                if isinstance(response, dict)
                else response
                if isinstance(response, list)
                else []
            )

            if cache_generation is not None and callable(update_cache_if_current):
                update_cache_if_current(cache_key, routes, cache_generation)
            else:
                self._connection._update_cache(cache_key, routes)
            return routes
        except Exception:
            logger.error("Traffic route listing failed")
            raise

    async def get_traffic_route_details(self, route_id: str) -> Dict[str, Any]:
        """Get details for a specific traffic route by ID.

        Raises:
            UniFiNotFoundError: If the route does not exist.
        """
        all_routes = await self.get_traffic_routes()
        route = next((r for r in all_routes if r.get("_id") == route_id), None)
        if route is None:
            raise UniFiNotFoundError("traffic_route", route_id)
        return route

    async def create_traffic_route(self, route_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a traffic route from the canonical validated payload contract."""
        if type(route_data) is not dict:
            raise ValueError("Traffic Route create data must be an object.")
        try:
            payload = build_traffic_route_create_payload(**route_data)
        except TypeError as error:
            raise ValueError("Unknown or invalid Traffic Route create fields.") from error

        api_request = ApiRequestV2(method="post", path="/trafficroutes", data=payload)
        try:
            response = await self._connection.request(api_request)
            result = response.get("data", response) if isinstance(response, dict) else response
            if isinstance(result, list):
                result = result[0] if len(result) == 1 else None
            if isinstance(result, dict):
                route_id = result.get("_id")
                if isinstance(route_id, str) and route_id.strip():
                    return result
            raise ValueError(
                "Controller returned no created traffic route; the route may have been created. "
                "List traffic routes before retrying."
            )
        finally:
            # A malformed reply after POST is ambiguous: the controller may have
            # committed the route, so cached route state must not be retained.
            self._connection._invalidate_cache(f"{CACHE_PREFIX_TRAFFIC_ROUTES}_{self._connection.site}")

    async def update_traffic_route(self, route_id: str, enabled: Optional[bool] = None, **kwargs) -> bool:
        """Update a traffic route.

        Uses PUT /trafficroutes/{route_id} endpoint (V2 API).
        Sends the full merged object as required by the API.

        Args:
            route_id: The _id of the traffic route to update.
            enabled: Optional enable/disable setting.
            **kwargs: Additional fields to update.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Existence check; raises UniFiNotFoundError on miss.
            current = await self.get_traffic_route_details(route_id)

            updates = dict(kwargs)
            if enabled is not None:
                updates["enabled"] = enabled
            # Preserve the controller-shaped alias accepted by existing Core
            # callers while validating through the canonical public field.
            if "description" in updates:
                if "name" in updates:
                    raise ValueError("Traffic Route update cannot include both name and description.")
                updates["name"] = updates.pop("description")
            validated_updates = validate_update(
                updates,
                matching_target=current.get("matching_target"),
                current_fields=current,
            )

            # Preserve the full historical route after validating only caller
            # replacements; legacy unsupplied selectors need not be parseable.
            payload: Dict[str, Any] = current.copy()
            payload.update(validated_updates)

            api_request = ApiRequestV2(
                method="put",
                path=f"/trafficroutes/{route_id}",
                data=payload,
            )
            try:
                await self._connection.request(api_request)
            finally:
                # A failed PUT may still have committed on the controller, so
                # stale traffic-route state cannot be retained.
                self._connection._invalidate_cache(f"{CACHE_PREFIX_TRAFFIC_ROUTES}_{self._connection.site}")

            logger.info("Traffic route update submitted")

            return True

        except Exception:
            logger.error("Traffic route update failed")
            raise

    async def toggle_traffic_route(self, route_id: str) -> bool:
        """Toggle a traffic route's enabled state.

        Raises:
            UniFiNotFoundError: If the route does not exist.
        """
        current = await self.get_traffic_route_details(route_id)  # raises on miss
        new_state = not current.get("enabled", True)
        return await self.update_traffic_route(route_id, enabled=new_state)

    async def update_kill_switch(self, route_id: str, enabled: bool) -> bool:
        """Update the kill switch setting for a traffic route.

        The kill switch blocks all traffic if the route's target network
        (e.g., VPN) becomes unavailable.

        Args:
            route_id: The _id of the traffic route.
            enabled: Whether to enable or disable the kill switch.

        Returns:
            True if successful, False otherwise.
        """
        return await self.update_traffic_route(route_id, kill_switch_enabled=enabled)
