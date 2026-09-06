import asyncio
import copy
import json
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

import aiohttp
from aiounifi.models.api import ApiRequest, ApiRequestV2
from aiounifi.models.firewall_policy import FirewallPolicy
from aiounifi.models.port_forward import PortForward
from aiounifi.models.traffic_route import TrafficRoute

from unifi_core.auth import UniFiAuth
from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.models.firewall import _normalize_endpoint_macs, validate_policy_port_targeting

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_FIREWALL_POLICIES = "firewall_policies"
CACHE_PREFIX_FIREWALL_POLICY_ORDERING = "firewall_policy_ordering"
CACHE_PREFIX_INTEGRATION_FIREWALL_ZONES = "integration_firewall_zones"
CACHE_PREFIX_TRAFFIC_ROUTES = "traffic_routes"
CACHE_PREFIX_PORT_FORWARDS = "port_forwards"
CACHE_PREFIX_FIREWALL_ZONES = "firewall_zones"
CACHE_PREFIX_FIREWALL_GROUPS = "firewall_groups"
CACHE_PREFIX_LEGACY_FIREWALL_RULES = "legacy_firewall_rules"
FIREWALL_ZONE_WRITE_VERIFY_ATTEMPTS = 3
FIREWALL_ZONE_WRITE_VERIFY_DELAY_SECONDS = 0.25
INTEGRATION_API_PAGE_SIZE = 200


