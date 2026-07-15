"""Device management for UniFi Access.

Provides methods to query and manage Access hardware devices (hubs, readers,
relays, intercoms) via the Access controller API.

Dual-path routing: tries the API client (py-unifi-access) first when
available, then falls back to the proxy session path.

Proxy paths discovered via browser inspection:
- ``devices/topology4`` -- device topology (full device tree)
- ``protect_devices?include_adopted_by_access=true`` -- Protect devices paired with Access
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.models.device_configs import (
    build_config_write_body,
    is_camera_device_id,
    validate_config_updates,
)
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError

logger = logging.getLogger(__name__)

_COMPACT_DEVICE_KEYS = frozenset(
    {
        "unique_id",
        "name",
        "alias",
        "device_type",
        "firmware",
        "version",
        "ip",
        "mac",
        "hw_type",
        "is_online",
        "is_adopted",
        "is_connected",
        "is_rebooting",
        "is_unavailable",
        "adopting",
        "connected_uah_id",
        "location_id",
        "model",
        "display_model",
        "_door_name",
        "_door_id",
    }
)

_API_DEVICE_LIST_KEYS = ("id", "name", "type", "connected", "firmware_version")


class DeviceManager:
    """Reads and mutates device data from the Access controller."""

    def __init__(self, connection_manager: AccessConnectionManager) -> None:
        self._cm = connection_manager

    @staticmethod
    def _api_device_to_dict(device: Any) -> Dict[str, Any]:
        """Translate a py-unifi-access Device into the manager response dialect."""
        return {
            "id": device.id,
            "name": getattr(device, "name", None),
            "type": getattr(device, "type", None),
            "connected": getattr(device, "is_online", None),
            "firmware_version": getattr(device, "firmware_version", None),
            "mac": getattr(device, "mac", None),
            "ip": getattr(device, "ip", None),
        }

    # ------------------------------------------------------------------
    # Read-only methods
    # ------------------------------------------------------------------

    @staticmethod
    def _compact_device(dev: Dict[str, Any]) -> Dict[str, Any]:
        """Strip low-value fields from a device dict.

        Keeps identity, status, and relationship fields.  Strips configs
        (58%), images (6%), location/door/floor duplicates (9%),
        extensions (6%), update_manual (5%), and capabilities (3%).
        """
        return {k: v for k, v in dev.items() if k in _COMPACT_DEVICE_KEYS}

    @staticmethod
    def _extract_devices_from_topology(topology: Any) -> List[Dict[str, Any]]:
        """Flatten the nested topology4 structure into a device list.

        The topology4 response has the structure::

            [site] -> floors -> doors -> device_groups -> [devices]

        Each device uses ``unique_id`` as its identifier.
        """
        devices: List[Dict[str, Any]] = []
        sites = topology if isinstance(topology, list) else [topology] if isinstance(topology, dict) else []
        for site in sites:
            if not isinstance(site, dict):
                continue
            for floor in site.get("floors", []):
                if not isinstance(floor, dict):
                    continue
                for door in floor.get("doors", []):
                    if not isinstance(door, dict):
                        continue
                    for dg in door.get("device_groups", []):
                        # device_groups can be a list of lists or list of dicts
                        group_devices = (
                            dg if isinstance(dg, list) else dg.get("devices", []) if isinstance(dg, dict) else []
                        )
                        for dev in group_devices:
                            if isinstance(dev, dict):
                                dev["_door_name"] = door.get("name")
                                dev["_door_id"] = door.get("unique_id")
                                devices.append(dev)
        return devices

    async def list_devices(self, compact: bool = False) -> List[Dict[str, Any]]:
        """Return all Access devices as summary dicts.

        Tries the API client first, then falls back to the proxy path
        using the ``devices/topology4`` endpoint.

        Args:
            compact: When True, strip high-volume/low-value fields from
                proxy-path responses (~87% smaller).
        """
        try:
            if self._cm.has_api_client:
                # API client already returns minimal 5-field dicts; compact is irrelevant.
                devices = await self._cm.api_client.get_devices()
                result = []
                for device in devices:
                    translated = self._api_device_to_dict(device)
                    result.append({key: translated[key] for key in _API_DEVICE_LIST_KEYS})
                return result
            elif self._cm.has_proxy:
                data = await self._cm.proxy_request("GET", "devices/topology4")
                topology = self._cm.extract_data(data)
                devices = self._extract_devices_from_topology(topology)
                if compact:
                    devices = [self._compact_device(d) for d in devices]
                return devices
            else:
                raise UniFiConnectionError("No auth path available for list_devices")
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to list devices: %s", e, exc_info=True)
            raise

    async def get_device(self, device_id: str) -> Dict[str, Any]:
        """Return detailed information for a single device.

        Tries the API client first, then falls back to the proxy path.
        When using the proxy path we flatten the topology tree and search
        by ``unique_id`` or ``mac``.
        """
        if not device_id:
            raise ValueError("device_id is required")
        try:
            if self._cm.has_api_client:
                devices = await self._cm.api_client.get_devices()
                device = next((device for device in devices if device.id == device_id), None)
                if device is None:
                    raise UniFiNotFoundError("device", device_id)
                return self._api_device_to_dict(device)
            elif self._cm.has_proxy:
                data = await self._cm.proxy_request("GET", "devices/topology4")
                topology = self._cm.extract_data(data)
                devices = self._extract_devices_from_topology(topology)
                for dev in devices:
                    if dev.get("unique_id") == device_id or dev.get("mac") == device_id:
                        return dev
                raise UniFiNotFoundError("device", device_id)
            else:
                raise UniFiConnectionError("No auth path available for get_device")
        except (UniFiConnectionError, UniFiNotFoundError, ValueError):
            raise
        except Exception as e:
            logger.error("Failed to get device %s: %s", device_id, e, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Mutation methods (preview/confirm pattern)
    # ------------------------------------------------------------------

    async def reboot_device(self, device_id: str) -> Dict[str, Any]:
        """Preview a device reboot. Returns preview data for confirmation."""
        if not device_id:
            raise ValueError("device_id is required")

        current = await self.get_device(device_id)
        return {
            "device_id": device_id,
            "device_name": current.get("name"),
            "device_type": current.get("type"),
            "current_state": {
                "connected": current.get("connected"),
                "firmware_version": current.get("firmware_version"),
            },
            "proposed_changes": {
                "action": "reboot",
            },
        }

    async def apply_reboot_device(self, device_id: str) -> Dict[str, Any]:
        """Execute the device reboot on the controller.

        Uses the proxy path since device reboot is not exposed by the
        py-unifi-access API client.
        """
        try:
            if self._cm.has_proxy:
                await self._cm.proxy_request("POST", f"devices/{device_id}/reboot")
                return {
                    "device_id": device_id,
                    "action": "reboot",
                    "result": "success",
                }
            else:
                raise UniFiConnectionError("No proxy session available for reboot_device")
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to reboot device %s: %s", device_id, e, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Device config (settings) read + update
    # ------------------------------------------------------------------

    async def get_device_configs(self, device_id: str) -> Dict[str, Any]:
        """Return a device's ``configs[]`` settings array plus write metadata.

        Settings live in the ``devices/topology4`` payload, so this is a
        proxy-only read.  The returned dict is::

            {"device_id", "device_name", "is_camera", "configs": [...]}

        where ``configs`` is the raw controller list (secrets **not** yet
        redacted — redaction is applied by the serving tool) and ``is_camera``
        is the flag the config PUT requires (derived from the device id).

        Raises :class:`UniFiNotFoundError` when the device is absent.
        """
        if not device_id:
            raise ValueError("device_id is required")
        if not self._cm.has_proxy:
            raise UniFiConnectionError("No proxy session available for get_device_configs")
        try:
            data = await self._cm.proxy_request("GET", "devices/topology4")
            topology = self._cm.extract_data(data)
            devices = self._extract_devices_from_topology(topology)
            for dev in devices:
                if dev.get("unique_id") == device_id or dev.get("mac") == device_id:
                    resolved_id = dev.get("unique_id") or device_id
                    return {
                        "device_id": resolved_id,
                        "device_name": dev.get("name") or dev.get("alias"),
                        "is_camera": is_camera_device_id(resolved_id),
                        "configs": dev.get("configs") or [],
                    }
            raise UniFiNotFoundError("device", device_id)
        except (UniFiConnectionError, UniFiNotFoundError, ValueError):
            raise
        except Exception as e:
            logger.error("Failed to get device configs %s: %s", device_id, e, exc_info=True)
            raise

    @staticmethod
    def _current_by_key(configs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {c.get("key"): c for c in configs if isinstance(c, dict) and c.get("key")}

    async def update_device_config(self, device_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Preview a device-config update. Returns preview data for confirmation.

        Fetches the device's live configs, validates every key against them
        (unknown or credential/secret keys are rejected), and returns the
        current-vs-proposed delta for the keys being changed.
        """
        if not device_id:
            raise ValueError("device_id is required")

        info = await self.get_device_configs(device_id)
        current_by_key = self._current_by_key(info["configs"])
        ok, err = validate_config_updates(updates, current_by_key)
        if not ok:
            raise ValueError(err)

        return {
            "device_id": info["device_id"],
            "device_name": info["device_name"],
            "current_state": {k: (current_by_key[k] or {}).get("value") for k in updates},
            "proposed_changes": {k: str(v) for k, v in updates.items()},
        }

    async def apply_update_device_config(
        self, device_id: str, updates: Dict[str, Any], is_camera: bool | None = None
    ) -> Dict[str, Any]:
        """Execute a device-config update on the controller.

        Re-fetches the live configs (so the tag lookup and validation reflect
        current state), builds the ``[{key, tag, value}]`` PUT body, and writes
        it via ``PUT device/{id}/configs?is_camera=<bool>``. ``is_camera`` is
        derived from the device id unless the caller pins it.
        """
        if not device_id:
            raise ValueError("device_id is required")

        info = await self.get_device_configs(device_id)
        current_by_key = self._current_by_key(info["configs"])
        ok, err = validate_config_updates(updates, current_by_key)
        if not ok:
            raise ValueError(err)

        body = build_config_write_body(updates, current_by_key)
        cam = info["is_camera"] if is_camera is None else bool(is_camera)
        try:
            await self._cm.proxy_request(
                "PUT",
                f"device/{info['device_id']}/configs",
                params={"is_camera": "true" if cam else "false"},
                json=body,
            )
            return {
                "device_id": info["device_id"],
                "action": "update_config",
                "result": "success",
                "updated_keys": list(updates.keys()),
                "is_camera": cam,
            }
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to update device config %s: %s", device_id, e, exc_info=True)
            raise
