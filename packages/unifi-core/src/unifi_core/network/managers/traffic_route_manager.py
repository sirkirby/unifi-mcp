"""Traffic Route Manager for UniFi Network MCP server.

Manages policy-based traffic routing (V2 API) for VPN routing,
domain-based routing, and other advanced routing scenarios.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequestV2

from unifi_core.auth import AuthenticationStatus
from unifi_core.exceptions import UniFiAuthError, UniFiNotFoundError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.network_manager import NetworkManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_TRAFFIC_ROUTES = "traffic_routes"
# Legacy FirewallManager reads cache aiounifi TrafficRoute wrappers, while this
# manager caches controller dictionaries. Keep the representations separate,
# but invalidate them together after every traffic-route mutation.
CACHE_PREFIX_LEGACY_TRAFFIC_ROUTES = "legacy_traffic_routes"
_CLIENT_MAC_PATTERN = re.compile(r"^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}$")


def is_unicast_client_mac(value: Any) -> bool:
    """Return whether *value* is a usable colon-delimited unicast client MAC."""
    if not isinstance(value, str) or _CLIENT_MAC_PATTERN.fullmatch(value) is None:
        return False
    octets = bytes.fromhex(value.replace(":", ""))
    return octets != b"\x00" * 6 and not (octets[0] & 1)


def invalidate_traffic_route_caches(connection: ConnectionManager) -> None:
    """Clear every cached representation of traffic routes for the active site."""
    for cache_prefix in (CACHE_PREFIX_TRAFFIC_ROUTES, CACHE_PREFIX_LEGACY_TRAFFIC_ROUTES):
        connection._invalidate_cache(f"{cache_prefix}_{connection.site}")


class TrafficRoutePreflightError(ValueError):
    """A create was rejected before any controller POST was attempted."""


class TrafficRouteManager:
    """Manages traffic route operations on the UniFi Controller.

    Traffic routes are policy-based routing rules that can route traffic
    based on domains, IP addresses, regions, or target devices through
    specific networks (like VPNs).
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
        network_manager: Optional[NetworkManager] = None,
    ):
        """Initialize the Traffic Route Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
            network_manager: The shared NetworkManager instance used to verify
                Internet-route target networks.
        """
        self._connection = connection_manager
        self._network_manager = network_manager or NetworkManager(connection_manager)

    async def validate_internet_route_target(self, target_devices: Any, network_id: Any) -> None:
        """Require an Internet route to target one explicit client via a WAN."""
        if not isinstance(target_devices, list) or len(target_devices) != 1:
            raise ValueError("INTERNET Traffic Routes require exactly one explicit CLIENT target")

        target = target_devices[0]
        if not isinstance(target, dict) or target.get("type") != "CLIENT":
            raise ValueError("INTERNET Traffic Routes require exactly one explicit CLIENT target")

        client_mac = target.get("client_mac")
        if not is_unicast_client_mac(client_mac):
            raise ValueError("INTERNET Traffic Routes require a valid unicast client MAC address")

        if not isinstance(network_id, str) or not network_id:
            raise ValueError("INTERNET Traffic Routes require a target WAN network")

        auth_status = getattr(self._connection, "authentication_status", None)
        if isinstance(auth_status, AuthenticationStatus) and not auth_status.session_available:
            if not await self._connection.ensure_session_connected():
                raise UniFiAuthError(
                    "INTERNET Traffic Routes require Network session authentication. "
                    "Configure UNIFI_NETWORK_USERNAME and UNIFI_NETWORK_PASSWORD."
                )

        target_network = await self._network_manager.get_network_details(network_id, force_refresh=True)
        if not isinstance(target_network, dict) or str(target_network.get("purpose", "")).lower() != "wan":
            raise ValueError("INTERNET Traffic Routes can target only a verified WAN network")

    async def _validate_internet_route_payload(
        self,
        payload: Dict[str, Any],
        *,
        existing_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Validate Internet routes, retaining only an unchanged disabled legacy scope."""
        matching_target = payload.get("matching_target")
        is_internet_route = isinstance(matching_target, str) and matching_target.upper() == "INTERNET"
        if not is_internet_route:
            return

        if payload.get("enabled") is not False:
            await self.validate_internet_route_target(payload.get("target_devices"), payload.get("network_id"))
            return

        existing_target = existing_payload.get("matching_target") if existing_payload else None
        existing_is_internet_route = isinstance(existing_target, str) and existing_target.upper() == "INTERNET"
        scope_changed = (
            (
                not existing_is_internet_route
                or existing_payload.get("target_devices") != payload.get("target_devices")
                or existing_payload.get("network_id") != payload.get("network_id")
            )
            if existing_payload
            else True
        )
        if scope_changed:
            await self.validate_internet_route_target(payload.get("target_devices"), payload.get("network_id"))

    async def get_traffic_routes(self, *, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Get all traffic routes for the current site.

        Uses GET /trafficroutes endpoint (V2 API).

        Returns:
            List of traffic route objects.
        """
        cache_key = f"{CACHE_PREFIX_TRAFFIC_ROUTES}_{self._connection.site}"
        if not force_refresh:
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
        except Exception as e:
            logger.error("Traffic route list failed (%s)", type(e).__name__)
            raise

    async def get_traffic_route_details(
        self,
        route_id: str,
        *,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Get details for a specific traffic route by ID.

        Raises:
            UniFiNotFoundError: If the route does not exist.
        """
        all_routes = await self.get_traffic_routes(force_refresh=force_refresh)
        route = next((r for r in all_routes if r.get("_id") == route_id), None)
        if route is None:
            raise UniFiNotFoundError("traffic_route", route_id)
        return route

    async def create_traffic_route(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a traffic route using POST /trafficroutes (V2 API)."""
        try:
            await self._validate_internet_route_payload(payload)
        except UniFiAuthError as exc:
            raise TrafficRoutePreflightError(str(exc)) from None
        except UniFiNotFoundError:
            raise TrafficRoutePreflightError("Target network was not found.") from None
        except ValueError as exc:
            raise TrafficRoutePreflightError(str(exc)) from None
        except Exception:
            raise TrafficRoutePreflightError(
                "Could not verify the target WAN network before creating the route. "
                "Check controller connectivity and session authentication."
            ) from None
        api_request = ApiRequestV2(method="post", path="/trafficroutes", data=payload)
        # A POST may commit before its response is lost. Clear both cache
        # representations after every request attempt, before validating a returned body.
        try:
            response = await self._connection.request(api_request)
        finally:
            invalidate_traffic_route_caches(self._connection)
        result = response.get("data", response) if isinstance(response, dict) else response
        if isinstance(result, list):
            result = result[0] if len(result) == 1 else None
        if not isinstance(result, dict) or not isinstance(result.get("_id"), str) or not result["_id"].strip():
            raise ValueError("Controller returned an invalid traffic route create response")
        return result

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
            current = await self.get_traffic_route_details(route_id, force_refresh=True)

            # Start with full existing route and apply updates
            payload: Dict[str, Any] = current.copy()

            if enabled is not None:
                payload["enabled"] = enabled

            # Apply any additional updates
            for key, value in kwargs.items():
                if value is not None:
                    payload[key] = value

            await self._validate_internet_route_payload(payload, existing_payload=current)

            api_request = ApiRequestV2(
                method="put",
                path=f"/trafficroutes/{route_id}",
                data=payload,
            )
            # A PUT may commit before its response is lost; never retain a pre-update cache.
            try:
                await self._connection.request(api_request)
            finally:
                invalidate_traffic_route_caches(self._connection)

            logger.info("Traffic route updated")
            return True

        except Exception as e:
            logger.error("Traffic route update failed (%s)", type(e).__name__)
            raise

    async def toggle_traffic_route(self, route_id: str) -> bool:
        """Toggle a traffic route's enabled state.

        Raises:
            UniFiNotFoundError: If the route does not exist.
        """
        current = await self.get_traffic_route_details(route_id, force_refresh=True)  # raises on miss
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
        try:
            # raises UniFiNotFoundError on miss
            current = await self.get_traffic_route_details(route_id, force_refresh=True)

            payload: Dict[str, Any] = current.copy()
            payload["kill_switch_enabled"] = enabled

            await self._validate_internet_route_payload(payload, existing_payload=current)

            api_request = ApiRequestV2(
                method="put",
                path=f"/trafficroutes/{route_id}",
                data=payload,
            )
            # A PUT may commit before its response is lost; never retain a pre-update cache.
            try:
                await self._connection.request(api_request)
            finally:
                invalidate_traffic_route_caches(self._connection)

            logger.info("Traffic route kill switch updated")
            return True

        except Exception as e:
            logger.error("Traffic route kill switch update failed (%s)", type(e).__name__)
            raise
