"""Door management for UniFi Access.

Provides methods to query door state, lock/unlock doors, and manage
door configurations via the Access controller API.

Dual-path routing: tries the API client (py-unifi-access) first when
available, then falls back to the proxy session path.

Proxy paths discovered via browser inspection:
- ``dashboard/locations?expand[]=...`` -- lists doors with lock state, thumbnails
- ``access_groups`` -- lists door/access groups
- ``dashboard/locations/{id}/...`` -- per-door operations (unlock/lock)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError

logger = logging.getLogger(__name__)

# Query parameters for the dashboard locations endpoint (includes all
# useful expansions discovered from browser network inspection).
_LOCATIONS_EXPAND = (
    "expand[]=location.thumbnail&expand[]=device.access_method&expand[]=device.lock_state&expand[]=device.thumbnail"
)

# Fields to keep at the door level in compact mode.
_COMPACT_DOOR_KEYS = frozenset({"id", "name", "location_type", "access_method", "devices"})

# Fields to keep per nested device in compact mode.
_COMPACT_DOOR_DEVICE_KEYS = frozenset({"name", "id", "device_type", "online", "direction"})

_API_DOOR_LIST_KEYS = ("id", "name", "door_position_status", "lock_relay_status")


class DoorManager:
    """Reads and mutates door data from the Access controller."""

    def __init__(self, connection_manager: AccessConnectionManager) -> None:
        self._cm = connection_manager

    @staticmethod
    def _api_door_to_dict(door: Any) -> Dict[str, Any]:
        """Translate a py-unifi-access Door into the manager response dialect."""
        return {
            "id": door.id,
            "name": door.name,
            "door_position_status": getattr(door, "door_position_status", None),
            "lock_relay_status": getattr(door, "door_lock_relay_status", None),
            "camera_resource_id": getattr(door, "camera_resource_id", None),
            "door_guard": getattr(door, "door_guard", None),
        }

    # ------------------------------------------------------------------
    # Read-only methods
    # ------------------------------------------------------------------

    @staticmethod
    def _compact_door(door: Dict[str, Any]) -> Dict[str, Any]:
        """Strip low-value fields from a door dict.

        Keeps identity and access method at the door level.  Simplifies
        nested devices to name/id/type/online/direction only.  Strips
        thumbnail, up_id, extras, device_ids (~70% smaller).
        """
        result = {k: v for k, v in door.items() if k in _COMPACT_DOOR_KEYS}
        # Simplify nested devices
        if "devices" in result and isinstance(result["devices"], list):
            result["devices"] = [
                {k: v for k, v in dev.items() if k in _COMPACT_DOOR_DEVICE_KEYS}
                for dev in result["devices"]
                if isinstance(dev, dict)
            ]
        return result

    async def list_doors(self, compact: bool = False) -> List[Dict[str, Any]]:
        """Return all doors as summary dicts.

        Tries the API client first, then falls back to the proxy path.
        """
        try:
            if self._cm.has_api_client:
                # API client already returns minimal 4-field dicts; compact is irrelevant.
                doors = await self._cm.api_client.get_doors()
                result = []
                for door in doors:
                    translated = self._api_door_to_dict(door)
                    result.append({key: translated[key] for key in _API_DOOR_LIST_KEYS})
                return result
            elif self._cm.has_proxy:
                data = await self._cm.proxy_request("GET", f"dashboard/locations?{_LOCATIONS_EXPAND}")
                # Response is {"data": {"locations": [...]}}
                inner = self._cm.extract_data(data)
                if isinstance(inner, dict):
                    doors = inner.get("locations", [])
                else:
                    doors = inner
                if compact:
                    doors = [self._compact_door(d) for d in doors if isinstance(d, dict)]
                return doors
            else:
                raise UniFiConnectionError("No auth path available for list_doors")
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to list doors: %s", e, exc_info=True)
            raise

    async def get_door(self, door_id: str) -> Dict[str, Any]:
        """Return detailed information for a single door.

        Tries the API client first, then falls back to the proxy path.
        When using the proxy path we fetch all locations and filter by ID
        since there is no single-door endpoint.
        """
        if not door_id:
            raise ValueError("door_id is required")
        try:
            if self._cm.has_api_client:
                doors = await self._cm.api_client.get_doors()
                door = next((door for door in doors if door.id == door_id), None)
                if door is None:
                    raise UniFiNotFoundError("door", door_id)
                return self._api_door_to_dict(door)
            elif self._cm.has_proxy:
                data = await self._cm.proxy_request("GET", f"dashboard/locations?{_LOCATIONS_EXPAND}")
                # Response is {"data": {"locations": [...]}}
                inner = self._cm.extract_data(data)
                locations = inner.get("locations", inner) if isinstance(inner, dict) else inner
                if isinstance(locations, list):
                    for loc in locations:
                        if isinstance(loc, dict) and loc.get("id") == door_id:
                            return loc
                raise UniFiNotFoundError("door", door_id)
            else:
                raise UniFiConnectionError("No auth path available for get_door")
        except (UniFiConnectionError, UniFiNotFoundError, ValueError):
            raise
        except Exception as e:
            logger.error("Failed to get door %s: %s", door_id, e, exc_info=True)
            raise

    async def get_door_status(self, door_id: str) -> Dict[str, Any]:
        """Return current lock/position status for a single door.

        Tries the API client first, then falls back to the proxy path.
        """
        door = await self.get_door(door_id)
        return {
            "id": door.get("id", door_id),
            "name": door.get("name"),
            "door_position_status": door.get("door_position_status"),
            "lock_relay_status": door.get("lock_relay_status"),
        }

    async def list_door_groups(self) -> List[Dict[str, Any]]:
        """Return all access groups (door groupings).

        This is only available via the proxy path (private API).
        """
        try:
            if self._cm.has_proxy:
                data = await self._cm.proxy_request("GET", "access_groups")
                return self._cm.extract_data(data)
            else:
                raise UniFiConnectionError("No auth path available for list_door_groups (proxy session required)")
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to list door groups: %s", e, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Mutation methods (preview/confirm pattern)
    # ------------------------------------------------------------------

    async def unlock_door(self, door_id: str, duration: int = 2) -> Dict[str, Any]:
        """Preview an unlock operation. Returns preview data for confirmation.

        Parameters
        ----------
        door_id:
            UUID of the door to unlock.
        duration:
            Unlock duration in seconds (default 2).
        """
        if not door_id:
            raise ValueError("door_id is required")
        if duration < 1:
            raise ValueError("duration must be at least 1 second")

        # Get current state for preview
        current = await self.get_door_status(door_id)
        return {
            "door_id": door_id,
            "door_name": current.get("name"),
            "current_state": {
                "lock_relay_status": current.get("lock_relay_status"),
                "door_position_status": current.get("door_position_status"),
            },
            "proposed_changes": {
                "action": "unlock",
                "duration_seconds": duration,
            },
        }

    async def apply_unlock_door(self, door_id: str, duration: int = 2) -> Dict[str, Any]:
        """Execute the unlock operation on the controller.

        Tries the API client first, then falls back to the proxy path.
        """
        try:
            if self._cm.has_api_client:
                await self._cm.api_client.unlock_door(door_id)
                return {
                    "door_id": door_id,
                    "action": "unlock",
                    "duration_seconds": duration,
                    "result": "success",
                }
            elif self._cm.has_proxy:
                await self._cm.proxy_request(
                    "PUT",
                    f"dashboard/locations/{door_id}/unlock",
                    json={"duration": duration},
                )
                return {
                    "door_id": door_id,
                    "action": "unlock",
                    "duration_seconds": duration,
                    "result": "success",
                }
            else:
                raise UniFiConnectionError("No auth path available for unlock_door")
        except (UniFiConnectionError, ValueError):
            raise
        except Exception as e:
            logger.error("Failed to unlock door %s: %s", door_id, e, exc_info=True)
            raise

    async def lock_door(self, door_id: str) -> Dict[str, Any]:
        """Preview a lock operation. Returns preview data for confirmation.

        Lock is only available via the proxy path (private API).
        """
        if not door_id:
            raise ValueError("door_id is required")

        # Get current state for preview
        current = await self.get_door_status(door_id)
        return {
            "door_id": door_id,
            "door_name": current.get("name"),
            "current_state": {
                "lock_relay_status": current.get("lock_relay_status"),
                "door_position_status": current.get("door_position_status"),
            },
            "proposed_changes": {
                "action": "lock",
            },
        }

    async def apply_lock_door(self, door_id: str) -> Dict[str, Any]:
        """Execute the lock operation on the controller.

        Tries the API client first, then falls back to the proxy path.
        """
        try:
            if self._cm.has_api_client:
                from unifi_access_api.models.door import DoorLockRule, DoorLockRuleType

                await self._cm.api_client.set_door_lock_rule(
                    door_id,
                    DoorLockRule(type=DoorLockRuleType.LOCK_NOW, interval=0),
                )
                return {
                    "door_id": door_id,
                    "action": "lock",
                    "result": "success",
                }
            elif self._cm.has_proxy:
                await self._cm.proxy_request("PUT", f"dashboard/locations/{door_id}/lock")
                return {
                    "door_id": door_id,
                    "action": "lock",
                    "result": "success",
                }
            else:
                raise UniFiConnectionError("No auth path available for lock_door")
        except (UniFiConnectionError, ValueError):
            raise
        except Exception as e:
            logger.error("Failed to lock door %s: %s", door_id, e, exc_info=True)
            raise
