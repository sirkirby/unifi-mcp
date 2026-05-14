"""DNS record management for UniFi Network MCP server.

Provides CRUD operations for static DNS records via the v2 API.
Endpoint: GET/POST/PUT/DELETE /v2/api/site/{site}/static-dns[/{id}]
"""

import logging
from typing import Any, Dict, List, Optional

from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_DNS = "dns_records"


class DnsManager:
    """Manages DNS record operations on the UniFi controller."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    async def list_dns_records(self) -> List[Dict[str, Any]]:
        """List all static DNS records.

        Returns:
            List of DNS record dicts.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")
        cache_key = f"{CACHE_PREFIX_DNS}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=300)
        if cached_data is not None:
            return cached_data

        try:
            api_request = ApiRequestV2(method="get", path="/static-dns")
            response = await self._connection.request(api_request)
            result = response if isinstance(response, list) else []
            self._connection._update_cache(cache_key, result, timeout=300)
            return result
        except Exception as e:
            logger.error("Error listing DNS records: %s", e, exc_info=True)
            raise

    async def get_dns_record(self, record_id: str) -> Dict[str, Any]:
        """Get a DNS record by ID.

        GET by ID returns 405 on this endpoint, so we list and filter.

        Raises:
            UniFiNotFoundError: If the record does not exist.
        """
        records = await self.list_dns_records()
        for record in records:
            if record.get("_id") == record_id:
                return record
        raise UniFiNotFoundError("dns_record", record_id)

    async def create_dns_record(self, record_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new static DNS record.

        Args:
            record_data: Dict with key (hostname), value (target), record_type, enabled.

        Returns:
            Created record dict with _id, or None on failure.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        try:
            api_request = ApiRequestV2(method="post", path="/static-dns", data=record_data)
            response = await self._connection.request(api_request)
            self._connection._invalidate_cache(f"{CACHE_PREFIX_DNS}_{self._connection.site}")
            if isinstance(response, dict) and response.get("_id"):
                return response
            if isinstance(response, list) and response:
                return response[0]
            return response
        except Exception as e:
            logger.error("Error creating DNS record: %s", e, exc_info=True)
            raise

    async def update_dns_record(self, record_id: str, record_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing DNS record.

        Fetches current record, merges updates, PUTs full object. Raises
        ``UniFiNotFoundError`` if the record does not exist.

        Returns:
            The merged record dict.

        Raises:
            UniFiNotFoundError: If the record does not exist.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        current = await self.get_dns_record(record_id)  # raises UniFiNotFoundError on miss
        merged = {**current, **record_data}

        api_request = ApiRequestV2(method="put", path=f"/static-dns/{record_id}", data=merged)
        await self._connection.request(api_request)
        self._connection._invalidate_cache(f"{CACHE_PREFIX_DNS}_{self._connection.site}")
        return merged

    async def delete_dns_record(self, record_id: str) -> bool:
        """Delete a DNS record.

        Idempotent: returns True even if the record doesn't exist (controller
        404 is treated as already-deleted).

        Returns:
            True on success.

        Raises:
            UniFiOperationError: If the controller rejects the delete for
                reasons other than not-found.
        """
        if not await self._connection.ensure_connected():
            raise ConnectionError("Not connected to controller")

        api_request = ApiRequestV2(method="delete", path=f"/static-dns/{record_id}")
        await self._connection.request(api_request)
        self._connection._invalidate_cache(f"{CACHE_PREFIX_DNS}_{self._connection.site}")
        return True
