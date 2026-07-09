"""Dynamic DNS management for UniFi Network MCP server.

Provides CRUD operations for the controller's native Dynamic DNS provider
entries via the V1 REST API.
Endpoint: GET/POST/PUT/DELETE /rest/dynamicdns[/{id}]
"""

import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_DDNS = "dynamic_dns"


class DynamicDnsManager:
    """Manages Dynamic DNS provider entries on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    async def list_dynamic_dns(self) -> List[Dict[str, Any]]:
        """List all Dynamic DNS entries.

        Returns:
            List of Dynamic DNS entry dicts.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        cache_key = f"{CACHE_PREFIX_DDNS}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequest(method="get", path="/rest/dynamicdns")
            response = await self._connection.request(api_request)
            result = response if isinstance(response, list) else []
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Error listing Dynamic DNS entries: %s", e, exc_info=True)
            raise

    async def get_dynamic_dns(self, entry_id: str) -> Dict[str, Any]:
        """Get a Dynamic DNS entry by ID.

        GET by ID returns 405 on this endpoint, so we list and filter.

        Raises:
            UniFiNotFoundError: If the entry does not exist.
        """
        entries = await self.list_dynamic_dns()
        for entry in entries:
            if entry.get("_id") == entry_id:
                return entry
        raise UniFiNotFoundError("dynamic_dns", entry_id)

    async def create_dynamic_dns(self, entry_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new Dynamic DNS entry.

        Args:
            entry_data: Dict with host_name, service, interface, and provider
                credentials (login, x_password) as required by the service.

        Returns:
            Created entry dict with _id, or the raw response on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequest(method="post", path="/rest/dynamicdns", data=entry_data)
            response = await self._connection.request(api_request)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_DDNS}_{self._connection.site}")
            if isinstance(response, dict) and response.get("_id"):
                return response
            if isinstance(response, list) and response:
                return response[0]
            return response
        except Exception as e:
            logger.error("Error creating Dynamic DNS entry: %s", e, exc_info=True)
            raise

    async def update_dynamic_dns(self, entry_id: str, entry_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing Dynamic DNS entry.

        Fetches the current entry, merges the caller's partial update, and PUTs
        the full object so unspecified fields are preserved.

        Returns:
            The merged entry dict.

        Raises:
            UniFiNotFoundError: If the entry does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        current = await self.get_dynamic_dns(entry_id)  # raises UniFiNotFoundError on miss
        merged = {**current, **entry_data}

        api_request = ApiRequest(method="put", path=f"/rest/dynamicdns/{entry_id}", data=merged)
        await self._connection.request(api_request)
        self._connection._invalidate_cache(f"{CACHE_PREFIX_DDNS}_{self._connection.site}")
        return merged

    async def delete_dynamic_dns(self, entry_id: str) -> bool:
        """Delete a Dynamic DNS entry.

        Returns:
            True on success.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        api_request = ApiRequest(method="delete", path=f"/rest/dynamicdns/{entry_id}")
        await self._connection.request(api_request)
        self._connection._invalidate_cache(f"{CACHE_PREFIX_DDNS}_{self._connection.site}")
        return True
