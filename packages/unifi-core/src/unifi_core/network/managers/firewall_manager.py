import copy
import json
import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequest, ApiRequestV2
from aiounifi.models.firewall_policy import FirewallPolicy
from aiounifi.models.port_forward import PortForward
from aiounifi.models.traffic_route import TrafficRoute

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_FIREWALL_POLICIES = "firewall_policies"
CACHE_PREFIX_TRAFFIC_ROUTES = "traffic_routes"
CACHE_PREFIX_PORT_FORWARDS = "port_forwards"
CACHE_PREFIX_FIREWALL_ZONES = "firewall_zones"
CACHE_PREFIX_FIREWALL_GROUPS = "firewall_groups"


class FirewallManager:
    """Manages Firewall Policies, Traffic Routes, and Port Forwards on the Unifi Controller."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the Firewall Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def get_firewall_policies(self, include_predefined: bool = False) -> List[FirewallPolicy]:
        """Get firewall policies.

        Args:
            include_predefined: Whether to include predefined policies.

        Returns:
            List of FirewallPolicy objects.
        """
        cache_key = f"{CACHE_PREFIX_FIREWALL_POLICIES}_{include_predefined}_{self._connection.site}"
        cached_data: Optional[List[FirewallPolicy]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequestV2(method="get", path="/firewall-policies")

            response = await self._connection.request(api_request)

            policies_data = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )

            policies: List[FirewallPolicy] = [FirewallPolicy(p) for p in policies_data]

            if not include_predefined:
                policies = [p for p in policies if not p.predefined]

            result = policies

            self._connection._update_cache(cache_key, result)
            return result
        except Exception as e:
            logger.error("Error getting firewall policies: %s", e)
            raise

    async def toggle_firewall_policy(self, policy_id: str) -> bool:
        """Toggle a firewall policy on/off.

        Returns:
            bool: True if successful.

        Raises:
            UniFiNotFoundError: If the policy does not exist.
        """
        try:
            policies = await self.get_firewall_policies(include_predefined=True)
            policy: Optional[FirewallPolicy] = next(
                (p for p in policies if isinstance(p.raw, dict) and p.raw.get("_id") == policy_id),
                None,
            )

            if policy is None:
                raise UniFiNotFoundError("firewall_policy", policy_id)

            new_state = not policy.enabled
            logger.info("Toggling firewall policy %s to %s", policy_id, "enabled" if new_state else "disabled")

            update_payload = {"enabled": new_state}

            api_request = ApiRequestV2(
                method="put",
                path=f"/firewall-policies/{policy_id}",
                data=update_payload,
            )
            await self._connection.request(api_request)

            self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_POLICIES}_True_{self._connection.site}")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_POLICIES}_False_{self._connection.site}")

            return True
        except Exception as e:
            logger.error("Error toggling firewall policy %s: %s", policy_id, e)
            raise

    async def update_firewall_policy(self, policy_id: str, updates: Dict[str, Any]) -> bool:
        """Update specific fields of a firewall policy.

        Args:
            policy_id: ID of the policy to update.
            updates: Dictionary of fields and new values to apply.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        if not updates:
            logger.warning("No updates provided for firewall policy %s.", policy_id)
            return False

        try:
            all_policies = await self.get_firewall_policies(include_predefined=True)
            policy_to_update: Optional[FirewallPolicy] = next(
                (p for p in all_policies if isinstance(p.raw, dict) and p.raw.get("_id") == policy_id),
                None,
            )

            if policy_to_update is None:
                raise UniFiNotFoundError("firewall_policy", policy_id)

            if not hasattr(policy_to_update, "raw") or not isinstance(policy_to_update.raw, dict):
                logger.error("Could not get raw data for policy %s. Update aborted.", policy_id)
                return False

            # Deep merge preserves nested sub-objects (source, destination, schedule, etc.)
            merged_data = deep_merge(policy_to_update.raw, updates)

            logger.info("Updating firewall policy %s via single-policy endpoint", policy_id)

            api_request = ApiRequestV2(
                method="put",
                path=f"/firewall-policies/{policy_id}",
                data=merged_data,
            )
            await self._connection.request(api_request)

            self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_POLICIES}_True_{self._connection.site}")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_POLICIES}_False_{self._connection.site}")

            logger.info("Successfully submitted update for firewall policy %s.", policy_id)
            return True
        except Exception as e:
            logger.error("Error updating firewall policy %s: %s", policy_id, e, exc_info=True)
            raise

    async def get_traffic_routes(self) -> List[TrafficRoute]:
        """Get all traffic routes.

        Returns:
            List of TrafficRoute objects.
        """
        cache_key = f"{CACHE_PREFIX_TRAFFIC_ROUTES}_{self._connection.site}"
        cached_data: Optional[List[TrafficRoute]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequestV2(method="get", path="/trafficroutes")

            response = await self._connection.request(api_request)

            routes_data = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )

            routes: List[TrafficRoute] = [TrafficRoute(r) for r in routes_data]

            result = routes

            self._connection._update_cache(cache_key, result)
            return result
        except Exception as e:
            logger.error("Error getting traffic routes: %s", e)
            raise

    async def update_traffic_route(self, route_id: str, updates: Dict[str, Any]) -> bool:
        """Update specific fields of a traffic route using the V2 API.

        Args:
            route_id: ID of the route to update.
            updates: Dictionary of fields and new values to apply.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        if not updates:
            logger.warning("No updates provided for traffic route %s.", route_id)
            return True  # No action needed, considered success

        try:
            # Fetch existing route data using the V2-based method
            routes = await self.get_traffic_routes()
            route_to_update_obj: Optional[TrafficRoute] = next(
                (r for r in routes if isinstance(r.raw, dict) and r.raw.get("_id") == route_id),
                None,
            )

            if route_to_update_obj is None:
                raise UniFiNotFoundError("traffic_route", route_id)

            if not hasattr(route_to_update_obj, "raw") or not isinstance(route_to_update_obj.raw, dict):
                logger.error("Could not get raw data for traffic route %s. Update aborted.", route_id)
                return False

            # Deep copy to avoid mutating the cached TrafficRoute.raw
            updated_data = copy.deepcopy(route_to_update_obj.raw)
            for key, value in updates.items():
                updated_data[key] = value

            api_path = f"/trafficroutes/{route_id}"

            logger.info(
                "Updating traffic route %s via V2 endpoint (%s) with data: %s", route_id, api_path, updated_data
            )

            # Use ApiRequestV2 for the update
            api_request = ApiRequestV2(
                method="put",
                path=api_path,
                data=updated_data,  # V2 typically uses the 'data' field
            )

            # The request method should handle potential V2 response structures
            await self._connection.request(api_request)

            # Invalidate cache
            cache_key = f"{CACHE_PREFIX_TRAFFIC_ROUTES}_{self._connection.site}"
            self._connection._invalidate_cache(cache_key)

            logger.info("Successfully submitted V2 update for traffic route %s.", route_id)
            return True
        except Exception as e:
            logger.error("Error updating traffic route %s via V2: %s", route_id, e, exc_info=True)
            raise

    async def toggle_traffic_route(self, route_id: str) -> bool:
        """Toggle a traffic route on/off.

        Args:
            route_id: ID of the route to toggle.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            routes = await self.get_traffic_routes()
            route: Optional[TrafficRoute] = next(
                (r for r in routes if isinstance(r.raw, dict) and r.raw.get("_id") == route_id),
                None,
            )

            if route is None:
                raise UniFiNotFoundError("traffic_route", route_id)

            if not hasattr(route, "raw") or not isinstance(route.raw, dict):
                logger.error("Could not get raw data for traffic route %s. Toggle aborted.", route_id)
                return False

            new_state = not route.enabled
            logger.info("Toggling traffic route %s to %s", route_id, "enabled" if new_state else "disabled")

            # Use the update method for consistency
            update_payload = {"enabled": new_state}
            return await self.update_traffic_route(route_id, update_payload)

        except Exception as e:
            logger.error("Error toggling traffic route %s: %s", route_id, e, exc_info=True)
            raise

    async def create_traffic_route(self, route_data: Dict[str, Any]) -> Optional[Dict]:
        """Create a new traffic route. Returns the created route data dict or None.

        Args:
            route_data: Dictionary containing the route configuration.
                      Expected keys depend on route type (e.g., name, interface,
                      domain_names or ip_addresses or network_ids, enabled, description).

        Returns:
            The created route data dict, or None if creation failed.
        """
        if not route_data.get("name") or not route_data.get("interface"):
            logger.error("Missing required keys for creating traffic route (name, interface)")
            return None

        try:
            logger.info("Attempting to create traffic route '%s'", route_data["name"])
            api_path = "/trafficroutes"  # V2 endpoint for creation
            # Log the exact data being sent for easier debugging
            logger.info(
                "Attempting to create traffic route via V2 endpoint (%s) with payload: %s",
                api_path,
                json.dumps(route_data, indent=2),
            )

            # Use ApiRequestV2 for the creation
            api_request = ApiRequestV2(method="post", path=api_path, data=route_data)
            response = await self._connection.request(api_request)

            # Check response structure for success and ID (adjust based on actual V2 response)
            # Example V2 success might be a 201 Created with the new object or ID in body/headers
            if isinstance(response, dict) and response.get("_id"):  # Simple check if response is the new object
                new_id = response.get("_id")
                logger.info("Successfully created traffic route via V2. New ID: %s", new_id)
                self._connection._invalidate_cache(f"{CACHE_PREFIX_TRAFFIC_ROUTES}_{self._connection.site}")
                # Return a clear success dictionary with the ID
                return {"success": True, "route_id": new_id}
            elif (
                isinstance(response, list) and len(response) == 1 and response[0].get("_id")
            ):  # Sometimes APIs return a list containing the single new item
                new_id = response[0].get("_id")
                logger.info("Successfully created traffic route via V2 (list response). New ID: %s", new_id)
                self._connection._invalidate_cache(f"{CACHE_PREFIX_TRAFFIC_ROUTES}_{self._connection.site}")
                # Return a clear success dictionary with the ID
                return {"success": True, "route_id": new_id}
            else:
                # Handle unexpected non-error response
                error_detail = f"Unexpected success response format: {str(response)}"
                logger.error("Failed to create traffic route via V2. %s", error_detail)
                return {"success": False, "error": error_detail}

        except Exception as e:
            # Log the exception details
            logger.error("Exception during V2 traffic route creation: %s", e, exc_info=True)

            # Extract specific API error message if available
            api_error_message = str(e)
            if hasattr(e, "args") and e.args:
                try:
                    # Attempt to parse nested error structure seen in logs
                    error_details = e.args[0]
                    if isinstance(error_details, dict) and "message" in error_details:
                        api_error_message = error_details["message"]
                    elif isinstance(error_details, str):  # Fallback if it's just a string
                        api_error_message = error_details
                except Exception as parse_exc:
                    logger.warning(
                        "Could not parse specific API error from exception args: %s. Parse error: %s", e.args, parse_exc
                    )

            # Return a clear failure dictionary with the extracted error message
            return {"success": False, "error": f"API Error: {api_error_message}"}

    async def delete_traffic_route(self, route_id: str) -> bool:
        """Delete a traffic route by ID.

        Args:
            route_id: ID of the route to delete.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            # Use V2 endpoint for deletion
            api_request = ApiRequestV2(method="delete", path=f"/trafficroutes/{route_id}")
            await self._connection.request(api_request)

            cache_key = f"{CACHE_PREFIX_TRAFFIC_ROUTES}_{self._connection.site}"
            self._connection._invalidate_cache(cache_key)
            logger.info("Successfully deleted traffic route %s", route_id)
            return True
        except Exception as e:
            # Handle specific "not found" errors if possible?
            logger.error("Error deleting traffic route %s: %s", route_id, e, exc_info=True)
            raise

    async def get_port_forwards(self) -> List[PortForward]:
        """Get all port forwarding rules.
        Returns:
             List of PortForward objects.
        """
        cache_key = f"{CACHE_PREFIX_PORT_FORWARDS}_{self._connection.site}"
        cached_data: Optional[List[PortForward]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequest(method="get", path="/rest/portforward")
            response = await self._connection.request(api_request)
            rules_data = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
            rules: List[PortForward] = [PortForward(r) for r in rules_data]

            result = rules

            self._connection._update_cache(cache_key, result)
            return result
        except Exception as e:
            logger.error("Error getting port forwards: %s", e)
            raise

    async def get_port_forward_by_id(self, rule_id: str) -> PortForward:
        """Get a specific port forwarding rule by ID.

        Raises:
            UniFiNotFoundError: If the rule does not exist.
        """
        rules = await self.get_port_forwards()
        match = next(
            (r for r in rules if isinstance(r.raw, dict) and r.raw.get("_id") == rule_id),
            None,
        )
        if match is None:
            raise UniFiNotFoundError("port_forward", rule_id)
        return match

    async def update_port_forward(self, rule_id: str, updates: Dict[str, Any]) -> bool:
        """Update specific fields of a port forwarding rule.

        Args:
            rule_id: ID of the rule to update.
            updates: Dictionary of fields and new values to apply.

        Returns:
            bool: True if successful.

        Raises:
            UniFiNotFoundError: If the rule does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        if not updates:
            logger.warning("No updates provided for port forward %s.", rule_id)
            return True  # No action needed, considered success

        try:
            # Fetch existing rule data; raises on miss.
            rule_to_update_obj = await self.get_port_forward_by_id(rule_id)

            if not hasattr(rule_to_update_obj, "raw") or not isinstance(rule_to_update_obj.raw, dict):
                logger.error("Could not get raw data for port forward %s. Update aborted.", rule_id)
                return False

            # Deep copy to avoid mutating the cached PortForward.raw
            updated_data = copy.deepcopy(rule_to_update_obj.raw)

            # Merge updates into copied data
            for key, value in updates.items():
                updated_data[key] = value

            logger.info("Updating port forward %s with full data: %s", rule_id, updated_data)

            api_request = ApiRequest(
                method="put",
                path=f"/rest/portforward/{rule_id}",  # V1 endpoint path, corrected
                data=updated_data,
            )

            await self._connection.request(api_request)

            # Invalidate cache
            cache_key = f"{CACHE_PREFIX_PORT_FORWARDS}_{self._connection.site}"
            self._connection._invalidate_cache(cache_key)

            logger.info("Successfully submitted update for port forward %s.", rule_id)
            return True
        except Exception as e:
            logger.error("Error updating port forward %s: %s", rule_id, e, exc_info=True)
            raise

    async def toggle_port_forward(self, rule_id: str) -> bool:
        """Toggle a port forwarding rule on/off.

        Args:
            rule_id: ID of the rule to toggle.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            # raises UniFiNotFoundError on miss
            rule = await self.get_port_forward_by_id(rule_id)

            if not hasattr(rule, "raw") or not isinstance(rule.raw, dict):
                logger.error("Could not get raw data for port forward %s. Toggle aborted.", rule_id)
                return False

            new_state = not rule.enabled
            logger.info("Toggling port forward %s to %s", rule_id, "enabled" if new_state else "disabled")

            # Use the update method
            update_payload = {"enabled": new_state}
            return await self.update_port_forward(rule_id, update_payload)

        except Exception as e:
            logger.error("Error toggling port forward %s: %s", rule_id, e, exc_info=True)
            raise

    async def create_port_forward(self, rule_data: Dict[str, Any]) -> Optional[Dict]:
        """Create a new port forwarding rule. Returns the created rule data dict or None.

        Args:
            rule_data: Dictionary containing the rule configuration. Expected keys:
                       name (str), dst_port (str), fwd_port (str), fwd_ip (str),
                       protocol (str, optional), enabled (bool, optional), etc.

        Returns:
            The created rule data dict, or None if creation failed.
        """
        required_keys = {"name", "dst_port", "fwd_port", "fwd_ip"}
        if not required_keys.issubset(rule_data.keys()):
            missing = required_keys - rule_data.keys()
            logger.error("Missing required keys for creating port forward: %s", missing)
            return None

        try:
            logger.info("Attempting to create port forward rule '%s'", rule_data["name"])
            api_request = ApiRequest(
                method="post",
                path="/rest/portforward",  # V1 endpoint path, corrected
                data=rule_data,
            )
            response = await self._connection.request(api_request)

            # V1 POST may return either {"data": [{...}]} (older firmware) or a bare
            # list [{...}] (UDM-SE 8.4.x and similar). Handle both — see #207.
            data = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
            created_rule = data[0] if data else None
            if not created_rule:
                logger.error("Unexpected response format creating port forward: %s", response)
                return None

            cache_key = f"{CACHE_PREFIX_PORT_FORWARDS}_{self._connection.site}"
            self._connection._invalidate_cache(cache_key)
            logger.info("Successfully created port forward '%s'", rule_data.get("name"))
            return created_rule if isinstance(created_rule, dict) else None

        except Exception as e:
            logger.error(
                "Error creating port forward '%s': %s",
                rule_data.get("name", "unknown"),
                e,
                exc_info=True,
            )
            raise

    async def delete_port_forward(self, rule_id: str) -> bool:
        """Delete a port forwarding rule by ID.

        Args:
            rule_id: ID of the rule to delete.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            # Use V1 endpoint as aiounifi does
            api_request = ApiRequest(
                method="delete",
                path=f"/rest/portforward/{rule_id}",
            )
            await self._connection.request(api_request)

            cache_key = f"{CACHE_PREFIX_PORT_FORWARDS}_{self._connection.site}"
            self._connection._invalidate_cache(cache_key)
            logger.info("Successfully deleted port forward %s", rule_id)
            return True
        except Exception as e:
            logger.error("Error deleting port forward %s: %s", rule_id, e, exc_info=True)
            raise

    async def create_firewall_policy(self, policy_data: Dict[str, Any]) -> Optional[FirewallPolicy]:
        """Create a new firewall policy using the V2 API.

        Args:
            policy_data: Dictionary containing the policy configuration conforming
                         to the UniFi API structure for firewall policies.

        Returns:
            The created FirewallPolicy object, or None if creation failed.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            policy_name = policy_data.get("name", "Unnamed Policy")
            logger.info("Attempting to create firewall policy '%s' via V2 endpoint.", policy_name)
            logger.debug("Firewall policy create payload: %s", json.dumps(policy_data, indent=2))

            api_request = ApiRequestV2(method="post", path="/firewall-policies", data=policy_data)

            response = await self._connection.request(api_request)

            # V2 POST often returns the created object directly or within a list
            created_policy_data = None
            if isinstance(response, dict) and response.get("_id"):
                created_policy_data = response
            elif isinstance(response, list) and len(response) == 1 and response[0].get("_id"):
                created_policy_data = response[0]

            if created_policy_data:
                new_policy_id = created_policy_data.get("_id")
                logger.info("Successfully created firewall policy '%s' with ID %s via V2.", policy_name, new_policy_id)
                # Invalidate caches after successful creation
                self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_POLICIES}_True_{self._connection.site}")
                self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_POLICIES}_False_{self._connection.site}")
                return FirewallPolicy(created_policy_data)
            else:
                logger.error(
                    "Failed to create firewall policy '%s'. Unexpected V2 response format: %s", policy_name, response
                )
                raise RuntimeError(
                    "Unexpected response from controller (no _id in response). Raw: %s"
                    % json.dumps(response, default=str)
                )

        except Exception as e:
            logger.error(
                "Error creating firewall policy '%s' via V2: %s",
                policy_data.get("name", "Unnamed Policy"),
                e,
                exc_info=True,
            )
            raise

    async def delete_firewall_policy(self, policy_id: str) -> bool:
        """Delete a firewall policy by ID.

        Args:
            policy_id: ID of the policy to delete.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequestV2(method="delete", path=f"/firewall-policies/{policy_id}")
            await self._connection.request(api_request)

            cache_key_true = f"{CACHE_PREFIX_FIREWALL_POLICIES}_True_{self._connection.site}"
            cache_key_false = f"{CACHE_PREFIX_FIREWALL_POLICIES}_False_{self._connection.site}"
            self._connection._invalidate_cache(cache_key_true)
            self._connection._invalidate_cache(cache_key_false)
            logger.info("Successfully deleted firewall policy %s", policy_id)
            return True
        except Exception as e:
            logger.error("Error deleting firewall policy %s: %s", policy_id, e, exc_info=True)
            raise

    async def get_firewall_zones(self) -> List[Dict[str, Any]]:
        """Return list of firewall zones via V2 API."""
        cache_key = f"{CACHE_PREFIX_FIREWALL_ZONES}_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if cached is not None:
            return cached
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            # Network 10.2+ exposes zones at /firewall/zone-matrix (returns
            # zone metadata plus an inter-zone policy-count matrix).
            # Older firmware exposed a flat list at /firewall/zones; try that
            # as a fallback so this works across versions.
            try:
                api_request = ApiRequestV2(method="get", path="/firewall/zone-matrix")
                resp = await self._connection.request(api_request)
            except Exception as primary_exc:
                logger.debug(
                    "Primary /firewall/zone-matrix failed (%s), falling back to /firewall/zones",
                    primary_exc,
                )
                api_request = ApiRequestV2(method="get", path="/firewall/zones")
                resp = await self._connection.request(api_request)
            data = resp if isinstance(resp, list) else resp.get("data", []) if isinstance(resp, dict) else []
            # The zone-matrix endpoint includes a `data` field per zone that
            # contains the policy-count matrix to every other zone (O(N^2)
            # payload). For a zones listing we only want the zone metadata,
            # so drop the matrix field if present. The matrix is still
            # available via a dedicated tool if needed.
            data = [{k: v for k, v in zone.items() if k != "data"} if isinstance(zone, dict) else zone for zone in data]
            self._connection._update_cache(cache_key, data)
            return data
        except Exception as e:
            logger.error("Error fetching firewall zones: %s", e, exc_info=True)
            raise

    # ---- Firewall Groups (v1 REST: address-group, port-group) ----

    async def get_firewall_groups(self) -> List[Dict[str, Any]]:
        """Get all firewall groups (address and port groups).

        These are reusable objects referenced by firewall policies via
        ip_group_id and port_group_id fields.

        Returns:
            List of firewall group dictionaries.
        """
        cache_key = f"{CACHE_PREFIX_FIREWALL_GROUPS}_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if cached is not None:
            return cached

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequest(method="get", path="/rest/firewallgroup")
            response = await self._connection.request(api_request)
            data = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
            self._connection._update_cache(cache_key, data)
            return data
        except Exception as e:
            logger.error("Error getting firewall groups: %s", e)
            raise

    async def get_firewall_group_by_id(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific firewall group by ID.

        Args:
            group_id: The ID of the firewall group.

        Returns:
            The firewall group dictionary, or None if not found.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequest(method="get", path=f"/rest/firewallgroup/{group_id}")
            response = await self._connection.request(api_request)
            data = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
            return data[0] if data else None
        except Exception as e:
            logger.error("Error getting firewall group %s: %s", group_id, e)
            raise

    async def create_firewall_group(self, group_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new firewall group.

        Args:
            group_data: Dictionary with name, group_type, and group_members.
                group_type must be 'address-group', 'ipv6-address-group', or 'port-group'.
                group_type cannot be changed after creation.

        Returns:
            The created firewall group dictionary, or None on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        if not group_data.get("name") or not group_data.get("group_type"):
            logger.error("Missing required fields 'name' and/or 'group_type' for firewall group")
            return None

        try:
            api_request = ApiRequest(method="post", path="/rest/firewallgroup", data=group_data)
            response = await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_FIREWALL_GROUPS)

            data = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
            return data[0] if data else None
        except Exception as e:
            logger.error("Error creating firewall group: %s", e, exc_info=True)
            raise

    async def update_firewall_group(self, group_id: str, group_data: Dict[str, Any]) -> bool:
        """Update an existing firewall group.

        Args:
            group_id: The ID of the group to update.
            group_data: Complete group data (PUT replaces the entire object).
                Note: group_type cannot be changed after creation.

        Returns:
            True on success, False on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequest(method="put", path=f"/rest/firewallgroup/{group_id}", data=group_data)
            await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_FIREWALL_GROUPS)
            return True
        except Exception as e:
            logger.error("Error updating firewall group %s: %s", group_id, e, exc_info=True)
            raise

    async def delete_firewall_group(self, group_id: str) -> bool:
        """Delete a firewall group.

        Args:
            group_id: The ID of the group to delete.

        Returns:
            True on success, False on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequest(method="delete", path=f"/rest/firewallgroup/{group_id}")
            await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_FIREWALL_GROUPS)
            return True
        except Exception as e:
            logger.error("Error deleting firewall group %s: %s", group_id, e, exc_info=True)
            raise
