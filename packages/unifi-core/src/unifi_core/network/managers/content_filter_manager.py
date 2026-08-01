"""Manager for content filtering profiles on the UniFi controller.

Content filtering uses DNS-based category blocking and safe search
enforcement. Profiles can be applied per-client (by MAC address)
or per-network (by network ID).

NOTE: The UniFi API does not support creating content filtering profiles
via POST. Profiles must be created through the UniFi UI first, then
managed (list, update, delete) via the API.

API endpoint: /proxy/network/v2/api/site/{site}/content-filtering
Supported methods:
  GET  /content-filtering        — list all profiles
  PUT  /content-filtering/{id}   — update a profile
  DELETE /content-filtering/{id} — delete a profile
Not supported:
  POST /content-filtering        — returns 405
  GET  /content-filtering/{id}   — returns 405 (use list + filter)
"""

import logging
from typing import Any, Dict, List

from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.merge import deep_merge
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_CONTENT_FILTERS = "content_filters"


class ContentFilterManager:
    """Manages content filtering profiles on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    async def get_content_filters(self) -> List[Dict[str, Any]]:
        """Get all content filtering profiles.

        Returns:
            List of content filtering profile dictionaries.
        """
        cache_key = f"{CACHE_PREFIX_CONTENT_FILTERS}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        try:
            api_request = ApiRequestV2(method="get", path="/content-filtering")
            response = await self._connection.request(api_request)

            filters = (
                response
                if isinstance(response, list)
                else response.get("data", [])
                if isinstance(response, dict)
                else []
            )

            self._connection._update_cache(cache_key, filters)
            return filters
        except Exception as e:
            logger.error("Error getting content filters: %s", e)
            raise

    async def get_content_filter_by_id(self, filter_id: str) -> Dict[str, Any]:
        """Get a specific content filtering profile by ID.

        The API does not support GET /content-filtering/{id} (returns 405),
        so this method fetches all profiles and filters by ID.

        Raises:
            UniFiNotFoundError: If the profile does not exist.
        """
        filters = await self.get_content_filters()
        match = next((f for f in filters if f.get("_id", f.get("id")) == filter_id), None)
        if match is None:
            raise UniFiNotFoundError("content_filter", filter_id)
        return match

    async def update_content_filter(self, filter_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing content filtering profile by merging updates with current state.

        Returns:
            The merged profile dict.

        Raises:
            UniFiNotFoundError: If the profile does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        existing = await self.get_content_filter_by_id(filter_id)  # raises on miss
        if not update_data:
            return existing

        merged_data = deep_merge(existing, update_data)
        api_request = ApiRequestV2(method="put", path=f"/content-filtering/{filter_id}", data=merged_data)
        await self._connection.request(api_request)
        self._invalidate_cache()
        return merged_data

    async def delete_content_filter(self, filter_id: str) -> bool:
        """Delete a content filtering profile.

        Args:
            filter_id: The ID of the profile to delete.

        Returns:
            True on success, False on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequestV2(method="delete", path=f"/content-filtering/{filter_id}")
            await self._connection.request(api_request)

            self._invalidate_cache()
            return True
        except Exception as e:
            logger.error("Error deleting content filter %s: %s", filter_id, e, exc_info=True)
            raise

    def _invalidate_cache(self):
        """Invalidate all content filter caches."""
        self._connection._invalidate_cache(CACHE_PREFIX_CONTENT_FILTERS)
