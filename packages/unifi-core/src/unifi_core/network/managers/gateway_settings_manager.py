"""Manager for gateway (USG) settings — a per-site singleton settings object.

Reads/writes the controller's ``usg`` settings section:
    GET ``/get/setting/usg`` → list with one settings dict
    PUT ``/set/setting/usg`` → full settings object

Updates follow the same fetch-merge-put-verify golden path the other managers
use: fetch current, deep-merge the partial update (preserving nested
sub-objects such as ``dns_verification`` and every untouched sibling key), PUT
the full object, then re-read and confirm the requested fields persisted.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from aiounifi.models.api import ApiRequest

from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_GATEWAY_SETTINGS = "gateway_settings"
SETTING_KEY = "usg"


def _unpersisted_fields(before: Dict[str, Any], after: Dict[str, Any], requested: Dict[str, Any]) -> List[str]:
    """Return requested keys that were meant to change but did not move.

    A field counts as *not persisted* only when it was actually being changed
    (requested value differs from the pre-write value) yet the re-read value is
    still identical to the pre-write value. Fields the controller normalizes to
    a different-but-non-original value are treated as persisted.

    Nested object updates (e.g. ``dns_verification``) are verified per requested
    LEAF key, not by whole-sub-object equality — otherwise the controller
    normalizing or filling an untouched sibling key would mask a silently-dropped
    sub-field (the change appears to "stick" because the sub-object moved overall).
    """
    stuck: List[str] = []
    for key, want in requested.items():
        prev = before.get(key)
        if isinstance(want, dict) and isinstance(prev, dict):
            after_sub = after.get(key)
            after_sub = after_sub if isinstance(after_sub, dict) else {}
            for subkey, subwant in want.items():
                subprev = prev.get(subkey)
                if subprev == subwant:
                    continue  # no real change for this sub-key
                if after_sub.get(subkey) == subprev:
                    stuck.append(f"{key}.{subkey}")
            continue
        if prev == want:
            continue  # no real change requested for this field
        if after.get(key) == prev:
            stuck.append(key)
    return stuck


class GatewaySettingsManager:
    """Manages gateway (USG) settings on the UniFi Controller."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the Gateway Settings Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def get_gateway_settings(self) -> Dict[str, Any]:
        """Fetch the gateway (USG) settings singleton.

        The controller returns a single-element list for ``/get/setting/usg``;
        this unwraps it to the settings dict (or ``{}`` when absent).
        """
        cache_key = f"{CACHE_PREFIX_GATEWAY_SETTINGS}_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            api_request = ApiRequest(method="get", path=f"/get/setting/{SETTING_KEY}")
            response = await self._connection.request(api_request)
            settings: Dict[str, Any] = {}
            if isinstance(response, list) and response and isinstance(response[0], dict):
                settings = response[0]
            elif isinstance(response, dict):
                settings = response
            self._connection._update_cache(cache_key, settings)
            return settings
        except Exception as e:
            logger.error("Error getting gateway settings: %s", e)
            raise

    async def update_gateway_settings(self, update_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Update gateway (USG) settings by deep-merging a partial onto current.

        Args:
            update_data: Dictionary of fields to update.

        Returns:
            Tuple of (success, error_message). On success error_message is None.
            On failure error_message describes which fields the controller
            accepted but did not persist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        if not update_data:
            logger.warning("No update data provided for gateway settings.")
            return True, None  # No action needed

        # A nested-object field passed as a non-dict would REPLACE (not merge) the
        # existing sub-object in deep_merge, silently wiping its sibling keys — reject
        # rather than clobber. Guards both the MCP tool and the API action paths.
        if "dns_verification" in update_data and not isinstance(update_data["dns_verification"], dict):
            return False, "dns_verification must be an object (a dict of DNS-verification keys)."

        try:
            # 1. Fetch current state.
            existing = await self.get_gateway_settings()

            # 2. Deep merge preserves nested sub-objects (e.g. dns_verification)
            #    and every sibling key the partial update did not touch.
            merged_data = deep_merge(existing, update_data)
            # The section discriminator is fixed by the endpoint path; set it
            # unconditionally so a corrupt/mismatched stored key can't be PUT back.
            merged_data["key"] = SETTING_KEY

            # 3. Send the full merged object.
            api_request = ApiRequest(
                method="put",
                path=f"/set/setting/{SETTING_KEY}",
                data=merged_data,
            )
            await self._connection.request(api_request)
            logger.info("Update command sent for gateway settings with merged data.")
            self._connection._invalidate_cache(f"{CACHE_PREFIX_GATEWAY_SETTINGS}_{self._connection.site}")

            # 4. Verify the controller actually persisted the change.
            refetched = await self.get_gateway_settings()
            stuck = _unpersisted_fields(existing, refetched, update_data)
            if stuck:
                return False, (
                    f"Controller accepted the request but did not persist field(s): {', '.join(sorted(stuck))}."
                )
            return True, None
        except Exception as e:
            logger.error("Error updating gateway settings: %s", e, exc_info=True)
            raise