class FirewallManager:
    """Manages Firewall Policies, Traffic Routes, and Port Forwards on the Unifi Controller."""

    def __init__(self, connection_manager: ConnectionManager, auth: UniFiAuth | None = None):
        """Initialize the Firewall Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager
        self._auth = auth

    async def get_firewall_policy_by_id(self, policy_id: str) -> FirewallPolicy:
        """Return one V2 firewall policy from the complete policy inventory."""
        policies = await self.get_firewall_policies(include_predefined=True)
        match = next(
            (
                policy
                for policy in policies
                if isinstance(getattr(policy, "raw", None), dict) and policy.raw.get("_id") == policy_id
            ),
            None,
        )
        if match is None:
            raise UniFiNotFoundError("firewall_policy", policy_id)
        return match

    @staticmethod
    def _requested_firewall_policy_ids(ordered_firewall_policy_ids: Any) -> list[str]:
        if not isinstance(ordered_firewall_policy_ids, dict):
            raise ValueError("ordered_firewall_policy_ids must be an object")

        before = ordered_firewall_policy_ids.get("beforeSystemDefined")
        after = ordered_firewall_policy_ids.get("afterSystemDefined")
        if not isinstance(before, list) or not isinstance(after, list):
            raise ValueError(
                "ordered_firewall_policy_ids must include beforeSystemDefined and afterSystemDefined arrays"
            )

        requested_order = before + after
        if not all(isinstance(policy_id, str) and policy_id for policy_id in requested_order):
            raise ValueError("ordered_firewall_policy_ids arrays must contain only non-empty policy ID strings")

        duplicate_ids = sorted(policy_id for policy_id, count in Counter(requested_order).items() if count > 1)
        if duplicate_ids:
            raise ValueError("Reorder payload contains duplicate policy IDs: %s" % ", ".join(duplicate_ids))

        return requested_order

    @staticmethod
    def _validate_firewall_policy_ordering_matches_current(
        ordered_firewall_policy_ids: Any,
        current_ordering_response: Any,
    ) -> None:
        requested_order = FirewallManager._requested_firewall_policy_ids(ordered_firewall_policy_ids)

        if not isinstance(current_ordering_response, dict):
            raise RuntimeError("Current firewall policy ordering response did not include an ordering object")
        current_ordering = current_ordering_response.get("orderedFirewallPolicyIds", current_ordering_response)
        if not isinstance(current_ordering, dict):
            raise RuntimeError("Current firewall policy ordering response did not include an ordering object")

        before = current_ordering.get("beforeSystemDefined", [])
        after = current_ordering.get("afterSystemDefined", [])
        if not isinstance(before, list) or not isinstance(after, list):
            raise RuntimeError("Current firewall policy ordering response did not include ordering arrays")

        current_order = before + after
        requested_counts = Counter(requested_order)
        current_counts = Counter(current_order)
        if requested_counts != current_counts:
            missing_ids = sorted((current_counts - requested_counts).elements())
            unexpected_ids = sorted((requested_counts - current_counts).elements())
            raise ValueError(
                "Reorder payload must preserve the exact current policy ID set. Missing: %s; unexpected: %s"
                % (
                    ", ".join(missing_ids) or "none",
                    ", ".join(unexpected_ids) or "none",
                )
            )

    async def _request_integration_api(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call the official UniFi Network integration API.

        The integration API rejects local controller cookies for these
        endpoints, so an API key is required.
        """
        self._require_integration_api_key("Firewall Integration API access")

        base_url = f"https://{self._connection.host}:{self._connection.port}"
        url = f"{base_url}/proxy/network/integration{path}"
        timeout = aiohttp.ClientTimeout(total=10)

        # get_api_key_session() supplies the required X-API-Key header. The
        # integration endpoints reject the local controller cookie session.
        session = await self._auth.get_api_key_session()

        try:
            async with session.request(
                method.upper(),
                url,
                params=params,
                json=data,
                ssl=False,
                timeout=timeout,
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    try:
                        body_text = (await resp.text()).strip()
                    except Exception as text_error:
                        body_text = f"<failed to read response body: {text_error}>"
                    if len(body_text) > 500:
                        body_text = f"{body_text[:500]}..."
                    if resp.status < 200 or resp.status >= 300:
                        detail = body_text or "<empty body>"
                        raise RuntimeError(f"Integration API returned {resp.status} for {path}: {detail}")
                    detail = body_text or "<empty body>"
                    raise RuntimeError(f"Integration API returned non-JSON response for {path}: {detail}")

                if resp.status < 200 or resp.status >= 300:
                    raise RuntimeError(f"Integration API returned {resp.status} for {path}: {body}")
                return body if isinstance(body, dict) else {}
        finally:
            await session.close()

    def _require_integration_api_key(self, operation: str) -> None:
        """Fail before controller I/O when an Integration API mutation lacks auth."""
        if self._auth is None or not self._auth.has_api_key:
            raise RuntimeError(
                f"{operation} requires a UniFi API key. "
                "Create a Network API token in UniFi Control Plane -> Integrations "
                "and set UNIFI_API_KEY or UNIFI_NETWORK_API_KEY for the MCP."
            )

    async def _get_integration_site_id(self) -> str:
        """Resolve the configured site name/key to the integration API site ID."""
        cache_key = f"integrations_site_id_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if isinstance(cached, str) and cached:
            return cached

        result = await self._request_integration_api("get", "/v1/sites")
        sites = result.get("data", []) if isinstance(result, dict) else []
        if not isinstance(sites, list) or not sites:
            return self._connection.site

        configured = self._connection.site
        match = next(
            (
                s
                for s in sites
                if isinstance(s, dict)
                and configured
                in {
                    str(s.get("id", "")),
                    str(s.get("name", "")),
                    str(s.get("key", "")),
                    str(s.get("siteId", "")),
                }
            ),
            None,
        )
        if match is None and len(sites) == 1 and isinstance(sites[0], dict):
            match = sites[0]

        site_id = str((match or {}).get("id") or configured)
        self._connection._update_cache(cache_key, site_id)
        return site_id

    async def _get_integration_firewall_zones(self, site_id: str | None = None) -> List[Dict[str, Any]]:
        """Return firewall zones from the official integration API."""
        if site_id is None:
            site_id = await self._get_integration_site_id()
        cache_key = f"{CACHE_PREFIX_INTEGRATION_FIREWALL_ZONES}_{site_id}"
        cached = self._connection.get_cached(cache_key)
        if isinstance(cached, list):
            return cached

        zones: List[Dict[str, Any]] = []
        offset = 0
        while True:
            result = await self._request_integration_api(
                "get",
                f"/v1/sites/{site_id}/firewall/zones",
                params={"limit": str(INTEGRATION_API_PAGE_SIZE), "offset": str(offset)},
            )
            page = result.get("data", []) if isinstance(result, dict) else []
            if not isinstance(page, list):
                page = []
            page = [zone for zone in page if isinstance(zone, dict)]
            zones.extend(page)

            total_count = result.get("totalCount") if isinstance(result, dict) else None
            if not page or not isinstance(total_count, int) or len(zones) >= total_count:
                break
            offset += len(page)

        self._connection._update_cache(cache_key, zones)
        return zones

    @staticmethod
    def _zone_match_values(zone: Dict[str, Any]) -> set[str]:
        values: set[str] = set()
        for key in ("id", "_id", "name", "key", "zoneKey", "zone_key"):
            value = zone.get(key)
            if value is not None:
                values.add(str(value).strip().lower())
        return values

    async def _resolve_integration_firewall_zone_id(
        self,
        zone_id: str,
        integration_zones: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Translate local V2 firewall zone IDs to integration API zone IDs."""
        candidate = str(zone_id).strip()
        if not candidate:
            return candidate

        if integration_zones is None:
            integration_zones = await self._get_integration_firewall_zones()
        wanted = candidate.lower()
        direct = next((z for z in integration_zones if wanted in self._zone_match_values(z)), None)
        if direct and direct.get("id"):
            return str(direct["id"])

        try:
            local_zones = await self.get_firewall_zones()
        except Exception:
            local_zones = []
        local = next(
            (z for z in local_zones if isinstance(z, dict) and wanted in self._zone_match_values(z)),
            None,
        )
        if not local:
            return candidate

        local_values = self._zone_match_values(local)
        translated = next(
            (z for z in integration_zones if local_values & self._zone_match_values(z) and z.get("id")),
            None,
        )
        return str(translated["id"]) if translated and translated.get("id") else candidate

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

        Delegates to ``update_firewall_policy`` so the controller PUT is a
        deep-merge of the new ``enabled`` flag into the full policy object.
        The controller rejects PUTs that omit any required field
        (action, ipVersion, name, source, destination, schedule), so a
        partial payload of ``{"enabled": ...}`` cannot be sent on its own.

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

            return await self.update_firewall_policy(policy_id, {"enabled": new_state})
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

    async def get_firewall_policy_ordering(
        self,
        source_firewall_zone_id: str,
        destination_firewall_zone_id: str,
    ) -> Dict[str, Any]:
        """Return user-defined firewall policy ordering for a zone pair.

        UniFi's V2 policy ``index`` is controller-assigned. Reordering is a
        separate official API surface scoped to a source/destination zone pair.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        site_id = await self._get_integration_site_id()
        integration_zones = await self._get_integration_firewall_zones(site_id)
        source_integration_zone_id = await self._resolve_integration_firewall_zone_id(
            source_firewall_zone_id,
            integration_zones,
        )
        destination_integration_zone_id = await self._resolve_integration_firewall_zone_id(
            destination_firewall_zone_id,
            integration_zones,
        )
        params = {
            "sourceFirewallZoneId": source_integration_zone_id,
            "destinationFirewallZoneId": destination_integration_zone_id,
        }
        cache_key = (
            f"{CACHE_PREFIX_FIREWALL_POLICY_ORDERING}_"
            f"{source_integration_zone_id}_{destination_integration_zone_id}_{self._connection.site}"
        )
        cached_data: Optional[Dict[str, Any]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            result = await self._request_integration_api(
                "get",
                f"/v1/sites/{site_id}/firewall/policies/ordering",
                params=params,
            )
            self._connection._update_cache(cache_key, result)
            return result
        except Exception as e:
            logger.error("Error getting firewall policy ordering: %s", e, exc_info=True)
            raise

    async def reorder_firewall_policies(
        self,
        source_firewall_zone_id: str,
        destination_firewall_zone_id: str,
        ordered_firewall_policy_ids: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """Reorder user-defined firewall policies for a zone pair."""
        self._requested_firewall_policy_ids(ordered_firewall_policy_ids)

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        site_id = await self._get_integration_site_id()
        integration_zones = await self._get_integration_firewall_zones(site_id)
        source_integration_zone_id = await self._resolve_integration_firewall_zone_id(
            source_firewall_zone_id,
            integration_zones,
        )
        destination_integration_zone_id = await self._resolve_integration_firewall_zone_id(
            destination_firewall_zone_id,
            integration_zones,
        )
        params = {
            "sourceFirewallZoneId": source_integration_zone_id,
            "destinationFirewallZoneId": destination_integration_zone_id,
        }
        payload = {"orderedFirewallPolicyIds": ordered_firewall_policy_ids}
        cache_key = (
            f"{CACHE_PREFIX_FIREWALL_POLICY_ORDERING}_"
            f"{source_integration_zone_id}_{destination_integration_zone_id}_{self._connection.site}"
        )

        try:
            # Reorder is a live mutation; validate against fresh controller
            # state instead of a cached read to avoid TOCTOU policy drops.
            current_ordering = await self._request_integration_api(
                "get",
                f"/v1/sites/{site_id}/firewall/policies/ordering",
                params=params,
            )
            self._connection._update_cache(cache_key, current_ordering)
            self._validate_firewall_policy_ordering_matches_current(
                ordered_firewall_policy_ids,
                current_ordering,
            )

            response = await self._request_integration_api(
                "put",
                f"/v1/sites/{site_id}/firewall/policies/ordering",
                params=params,
                data=payload,
            )
            self._connection._invalidate_cache(cache_key)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_POLICIES}_True_{self._connection.site}")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_POLICIES}_False_{self._connection.site}")
            return response if isinstance(response, dict) else {}
        except Exception as e:
            logger.error("Error reordering firewall policies: %s", e, exc_info=True)
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

            logger.debug("Updating port forward %s with full data: %s", rule_id, updated_data)

            api_request = ApiRequest(
                method="put",
                path=f"/rest/portforward/{rule_id}",  # V1 endpoint path, corrected
                data=updated_data,
            )

            await self._connection.request(api_request)

            # Invalidate cache
            cache_key = f"{CACHE_PREFIX_PORT_FORWARDS}_{self._connection.site}"
            self._connection._invalidate_cache(cache_key)

            refetched_obj = await self.get_port_forward_by_id(rule_id)
            refetched = refetched_obj.raw if hasattr(refetched_obj, "raw") else None
            if not isinstance(refetched, dict):
                raise UniFiOperationError(f"Could not verify port forward '{rule_id}' after update")

            unpersisted = [
                key
                for key, requested in updates.items()
                if rule_to_update_obj.raw.get(key) != requested
                and refetched.get(key) == rule_to_update_obj.raw.get(key)
            ]
            if unpersisted:
                raise UniFiOperationError(
                    f"Controller accepted the request but did not persist field(s): {', '.join(sorted(unpersisted))}"
                )

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
                       name (str), dst_port (str), fwd_port (str), fwd (str),
                       proto (str, optional), enabled (bool, optional), etc.

        Returns:
            The created rule data dict, or None if creation failed.
        """
        required_keys = {"name", "dst_port", "fwd_port", "fwd"}
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
            # list [{...}] (UDM-SE 8.4.x and similar).
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
        validate_policy_port_targeting(policy_data)
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        # Normalized here rather than at the tool: the MCP tool and the apps/api
        # dispatch both hand this dict straight through, so to_controller_create
        # is not on the path. A CLIENT endpoint carries a client_macs list.
        policy_data = {
            k: (_normalize_endpoint_macs(v) if k in ("source", "destination") else v) for k, v in policy_data.items()
        }

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

    # ---- Firewall Zone CRUD (integration API) ----

    async def _get_v2_zones_full(self) -> List[Dict[str, Any]]:
        """Return the full V2 firewall-zone list (``/firewall/zone``).

        ``get_firewall_zones()`` reads ``/firewall/zone-matrix``, which strips
        ``external_id`` and ``default_zone``. Zone writes go through the
        integration API (UUID ``id``) while ``unifi_list_firewall_zones`` and
        ``firewall_zone_id`` use the V2 ``_id``, so the bridge needs the full
        shape that carries ``external_id`` (== integration ``id``).
        """
        cache_key = f"{CACHE_PREFIX_FIREWALL_ZONES}_full_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if isinstance(cached, list):
            return cached
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        api_request = ApiRequestV2(method="get", path="/firewall/zone")
        resp = await self._connection.request(api_request)
        data = resp if isinstance(resp, list) else (resp.get("data", []) if isinstance(resp, dict) else [])
        data = [zone for zone in data if isinstance(zone, dict)]
        self._connection._update_cache(cache_key, data)
        return data

    async def _resolve_zone_record(self, zone_id: str) -> Dict[str, Any]:
        """Resolve a V2 firewall-zone ID to its full V2 record."""
        candidate = str(zone_id).strip()
        if not candidate:
            raise UniFiNotFoundError("firewall_zone", zone_id)
        zones = await self._get_v2_zones_full()
        for zone in zones:
            identifiers = {str(zone[key]) for key in ("_id", "id") if zone.get(key) is not None}
            if candidate in identifiers:
                return zone
        raise UniFiNotFoundError("firewall_zone", zone_id)

    @staticmethod
    def _resolve_integration_zone_record(
        v2_zone: Dict[str, Any],
        integration_zones: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Resolve a V2 zone to its Integration API record without crossing ID spaces."""
        external_id = v2_zone.get("external_id")
        if external_id is not None:
            direct = next(
                (zone for zone in integration_zones if str(zone.get("id")) == str(external_id)),
                None,
            )
            if direct is not None:
                return direct

        # Zone names are the established 1:1 bridge between these API surfaces.
        # Fail closed if the mapping is missing or ambiguous rather than sending a
        # V2 ObjectID to an Integration API endpoint.
        name = str(v2_zone.get("name") or "").strip().casefold()
        by_name = [
            zone for zone in integration_zones if name and str(zone.get("name") or "").strip().casefold() == name
        ]
        if len(by_name) == 1 and by_name[0].get("id"):
            return by_name[0]

        v2_id = v2_zone.get("_id") or v2_zone.get("id") or "unknown"
        raise UniFiOperationError(f"Could not map V2 firewall zone '{v2_id}' to exactly one Integration API zone")

    def _invalidate_firewall_zone_caches(self, site_id: str) -> None:
        """Invalidate every cache whose contents or keys depend on firewall zones."""
        site = self._connection.site
        self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_ZONES}_{site}")
        self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_ZONES}_full_{site}")
        self._connection._invalidate_cache(f"{CACHE_PREFIX_INTEGRATION_FIREWALL_ZONES}_{site_id}")
        self._connection._invalidate_cache(CACHE_PREFIX_FIREWALL_POLICY_ORDERING)

    async def _wait_for_created_v2_zone(self, integration_id: str) -> Dict[str, Any]:
        """Wait briefly for an Integration-created zone to appear in the V2 family."""
        for attempt in range(FIREWALL_ZONE_WRITE_VERIFY_ATTEMPTS):
            self._connection._invalidate_cache(f"{CACHE_PREFIX_FIREWALL_ZONES}_full_{self._connection.site}")
            zones = await self._get_v2_zones_full()
            match = next(
                (zone for zone in zones if str(zone.get("external_id")) == str(integration_id)),
                None,
            )
            if match is not None:
                return match
            if attempt + 1 < FIREWALL_ZONE_WRITE_VERIFY_ATTEMPTS:
                await asyncio.sleep(FIREWALL_ZONE_WRITE_VERIFY_DELAY_SECONDS * (attempt + 1))
        raise UniFiOperationError("Created firewall zone was not found in the V2 read-back")

    async def _wait_for_zone_update(
        self,
        *,
        site_id: str,
        v2_id: str,
        integration_id: str,
        expected_name: str,
        expected_network_ids: List[Any],
    ) -> None:
        """Verify a rename on both API surfaces without accepting a silent no-op."""
        for attempt in range(FIREWALL_ZONE_WRITE_VERIFY_ATTEMPTS):
            self._invalidate_firewall_zone_caches(site_id)
            integration_zones = await self._get_integration_firewall_zones(site_id)
            integration_zone = next(
                (zone for zone in integration_zones if str(zone.get("id")) == str(integration_id)),
                None,
            )
            v2_zones = await self._get_v2_zones_full()
            v2_zone = next(
                (zone for zone in v2_zones if str(zone.get("_id")) == str(v2_id)),
                None,
            )
            if (
                integration_zone is not None
                and integration_zone.get("name") == expected_name
                and integration_zone.get("networkIds") == expected_network_ids
                and v2_zone is not None
                and v2_zone.get("name") == expected_name
            ):
                return
            if attempt + 1 < FIREWALL_ZONE_WRITE_VERIFY_ATTEMPTS:
                await asyncio.sleep(FIREWALL_ZONE_WRITE_VERIFY_DELAY_SECONDS * (attempt + 1))
        raise UniFiOperationError(
            f"Controller accepted the request but did not persist firewall zone rename to '{expected_name}'"
        )

    async def _wait_for_zone_deletion(
        self,
        *,
        site_id: str,
        v2_id: str,
        integration_id: str,
    ) -> None:
        """Verify a deleted zone disappears from both ID namespaces."""
        for attempt in range(FIREWALL_ZONE_WRITE_VERIFY_ATTEMPTS):
            self._invalidate_firewall_zone_caches(site_id)
            integration_zones = await self._get_integration_firewall_zones(site_id)
            v2_zones = await self._get_v2_zones_full()
            integration_exists = any(str(zone.get("id")) == str(integration_id) for zone in integration_zones)
            v2_exists = any(str(zone.get("_id")) == str(v2_id) for zone in v2_zones)
            if not integration_exists and not v2_exists:
                return
            if attempt + 1 < FIREWALL_ZONE_WRITE_VERIFY_ATTEMPTS:
                await asyncio.sleep(FIREWALL_ZONE_WRITE_VERIFY_DELAY_SECONDS * (attempt + 1))
        raise UniFiOperationError(f"Controller accepted the request but firewall zone '{v2_id}' is still present")

    async def get_firewall_zone_by_id(self, zone_id: str) -> Dict[str, Any]:
        """Return one full V2 firewall-zone record by V2 ID."""
        return await self._resolve_zone_record(zone_id)

    async def create_firewall_zone(self, name: str) -> Dict[str, Any]:
        """Create a firewall zone via the integration API.

        The V2 ``POST /firewall/zone`` silently no-ops, so writes use the
        integration API (requires ``UNIFI_API_KEY``). Returns the zone in the
        V2 read shape so the caller receives the 24-hex ``_id`` that
        ``firewall_zone_id`` expects.
        """
        name = name.strip()
        if not name:
            raise ValueError("Firewall zone name cannot be empty")
        self._require_integration_api_key("Creating a firewall zone")
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        site_id = await self._get_integration_site_id()
        created = await self._request_integration_api(
            "post",
            f"/v1/sites/{site_id}/firewall/zones",
            data={"name": name, "networkIds": []},
        )
        integration_id = created.get("id") if isinstance(created, dict) else None
        if not integration_id:
            raise RuntimeError("Integration API did not return a firewall zone id")
        self._invalidate_firewall_zone_caches(site_id)
        return await self._wait_for_created_v2_zone(str(integration_id))

    async def update_firewall_zone(self, zone_id: str, name: str) -> bool:
        """Update a firewall zone's name via the integration API."""
        name = name.strip()
        if not name:
            raise ValueError("Firewall zone name cannot be empty")
        self._require_integration_api_key("Renaming a firewall zone")
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        zone = await self._resolve_zone_record(zone_id)
        if zone.get("default_zone"):
            raise UniFiOperationError(f"Cannot rename system-defined firewall zone '{zone.get('name')}'")
        site_id = await self._get_integration_site_id()
        integration_zones = await self._get_integration_firewall_zones(site_id)
        integration_zone = self._resolve_integration_zone_record(zone, integration_zones)
        integration_id = integration_zone["id"]
        network_ids = integration_zone.get("networkIds")
        if not isinstance(network_ids, list):
            raise UniFiOperationError(
                f"Integration API firewall zone '{integration_id}' did not include networkIds; rename aborted"
            )
        await self._request_integration_api(
            "put",
            f"/v1/sites/{site_id}/firewall/zones/{integration_id}",
            data={"name": name, "networkIds": list(network_ids)},
        )
        v2_id = str(zone.get("_id") or zone.get("id"))
        await self._wait_for_zone_update(
            site_id=site_id,
            v2_id=v2_id,
            integration_id=str(integration_id),
            expected_name=name,
            expected_network_ids=list(network_ids),
        )
        return True

    async def delete_firewall_zone(self, zone_id: str) -> bool:
        """Delete a firewall zone via the integration API.

        ``SYSTEM_DEFINED`` zones (``default_zone`` in the V2 shape) are refused.
        """
        self._require_integration_api_key("Deleting a firewall zone")
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        zone = await self._resolve_zone_record(zone_id)
        if zone.get("default_zone"):
            raise UniFiOperationError(f"Cannot delete system-defined firewall zone '{zone.get('name')}'")
        site_id = await self._get_integration_site_id()
        integration_zones = await self._get_integration_firewall_zones(site_id)
        integration_zone = self._resolve_integration_zone_record(zone, integration_zones)
        integration_id = integration_zone["id"]
        await self._request_integration_api(
            "delete",
            f"/v1/sites/{site_id}/firewall/zones/{integration_id}",
        )
        v2_id = str(zone.get("_id") or zone.get("id"))
        await self._wait_for_zone_deletion(
            site_id=site_id,
            v2_id=v2_id,
            integration_id=str(integration_id),
        )
        return True

    # ---- Legacy Firewall Rules and Groups (v1 REST) ----

    async def get_legacy_firewall_rules(self) -> List[Dict[str, Any]]:
        """Get legacy pre-zone-based firewall rules for the current UniFi site."""
        cache_key = f"{CACHE_PREFIX_LEGACY_FIREWALL_RULES}_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if cached is not None:
            return cached

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequest(method="get", path="/rest/firewallrule")
            response = await self._connection.request(api_request)
            data = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
            data = [rule for rule in data if isinstance(rule, dict)]

            self._connection._update_cache(cache_key, data)
            return data
        except Exception as e:
            logger.error("Error getting legacy firewall rules: %s", e)
            raise

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
