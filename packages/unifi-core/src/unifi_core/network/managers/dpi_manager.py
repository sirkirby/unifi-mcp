"""Manager for DPI (Deep Packet Inspection) application lookups on the UniFi controller.

Provides read-only access to the DPI application and category database
via the official UniFi integration API. Applications are identified by
compound IDs: (category_id << 16) | app_id.

Requires an API key (UNIFI_API_KEY or UNIFI_NETWORK_API_KEY).

API endpoints (official integration API):
  GET /proxy/network/integration/v1/dpi/applications  (paginated; some
      controller versions cap each response at 200 records)
  GET /proxy/network/integration/v1/dpi/categories    (paginated)

Catalogue coverage is controller- and firmware-dependent. Callers must keep
unresolved names null rather than infer them from a partial catalogue.
"""

import logging
from typing import Any, Dict, Optional

import aiohttp

from unifi_core.auth import UniFiAuth
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_DPI_APPS = "dpi_apps"
CACHE_PREFIX_DPI_CATEGORIES = "dpi_categories"
CACHE_PREFIX_DPI_CATALOG = "dpi_catalog"
_DPI_CATALOG_CACHE_TTL = 900


class DpiManager:
    """Manages DPI application and category lookups via the official UniFi API."""

    def __init__(self, connection_manager: ConnectionManager, auth: UniFiAuth | None):
        self._connection = connection_manager
        self._auth = auth

    async def _request_integration_api(self, path: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a request to the official integration API using the shared auth module.

        Args:
            path: API path (e.g., '/v1/dpi/applications')
            params: Optional query parameters

        Returns:
            Response dict, or None on failure.
        """
        if self._auth is None or not self._auth.has_api_key:
            logger.error(
                "DPI integration API requires an API key. "
                "Configure the controller with an API token (Settings → "
                "Control Plane → Integrations) or set UNIFI_API_KEY / "
                "UNIFI_NETWORK_API_KEY in the network MCP environment."
            )
            return None

        base_url = f"https://{self._connection.host}:{self._connection.port}"
        url = f"{base_url}/proxy/network/integration{path}"

        try:
            session = await self._auth.get_api_key_session()
            try:
                async with session.get(
                    url,
                    params=params,
                    ssl=self._connection.verify_ssl,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error("Integration API returned %s for %s", resp.status, path)
                        return None
            finally:
                await session.close()
        except Exception as e:
            logger.error("Error calling integration API %s: %s", path, e)
            raise

    async def get_dpi_applications(
        self,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get DPI applications from the official API.

        Args:
            limit: Max results per page (default 100).
            offset: Pagination offset.
            search: Optional name search (client-side filtering — the API
                    does not support server-side text search).

        Returns:
            Dict with 'data', 'totalCount', 'offset', 'limit' keys.
        """
        # When searching, fetch all apps so client-side filter works correctly.
        # Otherwise use the requested limit/offset for pagination.
        if search:
            fetch_limit = 2500
            fetch_offset = 0
        else:
            fetch_limit = limit
            fetch_offset = offset

        cache_key = f"{CACHE_PREFIX_DPI_APPS}_{fetch_limit}_{fetch_offset}_{self._connection.site}"
        if not search:
            cached_data = self._connection.get_cached(cache_key)
            if cached_data is not None:
                return cached_data

        params = {"limit": str(fetch_limit), "offset": str(fetch_offset)}
        result = await self._request_integration_api("/v1/dpi/applications", params)

        if result is None:
            return {"data": [], "totalCount": 0, "offset": offset, "limit": limit}

        # Client-side search filtering (API doesn't support text search)
        if search and result.get("data"):
            search_lower = search.lower()
            filtered = [a for a in result["data"] if search_lower in a.get("name", "").lower()]
            result = {
                "data": filtered,
                "totalCount": len(filtered),
                "offset": 0,
                "limit": len(filtered),
                "filtered_from": result.get("totalCount", 0),
            }
        elif not search:
            self._connection._update_cache(cache_key, result)

        return result

    async def _get_all_integration_pages(self, path: str, resource: str) -> list[dict[str, Any]]:
        """Fetch every page from a DPI Integration-API collection."""
        first_page = await self._request_integration_api(path, {"limit": "2500", "offset": "0"})
        if first_page is None:
            raise RuntimeError(f"failed to fetch DPI {resource} catalogue")

        entries = list(first_page.get("data") or [])
        total_count = int(first_page.get("totalCount") or len(entries))
        page_size = len(entries)
        if total_count > page_size and page_size == 0:
            raise RuntimeError(f"incomplete DPI {resource} catalogue")

        for offset in range(page_size, total_count, page_size or 1):
            page = await self._request_integration_api(path, {"limit": "2500", "offset": str(offset)})
            page_entries = list((page or {}).get("data") or [])
            if not page_entries:
                raise RuntimeError(f"incomplete DPI {resource} catalogue")
            entries.extend(page_entries)

        if len(entries) < total_count:
            raise RuntimeError(f"incomplete DPI {resource} catalogue")
        return entries[:total_count]

    async def get_full_dpi_catalog(self) -> Dict[str, list[dict[str, Any]]]:
        """Fetch a complete, cached DPI catalogue for ID-to-name resolution.

        Network App may cap DPI collection responses below the requested limit,
        so page using the controller's returned page size until ``totalCount``
        is exhausted.
        """
        cache_key = f"{CACHE_PREFIX_DPI_CATALOG}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key, timeout=_DPI_CATALOG_CACHE_TTL)
        if cached_data is not None:
            return cached_data

        result = {
            "applications": await self._get_all_integration_pages("/v1/dpi/applications", "application"),
            "categories": await self._get_all_integration_pages("/v1/dpi/categories", "category"),
        }
        self._connection._update_cache(cache_key, result, timeout=_DPI_CATALOG_CACHE_TTL)
        return result

    async def get_dpi_categories(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get DPI categories from the official API.

        Args:
            limit: Max results per page.
            offset: Pagination offset.

        Returns:
            Dict with 'data', 'totalCount', 'offset', 'limit' keys.
        """
        cache_key = f"{CACHE_PREFIX_DPI_CATEGORIES}_{limit}_{offset}_{self._connection.site}"
        cached_data = self._connection.get_cached(cache_key)
        if cached_data is not None:
            return cached_data

        params = {"limit": str(limit), "offset": str(offset)}
        result = await self._request_integration_api("/v1/dpi/categories", params)

        if result is None:
            return {"data": [], "totalCount": 0, "offset": offset, "limit": limit}

        self._connection._update_cache(cache_key, result)
        return result
