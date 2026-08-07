import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_QOS = "qos_rules"


class QosManager:
    """Manages QoS (Quality of Service) rules on the Unifi Controller."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the QoS Manager.

        Args:
            connection_manager: The shared ConnectionManager instance.
        """
        self._connection = connection_manager

    async def get_qos_rules(self) -> List[Dict[str, Any]]:
        """Get QoS rules for the current site."""
        cache_key = f"{CACHE_PREFIX_QOS}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequestV2(method="get", path="/qos-rules")
            response = await self._connection.request(api_request)
            rules = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )
            self._connection._update_cache(cache_key, rules)
            return rules
        except Exception as e:
            logger.error("Error getting QoS rules: %s", e)
            raise

    async def get_qos_rule_details(self, rule_id: str) -> Dict[str, Any]:
        """Get detailed information for a specific QoS rule.

        Raises:
            UniFiNotFoundError: If the rule does not exist.
        """
        all_rules = await self.get_qos_rules()
        rule = next((r for r in all_rules if r.get("_id") == rule_id), None)
        if rule is None:
            raise UniFiNotFoundError("qos_rule", rule_id)
        return rule

    async def update_qos_rule(self, rule_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a QoS rule by merging updates with existing data.

        Returns:
            The merged rule dict.

        Raises:
            UniFiNotFoundError: If the rule does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        existing_rule = await self.get_qos_rule_details(rule_id)  # raises on miss
        if not update_data:
            return existing_rule

        merged_data = deep_merge(existing_rule, update_data)
        api_request = ApiRequestV2(
            method="put",
            path=f"/qos-rules/{rule_id}",
            data=merged_data,
        )
        await self._connection.request(api_request)
        self._connection._invalidate_cache(f"{CACHE_PREFIX_QOS}_{self._connection.site}")
        return merged_data

    async def toggle_qos_rule_enabled(self, rule_id: str) -> Dict[str, Any]:
        """Invert a QoS rule's enabled state using the shared fetch-merge-put path."""
        existing_rule = await self.get_qos_rule_details(rule_id)
        return await self.update_qos_rule(rule_id, {"enabled": not existing_rule.get("enabled", False)})

    async def create_qos_rule(self, rule_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new QoS rule.

        Args:
            rule_data: Dictionary with rule data

        Returns:
            The created rule data if successful, None otherwise
        """
        try:
            required_fields = ["name", "enabled"]
            for field in required_fields:
                if field not in rule_data:
                    logger.error("Missing required field '%s' for QoS rule creation", field)
                    return None

            api_request = ApiRequestV2(method="post", path="/qos-rules", data=rule_data)
            response = await self._connection.request(api_request)
            logger.info("Create command sent for QoS rule '%s'", rule_data.get("name"))
            self._connection._invalidate_cache(f"{CACHE_PREFIX_QOS}_{self._connection.site}")

            if (
                isinstance(response, dict)
                and "data" in response
                and isinstance(response["data"], list)
                and len(response["data"]) > 0
            ):
                return response["data"][0]
            elif (
                isinstance(response, list) and len(response) > 0 and isinstance(response[0], dict)
            ):  # Handle cases where API returns a list
                return response[0]
            logger.warning("Could not extract created QoS rule data from response: %s", response)
            return response  # Return raw response if extraction fails

        except Exception as e:
            logger.error("Error creating QoS rule: %s", e)
            raise

    async def delete_qos_rule(self, rule_id: str) -> bool:
        """Delete a QoS rule.

        Args:
            rule_id: ID of the rule to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            api_request = ApiRequestV2(method="delete", path=f"/qos-rules/{rule_id}")
            await self._connection.request(api_request)
            logger.info("Delete command sent for QoS rule %s", rule_id)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_QOS}_{self._connection.site}")
            return True
        except Exception as e:
            logger.error("Error deleting QoS rule %s: %s", rule_id, e)
            raise
