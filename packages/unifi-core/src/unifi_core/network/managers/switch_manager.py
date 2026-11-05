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

import asyncio
import logging
import weakref
from typing import Any, Dict, List, Optional

from aiounifi.errors import RequestError
from aiounifi.models.api import ApiRequest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.mac import canonical_mac, normalize_mac
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.request_paths import object_id
from unifi_core.write_verification import WriteVerificationResult, failed_write, noop_write, verify_write

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_PORT_PROFILES = "port_profiles"
_PORT_PROFILE_ABSENT_VALUE_DEFAULTS: Dict[str, Any] = {
    "tagged_networkconf_ids": [],
    "excluded_networkconf_ids": [],
}


# Device writes read port_overrides, change them and PUT the whole array back, so
# two overlapping writes to one switch would each restore the other's old
# entries. Locks are kept per connection, not per manager, because a server may
# build managers per request over one shared connection.
_DEVICE_WRITE_LOCKS: "weakref.WeakKeyDictionary[Any, Dict[str, asyncio.Lock]]" = weakref.WeakKeyDictionary()


class SwitchManager:
    """Manages switch-related operations on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    def _device_write_lock(self, device_mac: str) -> asyncio.Lock:
        """The lock serializing read-modify-write updates of one switch's device record."""
        locks = _DEVICE_WRITE_LOCKS.setdefault(self._connection, {})
        # One key per switch however its MAC is spelled; opaque identifiers keep their own key.
        key = canonical_mac(device_mac) or normalize_mac(device_mac) or device_mac
        return locks.setdefault(key, asyncio.Lock())

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

        api_request = ApiRequest(method="get", path=f"/rest/portconf/{object_id(profile_id, 'port profile')}")
        response = await self._connection.request(api_request)
        data = (
            response if isinstance(response, list) else response.get("data", []) if isinstance(response, dict) else []
        )
        if not data:
            raise UniFiNotFoundError("port_profile", profile_id)
        return data[0]

    async def create_port_profile(self, profile_data: Dict[str, Any]) -> WriteVerificationResult:
        """Create a new port profile.

        Args:
            profile_data: Dictionary with at minimum name and forward fields.

        Returns:
            Structured exact field-verification result with post-write state.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        if not profile_data.get("name") or not profile_data.get("forward"):
            logger.error("Missing required fields 'name' and/or 'forward' for port profile")
            return failed_write("Missing required fields 'name' and/or 'forward'", operation="create")

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
            created = data[0] if data and isinstance(data[0], dict) else None
            profile_id = created.get("_id") if created else None
            if not profile_id:
                return failed_write(
                    "Controller accepted the port profile create request but did not return a resource ID; "
                    "persistence could not be verified.",
                    operation="create",
                    mutation_applied=True,
                    resource=created,
                )

            try:
                stored = await self.get_port_profile_by_id(profile_id)
            except Exception as e:
                logger.warning("Created port profile %s could not be re-read: %s", profile_id, e)
                return failed_write(
                    f"Controller accepted the port profile create request but the resource could not be re-read: {e}",
                    operation="create",
                    mutation_applied=True,
                    resource=created,
                    metadata={"profile_id": profile_id},
                )

            return verify_write(
                operation="create",
                requested=profile_data,
                after=stored,
                absent_value_defaults=_PORT_PROFILE_ABSENT_VALUE_DEFAULTS,
                metadata={"profile_id": profile_id},
            )
        except Exception as e:
            logger.error("Error creating port profile: %s", e, exc_info=True)
            raise

    async def update_port_profile(self, profile_id: str, update_data: Dict[str, Any]) -> WriteVerificationResult:
        """Update an existing port profile by merging updates with current state.

        Returns:
            Structured exact field-verification result with post-write state.

        Raises:
            UniFiNotFoundError: If the profile does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        existing = await self.get_port_profile_by_id(profile_id)  # raises on miss
        if not update_data:
            return noop_write(operation="update", resource=existing, metadata={"profile_id": profile_id})

        merged_data = deep_merge(existing, update_data)
        api_request = ApiRequest(
            method="put", path=f"/rest/portconf/{object_id(profile_id, 'port profile')}", data=merged_data
        )
        await self._connection.request(api_request)
        self._connection._invalidate_cache(CACHE_PREFIX_PORT_PROFILES)

        # The write has landed by this point. A read-back failure must not be
        # reported as a failed write — it only means the result is unverified.
        try:
            stored = await self.get_port_profile_by_id(profile_id)
        except Exception as e:
            logger.warning("Port profile %s was written but could not be re-read to verify it: %s", profile_id, e)
            return failed_write(
                f"Controller accepted the port profile update but the resource could not be re-read: {e}",
                operation="update",
                mutation_applied=True,
                metadata={"profile_id": profile_id, "details_before_attempt": existing},
            )
        return verify_write(
            operation="update",
            requested=update_data,
            before=existing,
            after=stored,
            absent_value_defaults=_PORT_PROFILE_ABSENT_VALUE_DEFAULTS,
            metadata={"profile_id": profile_id},
        )

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
            api_request = ApiRequest(method="delete", path=f"/rest/portconf/{object_id(profile_id, 'port profile')}")
            await self._connection.request(api_request)

            self._connection._invalidate_cache(CACHE_PREFIX_PORT_PROFILES)
            return True
        except Exception as e:
            logger.error("Error deleting port profile %s: %s", profile_id, e, exc_info=True)
            raise

    # ---- Device stat helpers ----

    async def _get_device_stat(self, device_mac: str) -> Optional[Dict[str, Any]]:
        """Get raw device stat data for a specific device."""
        device_mac = normalize_mac(device_mac) or device_mac
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequest(method="get", path=f"/stat/device/{object_id(device_mac, 'device MAC')}")
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
            logger.error("Device statistics read failed: %s", type(e).__name__)
            raise RequestError(f"Device statistics read failed ({type(e).__name__}).") from None

    async def _get_device_id(self, device_mac: str) -> Optional[str]:
        """Get the device _id from its MAC address (needed for REST writes)."""
        device_mac = normalize_mac(device_mac) or device_mac
        device = await self._get_device_stat(device_mac)
        if device:
            return device.get("_id")
        return None

    # ---- Switch port read operations ----

    async def get_switch_ports(self, device_mac: str) -> Optional[Dict[str, Any]]:
        """Get port overrides (profile assignments) for a switch."""
        device_mac = normalize_mac(device_mac) or device_mac
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
        device_mac = normalize_mac(device_mac) or device_mac
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
        device_mac = normalize_mac(device_mac) or device_mac
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
        device_mac = normalize_mac(device_mac) or device_mac
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

    @staticmethod
    def _merge_port_overrides(
        current: List[Dict[str, Any]],
        port_overrides: List[Dict[str, Any]],
        remove_port_idxs: Optional[List[int]],
    ) -> Dict[str, Any]:
        """Merge *port_overrides* into *current* by ``port_idx``.

        The controller treats the PUT array as a full replacement, so a port
        missing from it reverts to defaults. Each sent entry replaces the entry
        for its port or is appended; every other current entry is kept as the
        controller returned it. An entry is dropped only when its port is in
        *remove_port_idxs*.
        """

        def port_of(entry: Any) -> int:
            port = entry.get("port_idx") if isinstance(entry, dict) else None
            if not isinstance(port, int) or isinstance(port, bool):
                raise ValueError("Every port override needs an integer port_idx.")
            return port

        sent: Dict[int, Dict[str, Any]] = {}
        for entry in port_overrides:
            port = port_of(entry)
            if port in sent:
                raise ValueError(f"Port {port} appears more than once in port_overrides.")
            sent[port] = entry
        removed = list(dict.fromkeys(remove_port_idxs or []))
        if any(not isinstance(port, int) or isinstance(port, bool) for port in removed):
            raise ValueError("remove_port_idxs must hold integer port numbers.")
        both = sorted(set(sent) & set(removed))
        if both:
            raise ValueError(f"Port {both[0]} is both updated and removed; choose one.")
        existing = [port_of(entry) for entry in current if isinstance(entry, dict) and "port_idx" in entry]
        missing = [port for port in removed if port not in existing]
        if missing:
            raise ValueError(f"Port {missing[0]} has no override to remove.")
        if not sent and not removed:
            raise ValueError("No port override changes were given.")

        merged: List[Dict[str, Any]] = []
        changed, kept = [], []
        for entry in current:
            port = entry.get("port_idx") if isinstance(entry, dict) else None
            if port in removed:
                continue
            if port in sent:
                merged.append(sent.pop(port))
                changed.append(port)
            else:
                merged.append(entry)
                if port is not None:
                    kept.append(port)
        added = sorted(sent)
        merged.extend(sent[port] for port in added)
        return {
            "current": current,
            "merged": merged,
            "changed_ports": changed,
            "added_ports": added,
            "removed_ports": removed,
            "kept_ports": kept,
        }

    async def _port_override_target(self, device_mac: str) -> tuple[str, List[Dict[str, Any]]]:
        device_mac = normalize_mac(device_mac) or device_mac
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        device = await self._get_device_stat(device_mac)
        device_id = device.get("_id") if device else None
        if not device_id:
            raise ValueError(f"Device '{device_mac}' not found")
        current = device.get("port_overrides") or []
        return device_id, current if isinstance(current, list) else []

    async def plan_port_overrides(
        self,
        device_mac: str,
        port_overrides: List[Dict[str, Any]],
        remove_port_idxs: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Show what :meth:`set_port_overrides` would write, without writing.

        Returns the current and merged arrays plus the ports changed, added,
        removed and kept, for a preview.
        """
        _, current = await self._port_override_target(device_mac)
        return self._merge_port_overrides(current, port_overrides, remove_port_idxs)

    async def set_port_overrides(
        self,
        device_mac: str,
        port_overrides: List[Dict[str, Any]],
        remove_port_idxs: Optional[List[int]] = None,
    ) -> bool:
        """Change port overrides for a switch, keeping every port not named.

        The controller replaces the whole ``port_overrides`` array on write, so
        this reads the switch's current overrides and merges into them: each
        sent entry (matched by ``port_idx``) replaces that port's entry or is
        added, and other ports keep theirs. Pass ``remove_port_idxs`` to drop a
        port's override so it reverts to defaults.

        Args:
            device_mac: MAC address of the switch.
            port_overrides: Override entries for the ports to change.
            remove_port_idxs: Ports whose override to remove.

        Returns:
            True on success.

        Raises:
            ValueError: Unknown device, or changes that are empty or ambiguous.
            Exception: On API error.
        """
        async with self._device_write_lock(device_mac):
            device_id, current = await self._port_override_target(device_mac)
            plan = self._merge_port_overrides(current, port_overrides, remove_port_idxs)
            api_request = ApiRequest(
                method="put",
                path=f"/rest/device/{object_id(device_id, 'device')}",
                data={"port_overrides": plan["merged"]},
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
        device_mac = normalize_mac(device_mac) or device_mac
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        async with self._device_write_lock(device_mac):
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
                path=f"/rest/device/{object_id(device_id, 'device')}",
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
        device_mac = normalize_mac(device_mac) or device_mac
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        api_request = ApiRequest(
            method="post",
            path="/cmd/devmgr",
            data={"cmd": "power-cycle", "mac": device_mac, "port_idx": port_idx},
        )
        await self._connection.request(api_request)
        return True
