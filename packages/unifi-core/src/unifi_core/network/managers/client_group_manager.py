"""Manager for client groups (network member groups) on the UniFi controller.

Client groups organize devices by MAC address for use in OON policies,
firewall rules, and other network configurations. Groups have a name,
type (CLIENTS), and a list of member MAC addresses.

API endpoint: /proxy/network/v2/api/site/{site}/network-members-group
"""

import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.mac import normalize_mac_list
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_CLIENT_GROUPS = "client_groups"


class ClientGroupManager:
    """Manages client groups (network member groups) on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    async def get_client_groups(self) -> List[Dict[str, Any]]:
        """Get all client groups.

        Returns:
            List of client group dictionaries.
        """
        cache_key = f"{CACHE_PREFIX_CLIENT_GROUPS}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequestV2(method="get", path="/network-members-groups")
            response = await self._connection.request(api_request)

            groups = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )

            self._connection._update_cache(cache_key, groups)
            return groups
        except Exception as e:
            logger.error("Error getting client groups: %s", e)
            raise

    async def get_client_group_by_id(self, group_id: str) -> Dict[str, Any]:
        """Get a specific client group by ID.

        Raises:
            UniFiNotFoundError: If the group does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        api_request = ApiRequestV2(method="get", path=f"/network-members-group/{group_id}")
        try:
            response = await self._connection.request(api_request)
        except Exception:
            response = None

        match: Optional[Dict[str, Any]] = None
        if isinstance(response, list) and response:
            match = response[0]
        elif isinstance(response, dict):
            if "id" in response or "_id" in response:
                match = response
            else:
                match = response.get("data", None)

        if match is None:
            # Fallback: search the list (handles 405 / soft errors on by-id endpoint).
            groups = await self.get_client_groups()
            match = next((g for g in groups if g.get("_id", g.get("id")) == group_id), None)

        if match is None:
            raise UniFiNotFoundError("client_group", group_id)
        return match

    async def create_client_group(self, group_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new client group.

        Args:
            group_data: Dictionary containing the group configuration.
                Required fields:
                - name (str): Group name
                - members (list): List of MAC addresses
                - type (str): "CLIENTS"

        Returns:
            The created client group dictionary, or None on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        required_keys = {"name", "members", "type"}
        missing = required_keys - group_data.keys()
        if missing:
            logger.error("Missing required keys for client group: %s", missing)
            return None

        # Normalized here rather than in each caller: the MCP tool and the
        # apps/api dispatch both assemble this dict themselves, so a model
        # validator never sees it.
        if isinstance(group_data.get("members"), list):
            group_data = {**group_data, "members": normalize_mac_list(group_data["members"])}

        try:
            api_request = ApiRequestV2(method="post", path="/network-members-group", data=group_data)
            response = await self._connection.request(api_request)

            self._invalidate_cache()

            if isinstance(response, dict) and ("id" in response or "_id" in response):
                return response
            elif isinstance(response, dict) and "data" in response:
                return response["data"]
            elif isinstance(response, list) and len(response) > 0:
                return response[0] if isinstance(response[0], dict) else {"id": str(response[0])}
            elif response is None or response == "":
                logger.info("Create returned empty response, verifying via list")
                groups = await self.get_client_groups()
                created = next(
                    (g for g in groups if g.get("name") == group_data.get("name")),
                    None,
                )
                return created
            else:
                logger.error("Unexpected response creating client group: %s %s", type(response), response)
                return None
        except Exception as e:
            logger.error("Error creating client group: %s", e, exc_info=True)
            raise

    async def update_client_group(self, group_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing client group by merging updates with current state.

        Returns:
            The merged group dict.

        Raises:
            UniFiNotFoundError: If the group does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        existing = await self.get_client_group_by_id(group_id)  # raises on miss
        if not update_data:
            return existing

        merged_data = deep_merge(existing, update_data)
        api_request = ApiRequestV2(method="put", path=f"/network-members-group/{group_id}", data=merged_data)
        await self._connection.request(api_request)
        self._invalidate_cache()
        return merged_data

    async def delete_client_group(self, group_id: str) -> bool:
        """Delete a client group.

        Args:
            group_id: The ID of the client group to delete.

        Returns:
            True on success, False on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequestV2(method="delete", path=f"/network-members-group/{group_id}")
            await self._connection.request(api_request)

            self._invalidate_cache()
            return True
        except Exception as e:
            logger.error("Error deleting client group %s: %s", group_id, e, exc_info=True)
            raise

    def _invalidate_cache(self):
        """Invalidate all client group caches."""
        self._connection._invalidate_cache(CACHE_PREFIX_CLIENT_GROUPS)
