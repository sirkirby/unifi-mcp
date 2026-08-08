import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequest, ApiRequestV2
from aiounifi.models.wlan import Wlan

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.models.networks import DELETABLE_PURPOSES, UNSAFE_GUEST_PURPOSE_ERROR
from unifi_core.network.models.wlans import apply_update_dependencies as apply_wlan_update_dependencies
from unifi_core.write_verification import WriteVerificationResult, failed_write, noop_write, verify_write

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_NETWORKS = "networks"
CACHE_PREFIX_WLANS = "wlans"
CACHE_PREFIX_AP_GROUPS = "ap_groups"

# Legacy configs omit default-true flags on persist: an absent 'enabled' key
# on read-back means enabled, not that the write was dropped.
_ABSENT_VALUE_DEFAULTS = {"enabled": True}

# Fields the controller never echoes back verbatim, so a re-read cannot confirm
# them: write-only/redacted secrets, plus ap_group_mode, which the controller
# derives from the ap_group_ids selection (a "groups" request covering every AP
# is echoed back as "all"). Excluded from post-write persistence verification.
_UNVERIFIABLE_UPDATE_KEYS = frozenset(
    {
        "x_passphrase",
        "x_password",
        "sae_psk",
        "private_preshared_keys",
        "x_iapp_key",
        "password",
        "ap_group_mode",
    }
)


def _unpersisted_fields(before: Dict[str, Any], after: Dict[str, Any], requested: Dict[str, Any]) -> List[str]:
    """Return requested keys that were meant to change but did not move.

    A field counts as *not persisted* only when it was actually being changed
    (requested value differs from the pre-write value) yet the re-read value is
    still identical to the pre-write value. Fields the controller normalizes to a
    different-but-non-original value are treated as persisted (avoids false
    positives), and write-only/redacted fields are skipped entirely.
    """
    stuck: List[str] = []
    for key, want in requested.items():
        if key in _UNVERIFIABLE_UPDATE_KEYS:
            continue
        prev = before.get(key)
        if prev == want:
            continue  # no real change requested for this field
        if after.get(key) == prev:
            stuck.append(key)
    return stuck


def _apply_minrate_dependencies(update_data: Dict[str, Any]) -> Dict[str, Any]:
    """Backward-compatible alias for shared WLAN update expansion."""
    return apply_wlan_update_dependencies(update_data)


