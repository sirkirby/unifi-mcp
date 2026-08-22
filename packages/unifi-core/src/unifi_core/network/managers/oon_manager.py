"""Manager for OON (Object-Oriented Network) policies on the UniFi controller.

OON policies provide high-level network access control including:
- Internet access scheduling (bedtime blackouts)
- Application blocking (social media, streaming)
- QoS/bandwidth limiting
- Policy-based routing (VPN steering)

Policies can target specific client MACs or client groups.

API endpoints:
  LIST:   GET  /proxy/network/v2/api/site/{site}/object-oriented-network-configs  (plural)
  GET:    GET  /proxy/network/v2/api/site/{site}/object-oriented-network-config/{id}  (singular)
  CREATE: POST /proxy/network/v2/api/site/{site}/object-oriented-network-config  (singular)
  UPDATE: PUT  /proxy/network/v2/api/site/{site}/object-oriented-network-config/{id}  (singular)
  DELETE: DELETE /proxy/network/v2/api/site/{site}/object-oriented-network-config/{id}  (singular)

Note: The list endpoint uses the PLURAL form, while all other operations use SINGULAR.
"""

import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.mac import normalize_mac
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_OON_POLICIES = "oon_policies"

# Asymmetric paths: list uses plural, CRUD uses singular
OON_PATH_LIST = "/object-oriented-network-configs"
OON_PATH_SINGLE = "/object-oriented-network-config"


def _normalize_target_value(target_type: Any, value: Any) -> Any:
    """Lowercase a MAC target; leave every other target type untouched.

    Only ``MAC`` targets are addresses. A NETWORK_GROUP_ID is an opaque
    identifier and case-folding it would change which object it names.
    """
    if str(target_type).upper() == "MAC":
        return normalize_mac(value) or value
    return value


def _normalize_oon_targets(target_type: str | None, targets: Any) -> Any:
    """Translate friendly target inputs into the controller's target objects."""
    if not isinstance(targets, list):
        return targets

    default_type = "NETWORK_GROUP_ID" if str(target_type).upper() == "GROUPS" else "MAC"
    normalized: list[Any] = []
    for target in targets:
        if isinstance(target, str):
            normalized.append({"type": default_type, "value": _normalize_target_value(default_type, target)})
            continue

        if isinstance(target, dict):
            item = target.copy()
            item_type = item.get("type") or default_type
            item_value = item.get("value")
            if item_value is None:
                item_value = (
                    item.pop("id", None)
                    or item.pop("_id", None)
                    or item.pop("mac", None)
                    or item.pop("mac_address", None)
                    or item.pop("macAddress", None)
                    or item.pop("target", None)
                    or item.pop("target_id", None)
                    or item.pop("targetId", None)
                )
            normalized.append(
                {"type": item_type, "value": _normalize_target_value(item_type, item_value)}
                if item_value is not None
                else item
            )
            continue

        normalized.append(target)
    return normalized


def _normalize_secure_config(secure: Any) -> Any:
    """Translate shorthand secure config into the nested OON API shape."""
    if not isinstance(secure, dict):
        return secure

    normalized = secure.copy()
    internet = normalized.get("internet")
    has_controller_shape = isinstance(internet, dict) and "mode" in internet
    if has_controller_shape:
        normalized.setdefault("enabled", True)
        return normalized

    if isinstance(internet, dict):
        internet_config = internet.copy()
    else:
        internet_config = {}

    apps = normalized.pop("apps", internet_config.get("apps", []))
    schedule = normalized.pop("schedule", internet_config.get("schedule"))
    internet_access_enabled = normalized.pop("internet_access_enabled", None)

    has_enabled_option = bool(apps or schedule or internet_access_enabled is False)
    if "mode" not in internet_config:
        if internet_access_enabled is False:
            internet_config["mode"] = "TURN_OFF_INTERNET"
        elif apps:
            internet_config["mode"] = "BLOCKLIST"
        else:
            internet_config["mode"] = "TURN_OFF_INTERNET"

    if apps:
        internet_config["apps"] = apps
    if schedule is not None:
        internet_config["schedule"] = schedule

    normalized["internet"] = internet_config
    normalized["enabled"] = bool(normalized.get("enabled", has_enabled_option))
    return normalized


