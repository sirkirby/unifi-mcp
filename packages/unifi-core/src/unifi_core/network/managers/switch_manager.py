"""Manager for UniFi switch management operations.

Provides access to switch port profiles, port assignments, live port
statistics, LLDP neighbor discovery, switch capabilities, port mirroring,
link aggregation, PoE control, STP configuration, and jumbo frames.

API endpoints:
  Port profiles:    GET/POST/PUT/DELETE /rest/portconf[/{id}]     (v1 REST)
  Device config:    PUT /rest/device/{id}                          (v1 REST — port_overrides, STP, jumbo)
  Device stats:     GET /stat/device/{mac}                         (v1 stat — port_table, lldp_table, switch_caps)
  Device commands:  POST /cmd/devmgr                               (v1 cmd — power-cycle, locate, force-provision)
"""

import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_PORT_PROFILES = "port_profiles"


class SwitchManager:
    """Manages switch-related operations on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    # ---- Port Profiles ----

    async def get_port_profiles(self) -> List[Dict[str, Any]]:
        """Get all port profiles (port configurations).

        Returns:
            List of port profile dictionaries.
        """
        cache_key = f"{CACHE_PREFIX_PORT_PROFILES}_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if cached is not None:
            return cached

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequest(method="get", path="/rest/portconf")
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
            logger.error("Error getting port profiles: %s", e)
            raise

    async def get_port_profile_by_id(self, profile_id: str) -> Dict[str, Any]:
        """Get a specific port profile by ID.

        Raises:
            UniFiNotFoundError: If the profile does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        api_request = ApiRequest(method="get", path=f"/rest/portconf/{profile_id}")
        response = await self._connection.request(api_request)
        data = (
            response if isinstance(response, list) else response.get("data", []) if isinstance(response, dict) else []
        )
        if not data:
            raise UniFiNotFoundError("port_profile", profile_id)
        return data[0]

    async def create_port_profile(self, profile_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new port profile.

        Args:
            profile_data: Dictionary with at minimum name and forward fields.

        Returns:
            The created port profile dictionary, or None on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        if not profile_data.get("name") or not profile_data.get("forward"):
            logger.error("Missing required fields 'name' and/or 'forward' for port profile")
            return None

        try:
            api_request = ApiRequest(method="post", path="/rest/portconf", data=profile_data)
            response = await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_PORT_PROFILES)

            data = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
            return data[0] if data else None
        except Exception as e:
            logger.error("Error creating port profile: %s", e, exc_info=True)
            raise

    async def update_port_profile(self, profile_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing port profile by merging updates with current state.

        Returns:
            The merged profile dict.

        Raises:
            UniFiNotFoundError: If the profile does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        existing = await self.get_port_profile_by_id(profile_id)  # raises on miss
        if not update_data:
            return existing

        merged_data = deep_merge(existing, update_data)
        api_request = ApiRequest(method="put", path=f"/rest/portconf/{profile_id}", data=merged_data)
        await self._connection.request(api_request)
        self._connection._invalidate_cache(CACHE_PREFIX_PORT_PROFILES)
        return merged_data

    async def delete_port_profile(self, profile_id: str) -> bool:
        """Delete a port profile.

        Note: System profiles with attr_no_delete=true cannot be deleted.

        Args:
            profile_id: The ID of the port profile to delete.

        Returns:
            True on success, False on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequest(method="delete", path=f"/rest/portconf/{profile_id}")
            await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_PORT_PROFILES)
            return True
        except Exception as e:
            logger.error("Error deleting port profile %s: %s", profile_id, e, exc_info=True)
            raise

    # ---- Device stat helpers ----

    async def _get_device_stat(self, device_mac: str) -> Optional[Dict[str, Any]]:
        """Get raw device stat data for a specific device."""
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequest(method="get", path=f"/stat/device/{device_mac}")
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
            logger.error("Error getting device stat for %s: %s", device_mac, e)
            raise

    async def _get_device_id(self, device_mac: str) -> Optional[str]:
        """Get the device _id from its MAC address (needed for REST writes)."""
        device = await self._get_device_stat(device_mac)
        if device:
            return device.get("_id")
        return None

    # ---- Switch port read operations ----

    async def get_switch_ports(self, device_mac: str) -> Optional[Dict[str, Any]]:
        """Get port overrides (profile assignments) for a switch."""
        device = await self._get_device_stat(device_mac)
        if not device:
            return None
        return {
            "name": device.get("name", device.get("hostname", device_mac)),
            "model": device.get("model"),
            "port_overrides": device.get("port_overrides", []),
        }

    async def get_port_stats(self, device_mac: str) -> Optional[Dict[str, Any]]:
        """Get live port table statistics for a switch."""
        device = await self._get_device_stat(device_mac)
        if not device:
            return None
        return {
            "name": device.get("name", device.get("hostname", device_mac)),
            "model": device.get("model"),
            "port_table": device.get("port_table", []),
        }

    async def get_lldp_neighbors(self, device_mac: str) -> Optional[Dict[str, Any]]:
        """Get LLDP neighbor discovery table for a switch."""
        device = await self._get_device_stat(device_mac)
        if not device:
            return None
        return {
            "name": device.get("name", device.get("hostname", device_mac)),
            "model": device.get("model"),
            "lldp_table": device.get("lldp_table", []),
        }

    async def get_switch_capabilities(self, device_mac: str) -> Optional[Dict[str, Any]]:
        """Get switch hardware capabilities."""
        device = await self._get_device_stat(device_mac)
        if not device:
            return None
        return {
            "name": device.get("name", device.get("hostname", device_mac)),
            "model": device.get("model"),
            "switch_caps": device.get("switch_caps", {}),
            "stp_version": device.get("stp_version"),
            "stp_priority": device.get("stp_priority"),
            "jumboframe_enabled": device.get("jumboframe_enabled"),
            "dot1x_portctrl_enabled": device.get("dot1x_portctrl_enabled"),
        }

    # ---- Switch port write operations ----

    async def set_port_overrides(self, device_mac: str, port_overrides: List[Dict[str, Any]]) -> bool:
        """Set port overrides for a switch.

        CRITICAL: port_overrides is a full replacement — you must include
        ALL existing overrides plus your changes. Missing ports revert to defaults.

        Args:
            device_mac: MAC address of the switch.
            port_overrides: Complete list of port override dicts.

        Returns:
            True on success.

        Raises:
            Exception: On API error.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        device_id = await self._get_device_id(device_mac)
        if not device_id:
            raise ValueError(f"Device '{device_mac}' not found")

        api_request = ApiRequest(
            method="put",
            path=f"/rest/device/{device_id}",
            data={"port_overrides": port_overrides},
        )
        await self._connection.request(api_request)
        return True

    async def update_device_config(self, device_mac: str, config_data: Dict[str, Any]) -> bool:
        """Update device-level configuration (STP, jumbo frames, etc.).

        The UniFi controller requires port_overrides to be included alongside
        device-level config changes. This method fetches the current port_overrides
        and merges them into the PUT payload automatically.

        Args:
            device_mac: MAC address of the device.
            config_data: Dict of fields to update (e.g., stp_priority, jumboframe_enabled).

        Returns:
            True on success.

        Raises:
            Exception: On API error — propagated to tool layer for user-facing message.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        device_id = await self._get_device_id(device_mac)
        if not device_id:
            raise ValueError(f"Device '{device_mac}' not found")

        # Fetch current port_overrides — the controller requires them in the PUT payload
        device = await self._get_device_stat(device_mac)
        port_overrides = device.get("port_overrides", []) if device else []

        payload = dict(config_data)
        payload["port_overrides"] = port_overrides

        api_request = ApiRequest(
            method="put",
            path=f"/rest/device/{device_id}",
            data=payload,
        )
        await self._connection.request(api_request)
        return True

    # ---- Device commands ----

    async def power_cycle_port(self, device_mac: str, port_idx: int) -> bool:
        """Power cycle PoE on a specific port.

        Args:
            device_mac: MAC address of the switch.
            port_idx: 1-based port number to power cycle.

        Returns:
            True on success.

        Raises:
            Exception: On API error (e.g., non-PoE port).
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        api_request = ApiRequest(
            method="post",
            path="/cmd/devmgr",
            data={"cmd": "power-cycle", "mac": device_mac, "port_idx": port_idx},
        )
        await self._connection.request(api_request)
        return True