class NetworkManager:
    """Manages network (LAN/VLAN) and WLAN operations on the Unifi Controller."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the Network Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def get_networks(self) -> List[Dict[str, Any]]:
        """Get list of networks (LAN/VLAN) for the current site."""
        cache_key = f"{CACHE_PREFIX_NETWORKS}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            # Revert back to V1 API endpoint for listing networks
            logger.debug("Fetching networks using V1 endpoint /rest/networkconf")
            api_request = ApiRequest(method="get", path="/rest/networkconf")

            # Call the request method
            response = await self._connection.request(api_request)

            # V1 response is typically a list within a 'data' key, but aiounifi might unpack it
            # Check common patterns
            networks_data = []
            if isinstance(response, dict) and "data" in response and isinstance(response["data"], list):
                networks_data = response["data"]
            elif isinstance(response, list):  # aiounifi might return the list directly
                networks_data = response
            else:
                logger.error(
                    "Unexpected response format from /rest/networkconf: %s. Response: %s", type(response), response
                )
                raise RuntimeError("Controller returned an invalid network list response")

            # Basic check to ensure we got a list of dicts
            if not isinstance(networks_data, list) or not all(isinstance(item, dict) for item in networks_data):
                logger.error(
                    "Unexpected data structure in network list: %s. Expected list of dicts. Data: %s",
                    type(networks_data),
                    networks_data,
                )
                raise RuntimeError("Controller returned malformed entries in the network list response")

            # Return the list of network dictionaries
            networks = networks_data

            self._connection._update_cache(cache_key, networks)
            return networks
        except Exception as e:
            # Log original error for V1 endpoint failure
            logger.error("Error getting networks via V1 /rest/networkconf: %s", e, exc_info=True)
            raise

    async def get_network_details(self, network_id: str) -> Dict[str, Any]:
        """Get detailed information for a specific network.

        Raises:
            UniFiNotFoundError: If the network does not exist.
        """
        networks = await self.get_networks()
        network = next((n for n in networks if n.get("_id") == network_id), None)
        if network is None:
            raise UniFiNotFoundError("network", network_id)
        return network

    async def create_network(self, network_data: Dict[str, Any]) -> WriteVerificationResult:
        """Create a network and verify its exact persisted field values."""
        try:
            required_fields = ["name", "purpose"]
            for field in required_fields:
                if field not in network_data:
                    return failed_write(
                        f"Missing required field '{field}' for network creation",
                        operation="create",
                    )
            if network_data.get("purpose") == "guest":
                return failed_write(UNSAFE_GUEST_PURPOSE_ERROR, operation="create")

            api_request = ApiRequest(method="post", path="/rest/networkconf", data=network_data)
            response = await self._connection.request(api_request)
            logger.info("Create command sent for network '%s'", network_data.get("name"))
            self._connection._invalidate_cache(f"{CACHE_PREFIX_NETWORKS}_{self._connection.site}")

            created = (
                response[0]
                if isinstance(response, list) and response and isinstance(response[0], dict)
                else response
                if isinstance(response, dict)
                else None
            )
            network_id = created.get("_id") if created else None
            if not network_id:
                logger.warning("Could not extract created network data from response: %s", response)
                return failed_write(
                    "Controller accepted the network create request but did not return a resource ID; "
                    "persistence could not be verified.",
                    operation="create",
                    mutation_applied=True,
                    resource=created,
                )

            try:
                refetched = await self.get_network_details(network_id)
            except Exception as e:
                logger.error("Created network %s could not be re-read: %s", network_id, e, exc_info=True)
                return failed_write(
                    "Controller accepted the network create request but the created resource "
                    f"could not be re-read: {e}",
                    operation="create",
                    mutation_applied=True,
                    resource=created,
                    metadata={"network_id": network_id},
                )

            return verify_write(
                operation="create",
                requested=network_data,
                after=refetched,
                unverifiable_fields=_UNVERIFIABLE_UPDATE_KEYS,
                absent_value_defaults=_ABSENT_VALUE_DEFAULTS,
                metadata={"network_id": network_id},
            )
        except Exception as e:
            logger.error("Error creating network: %s", e, exc_info=True)
            raise

    async def update_network(self, network_id: str, update_data: Dict[str, Any]) -> WriteVerificationResult:
        """Update a network configuration by merging updates with existing data.

        Args:
            network_id: ID of the network to update
            update_data: Dictionary of fields to update

        Returns:
            Structured exact field-verification result with post-write state.
        """
        if not update_data:
            logger.debug("No update data provided for network %s; no controller call required.", network_id)
            return noop_write(operation="update", metadata={"network_id": network_id})
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        if update_data.get("purpose") == "guest":
            return failed_write(UNSAFE_GUEST_PURPOSE_ERROR, operation="update")

        try:
            # 1. Existence check; raises UniFiNotFoundError on miss.
            existing_network = await self.get_network_details(network_id)

            # 2. Merge updates into existing data (deep merge preserves nested sub-objects)
            merged_data = deep_merge(existing_network, update_data)

            # 3. Send the full merged data
            api_request = ApiRequest(
                method="put",
                path=f"/rest/networkconf/{network_id}",
                data=merged_data,  # Send full object
            )
            await self._connection.request(api_request)
            logger.info("Update command sent for network %s with merged data.", network_id)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_NETWORKS}_{self._connection.site}")

            # Verify the controller actually persisted the change. Some controller
            # versions answer the legacy /rest/networkconf PUT with rc:ok but
            # silently ignore the write, so a non-raising request() is not
            # sufficient evidence of success.
            try:
                refetched = await self.get_network_details(network_id)
            except Exception as e:
                return failed_write(
                    f"Controller accepted the network update but the resource could not be re-read: {e}",
                    operation="update",
                    mutation_applied=True,
                    metadata={"network_id": network_id, "details_before_attempt": existing_network},
                )
            return verify_write(
                operation="update",
                requested=update_data,
                before=existing_network,
                after=refetched,
                unverifiable_fields=_UNVERIFIABLE_UPDATE_KEYS,
                absent_value_defaults=_ABSENT_VALUE_DEFAULTS,
                metadata={"network_id": network_id},
            )
        except Exception as e:
            logger.error("Error updating network %s: %s", network_id, e, exc_info=True)
            raise

    async def delete_network(self, network_id: str) -> bool:
        """Delete a LAN/VLAN network and verify it is absent afterward."""
        try:
            existing = await self.get_network_details(network_id)
            purpose = existing.get("purpose")
            if purpose not in DELETABLE_PURPOSES:
                hint = " Use unifi_delete_vpn_client for VPN client configurations." if purpose == "vpn-client" else ""
                raise ValueError(
                    f"Refusing to delete network {network_id}: purpose '{purpose}' is not a LAN/VLAN network. "
                    "Deleting WAN or VPN networkconf entries can sever gateway connectivity." + hint
                )
            api_request = ApiRequest(method="delete", path=f"/rest/networkconf/{network_id}")
            await self._connection.request(api_request)
            logger.info("Delete command sent for network %s", network_id)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_NETWORKS}_{self._connection.site}")
            networks = await self.get_networks()
            if any(network.get("_id") == network_id for network in networks):
                raise RuntimeError("Controller accepted the delete request but the network still exists")
            return True
        except Exception as e:
            logger.error("Error deleting network %s: %s", network_id, e, exc_info=True)
            raise

    async def get_wlans(self) -> List[Wlan]:
        """Get list of wireless networks (WLANs) for the current site."""
        cache_key = f"{CACHE_PREFIX_WLANS}_{self._connection.site}"
        cached_data: Optional[List[Wlan]] = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequest(method="get", path="/rest/wlanconf")
            response = await self._connection.request(api_request)
            if not isinstance(response, list) or not all(isinstance(item, dict) for item in response):
                raise RuntimeError("Controller returned an invalid WLAN list response")
            wlans: List[Wlan] = [Wlan(raw_wlan) for raw_wlan in response]
            self._connection._update_cache(cache_key, wlans)
            return wlans
        except Exception as e:
            logger.error("Error getting WLANs: %s", e)
            raise

    async def get_wlan_details(self, wlan_id: str) -> Dict[str, Any]:
        """Get detailed information for a specific wireless network as a dictionary.

        Raises:
            UniFiNotFoundError: If the WLAN does not exist.
        """
        wlans = await self.get_wlans()
        wlan_obj: Optional[Wlan] = next(
            (w for w in wlans if isinstance(w.raw, dict) and w.raw.get("_id") == wlan_id),
            None,
        )
        if wlan_obj is None or not hasattr(wlan_obj, "raw") or wlan_obj.raw is None:
            raise UniFiNotFoundError("wlan", wlan_id)
        return wlan_obj.raw

    async def create_wlan(self, wlan_data: Dict[str, Any]) -> WriteVerificationResult:
        """Create a WLAN and verify its exact persisted field values."""
        try:
            for field in ("name", "security", "enabled"):
                if field not in wlan_data:
                    return failed_write(f"Missing required field '{field}' for WLAN creation", operation="create")
            if wlan_data.get("security") != "open" and "x_passphrase" not in wlan_data:
                return failed_write(
                    f"Missing required field 'x_passphrase' for WLAN security type '{wlan_data.get('security')}'",
                    operation="create",
                )

            api_request = ApiRequest(method="post", path="/rest/wlanconf", data=wlan_data)
            response = await self._connection.request(api_request)
            logger.info("Create command sent for WLAN '%s'", wlan_data.get("name"))
            self._connection._invalidate_cache(f"{CACHE_PREFIX_WLANS}_{self._connection.site}")

            created = (
                response[0]
                if isinstance(response, list) and response and isinstance(response[0], dict)
                else response
                if isinstance(response, dict)
                else None
            )
            wlan_id = created.get("_id") if created else None
            if not wlan_id:
                logger.warning("Could not extract created WLAN data from response: %s", response)
                return failed_write(
                    "Controller accepted the WLAN create request but did not return a resource ID; "
                    "persistence could not be verified.",
                    operation="create",
                    mutation_applied=True,
                    resource=created,
                )

            try:
                refetched = await self.get_wlan_details(wlan_id)
            except Exception as e:
                logger.error("Created WLAN %s could not be re-read: %s", wlan_id, e, exc_info=True)
                return failed_write(
                    f"Controller accepted the WLAN create request but the created resource could not be re-read: {e}",
                    operation="create",
                    mutation_applied=True,
                    resource=created,
                    metadata={"wlan_id": wlan_id},
                )

            return verify_write(
                operation="create",
                requested=wlan_data,
                after=refetched,
                unverifiable_fields=_UNVERIFIABLE_UPDATE_KEYS,
                absent_value_defaults=_ABSENT_VALUE_DEFAULTS,
                metadata={"wlan_id": wlan_id},
            )
        except Exception as e:
            logger.error("Error creating WLAN: %s", e, exc_info=True)
            raise

    async def update_wlan(self, wlan_id: str, update_data: Dict[str, Any]) -> WriteVerificationResult:
        """Update a WLAN configuration by merging updates with existing data.

        Args:
            wlan_id: ID of the WLAN to update
            update_data: Dictionary of fields to update

        Returns:
            Structured exact field-verification result with post-write state.
        """
        if not update_data:
            logger.debug("No update data provided for WLAN %s; no controller call required.", wlan_id)
            return noop_write(operation="update", metadata={"wlan_id": wlan_id})
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            # 1. Existence check; raises UniFiNotFoundError on miss.
            existing_wlan = await self.get_wlan_details(wlan_id)

            # 2. A manual min-rate request is silently recomputed away unless the
            #    rate mode is "manual" and the band is enabled; inject those
            #    dependencies so a rate-only update actually persists.
            update_data = _apply_minrate_dependencies(update_data)

            # 3. Merge updates (deep merge preserves nested sub-objects)
            merged_data = deep_merge(existing_wlan, update_data)

            # 4. Send the full merged data
            api_request = ApiRequest(
                method="put",
                path=f"/rest/wlanconf/{wlan_id}",
                data=merged_data,  # Send full object
            )
            await self._connection.request(api_request)
            logger.info("Update command sent for WLAN %s with merged data.", wlan_id)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_WLANS}_{self._connection.site}")

            # Verify the controller actually persisted the change. Some controller
            # / UniFi OS versions answer the legacy /rest/wlanconf PUT with rc:ok
            # but silently ignore the write, so a non-raising request() is not
            # sufficient evidence of success.
            try:
                refetched = await self.get_wlan_details(wlan_id)
            except Exception as e:
                return failed_write(
                    f"Controller accepted the WLAN update but the resource could not be re-read: {e}",
                    operation="update",
                    mutation_applied=True,
                    metadata={"wlan_id": wlan_id, "details_before_attempt": existing_wlan},
                )
            return verify_write(
                operation="update",
                requested=update_data,
                before=existing_wlan,
                after=refetched,
                unverifiable_fields=_UNVERIFIABLE_UPDATE_KEYS,
                absent_value_defaults=_ABSENT_VALUE_DEFAULTS,
                metadata={"wlan_id": wlan_id},
            )
        except Exception as e:
            logger.error("Error updating WLAN %s: %s", wlan_id, e, exc_info=True)
            raise

    async def delete_wlan(self, wlan_id: str) -> bool:
        """Delete a wireless network.

        Args:
            wlan_id: ID of the WLAN to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            await self.get_wlan_details(wlan_id)
            api_request = ApiRequest(method="delete", path=f"/rest/wlanconf/{wlan_id}")
            await self._connection.request(api_request)
            logger.info("Delete command sent for WLAN %s", wlan_id)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_WLANS}_{self._connection.site}")
            wlans = await self.get_wlans()
            if any(wlan.raw.get("_id") == wlan_id for wlan in wlans):
                raise RuntimeError("Controller accepted the delete request but the WLAN still exists")
            return True
        except Exception as e:
            logger.error("Error deleting WLAN %s: %s", wlan_id, e)
            raise

    async def toggle_wlan(self, wlan_id: str) -> bool:
        """Toggle a wireless network on/off.

        Args:
            wlan_id: ID of the WLAN to toggle

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # raises UniFiNotFoundError on miss
            wlan = await self.get_wlan_details(wlan_id)

            new_state = not wlan.get("enabled", False)
            update_payload = {"enabled": new_state}

            api_request = ApiRequest(method="put", path=f"/rest/wlanconf/{wlan_id}", data=update_payload)
            await self._connection.request(api_request)
            logger.info(
                "Toggle command sent for WLAN %s (new state: %s)", wlan_id, "enabled" if new_state else "disabled"
            )
            self._connection._invalidate_cache(f"{CACHE_PREFIX_WLANS}_{self._connection.site}")
            return True
        except Exception as e:
            logger.error("Error toggling WLAN %s: %s", wlan_id, e)
            raise

    async def list_ap_groups(self) -> List[Dict[str, Any]]:
        """List all AP groups.

        Returns:
            List of AP group dictionaries.
        """
        cache_key = f"{CACHE_PREFIX_AP_GROUPS}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequestV2(method="get", path="/apgroups")
            response = await self._connection.request(api_request)

            groups = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )

            self._connection._update_cache(cache_key, groups, timeout=300)
            return groups
        except Exception as e:
            logger.error("Error listing AP groups: %s", e)
            raise

    async def get_ap_group_details(self, group_id: str) -> Dict[str, Any]:
        """Get details of a specific AP group by ID.

        Raises:
            UniFiNotFoundError: If the AP group does not exist.
        """
        # v2 /apgroups/{id} returns 405 — fetch all and filter
        groups = await self.list_ap_groups()
        for group in groups:
            if group.get("_id") == group_id:
                return group
        raise UniFiNotFoundError("ap_group", group_id)

    async def create_ap_group(self, group_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new AP group.

        Args:
            group_data: Dictionary containing the AP group configuration.

        Returns:
            The created AP group dictionary, or None on failure.
        """
        try:
            api_request = ApiRequestV2(method="post", path="/apgroups", data=group_data)
            response = await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_AP_GROUPS)

            if isinstance(response, dict) and ("id" in response or "_id" in response):
                return response
            elif isinstance(response, dict) and "data" in response:
                return response["data"]
            elif isinstance(response, list) and len(response) > 0:
                return response[0] if isinstance(response[0], dict) else None
            elif response is None or response == "":
                logger.info("Create AP group returned empty response, verifying via list")
                groups = await self.list_ap_groups()
                created = next(
                    (g for g in groups if g.get("name") == group_data.get("name")),
                    None,
                )
                return created
            else:
                logger.error("Unexpected response creating AP group: %s %s", type(response), response)
                return None
        except Exception as e:
            logger.error("Error creating AP group: %s", e, exc_info=True)
            raise

    async def update_ap_group(self, group_id: str, update_data: Dict[str, Any]) -> bool:
        """Update an existing AP group by merging updates with current state.

        Args:
            group_id: The ID of the AP group to update.
            update_data: Dictionary of fields to update (partial is fine).

        Returns:
            True on success, False on failure.
        """
        try:
            # raises UniFiNotFoundError on miss
            existing = await self.get_ap_group_details(group_id)
            if not update_data:
                return True

            merged_data = deep_merge(existing, update_data)

            api_request = ApiRequestV2(method="put", path=f"/apgroups/{group_id}", data=merged_data)
            await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_AP_GROUPS)

            # Verify the controller actually persisted the change; a non-raising
            # request() is not sufficient evidence the write was applied.
            refetched = await self.get_ap_group_details(group_id)
            stuck = _unpersisted_fields(existing, refetched, update_data)
            if stuck:
                logger.error(
                    "AP group %s update not persisted by controller; fields unchanged: %s",
                    group_id,
                    ", ".join(sorted(stuck)),
                )
                return False
            return True
        except Exception as e:
            logger.error("Error updating AP group %s: %s", group_id, e, exc_info=True)
            raise

    async def delete_ap_group(self, group_id: str) -> bool:
        """Delete an AP group.

        Args:
            group_id: The ID of the AP group to delete.

        Returns:
            True on success, False on failure.
        """
        try:
            api_request = ApiRequestV2(method="delete", path=f"/apgroups/{group_id}")
            await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_AP_GROUPS)
            return True
        except Exception as e:
            logger.error("Error deleting AP group %s: %s", group_id, e, exc_info=True)
            raise