def normalize_oon_create_payload(policy_data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a controller-ready OON create/update payload."""
    normalized = policy_data.copy()
    normalized["targets"] = _normalize_oon_targets(normalized.get("target_type"), normalized.get("targets", []))
    if "secure" in normalized:
        normalized["secure"] = _normalize_secure_config(normalized["secure"])
    return normalized


def normalize_oon_update_payload(
    update_data: Dict[str, Any], existing: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Apply the create path's shaping to a PARTIAL update.

    ``target_type`` decides how a target is shaped, and a partial update need
    not restate it - so fall back to the policy already on the controller.

    When it is resolvable from neither, ``targets`` is left exactly as the
    caller sent it. Guessing would be worse than doing nothing: the default is
    ``MAC``, which lowercases the value, and a NETWORK_GROUP_ID is an opaque
    identifier that a case change renames.
    """
    normalized = update_data.copy()
    if "secure" in normalized:
        normalized["secure"] = _normalize_secure_config(normalized["secure"])
    if "targets" not in normalized:
        return normalized
    target_type = normalized.get("target_type") or (existing or {}).get("target_type")
    if not target_type:
        return normalized
    normalized["targets"] = _normalize_oon_targets(target_type, normalized["targets"])
    return normalized


class OonManager:
    """Manages OON (Object-Oriented Network) policies on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    async def get_oon_policies(self) -> List[Dict[str, Any]]:
        """Get all OON policies.

        Returns:
            List of OON policy dictionaries.
        """
        cache_key = f"{CACHE_PREFIX_OON_POLICIES}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequestV2(method="get", path=OON_PATH_LIST)
            response = await self._connection.request(api_request)

            policies = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )

            self._connection._update_cache(cache_key, policies)
            return policies
        except Exception as e:
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str:
                logger.debug("OON policies not available (controller may not support them): %s", e)
                return []
            logger.error("Error getting OON policies: %s", e)
            raise

    async def get_oon_policy_by_id(self, policy_id: str) -> Dict[str, Any]:
        """Get a specific OON policy by ID.

        Raises:
            UniFiNotFoundError: If the policy does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        api_request = ApiRequestV2(method="get", path=f"{OON_PATH_SINGLE}/{policy_id}")
        try:
            response = await self._connection.request(api_request)
        except Exception:
            response = None

        if isinstance(response, list) and response:
            return response[0]
        if isinstance(response, dict):
            result = response if ("id" in response or "_id" in response) else response.get("data", None)
            if result:
                return result

        # Fallback: search in list
        policies = await self.get_oon_policies()
        match = next((p for p in policies if p.get("id", p.get("_id")) == policy_id), None)
        if match is None:
            raise UniFiNotFoundError("oon_policy", policy_id)
        return match

    async def create_oon_policy(self, policy_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new OON policy.

        Args:
            policy_data: Dictionary containing the policy configuration.
                Required fields:
                - name (str): Policy name
                - enabled (bool): Whether the policy is active
                - target_type (str): "CLIENTS" or "GROUPS"
                - targets (list): MAC addresses or group IDs
                At least one of secure, qos, or route must be configured.

        Returns:
            The created OON policy dictionary, or None on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        if not policy_data.get("name"):
            logger.error("Missing required field 'name' for OON policy")
            return None

        # Strip _id/id if present — let the API assign a new one
        create_data = normalize_oon_create_payload(policy_data)
        create_data.pop("_id", None)
        create_data.pop("id", None)

        try:
            # POST uses singular path, may return 201
            api_request = ApiRequestV2(method="post", path=OON_PATH_SINGLE, data=create_data)
            response = await self._connection.request(api_request)

            self._invalidate_cache()

            if isinstance(response, dict) and ("id" in response or "_id" in response):
                return response
            elif isinstance(response, dict) and "data" in response:
                data = response["data"]
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
                return data
            elif isinstance(response, list) and len(response) > 0:
                return response[0] if isinstance(response[0], dict) else {"id": str(response[0])}
            elif response is None or response == "":
                logger.info("Create returned empty response, verifying via list")
                policies = await self.get_oon_policies()
                created = next(
                    (p for p in policies if p.get("name") == policy_data.get("name")),
                    None,
                )
                return created
            else:
                logger.error("Unexpected response creating OON policy: %s %s", type(response), response)
                return None
        except Exception as e:
            logger.error("Error creating OON policy: %s", e, exc_info=True)
            raise

    async def update_oon_policy(self, policy_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing OON policy by merging updates with current state.

        Returns:
            The merged policy dict.

        Raises:
            UniFiNotFoundError: If the policy does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        existing = await self.get_oon_policy_by_id(policy_id)  # raises on miss
        if not update_data:
            return existing

        # The create path runs this; the update path did not, so a partial
        # update lost both the MAC casing and the bare-string -> {type, value}
        # target shaping. target_type comes from the existing policy when the
        # caller does not restate it.
        update_data = normalize_oon_update_payload(update_data, existing)

        merged_data = deep_merge(existing, update_data)
        api_request = ApiRequestV2(method="put", path=f"{OON_PATH_SINGLE}/{policy_id}", data=merged_data)
        await self._connection.request(api_request)
        self._invalidate_cache()
        return merged_data

    async def toggle_oon_policy(self, policy_id: str) -> Optional[bool]:
        """Toggle an OON policy's enabled state.

        Fetches the current policy, flips the enabled flag, and sends
        the full object back via PUT.

        Args:
            policy_id: The ID of the OON policy to toggle.

        Returns:
            The new enabled state (True/False), or None on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        policy = await self.get_oon_policy_by_id(policy_id)  # raises on miss
        new_state = not policy.get("enabled", False)
        policy["enabled"] = new_state

        api_request = ApiRequestV2(method="put", path=f"{OON_PATH_SINGLE}/{policy_id}", data=policy)
        await self._connection.request(api_request)
        self._invalidate_cache()
        return new_state

    async def delete_oon_policy(self, policy_id: str) -> bool:
        """Delete an OON policy.

        Args:
            policy_id: The ID of the OON policy to delete.

        Returns:
            True on success, False on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            # DELETE may return 204 No Content
            api_request = ApiRequestV2(method="delete", path=f"{OON_PATH_SINGLE}/{policy_id}")
            await self._connection.request(api_request)

            self._invalidate_cache()
            return True
        except Exception as e:
            logger.error("Error deleting OON policy %s: %s", policy_id, e, exc_info=True)
            raise

    def _invalidate_cache(self):
        """Invalidate all OON policy caches."""
        self._connection._invalidate_cache(CACHE_PREFIX_OON_POLICIES)
