"""Manager for DPI (Deep Packet Inspection) application lookups on the UniFi controller.

Provides read-only access to the DPI application and category database
via the official UniFi integration API. Applications are identified by
compound IDs: (category_id << 16) | app_id.

Requires an API key (UNIFI_API_KEY or UNIFI_NETWORK_API_KEY for the MCP
server; the controller's API token for the API server). Without one, or on
any non-200 answer, requests raise with fixed text rather than returning an
empty catalog.

API endpoints (official integration API):
  GET /proxy/network/integration/v1/dpi/applications  (paginated; maximum
      page size 200)
  GET /proxy/network/integration/v1/dpi/categories    (paginated)

Catalogue coverage is controller- and firmware-dependent. Callers must keep
unresolved names null rather than infer them from a partial catalogue.
"""

import logging
from typing import Any, Dict, Optional

import aiohttp

from unifi_core.auth import UniFiAuth
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiMalformedResponseError,
    UniFiOperationError,
    UniFiPermissionError,
)
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.tls import CertificateVerificationError, certificate_failure, is_certificate_error

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_DPI_APPS = "dpi_apps"
CACHE_PREFIX_DPI_CATEGORIES = "dpi_categories"
CACHE_PREFIX_DPI_CATALOG = "dpi_catalog"
_DPI_CATALOG_CACHE_TTL = 900
_DPI_CATALOG_PAGE_SIZE = 200


_KEY_SOURCE = "Settings → Control Plane → Integrations"


def _missing_key_message(env_prefix: str | None) -> str:
    """Fixed text naming the setting that enables the DPI catalog.

    The ``UNIFI_*`` variables are named only for a caller that reads them
    (``env_prefix`` set by an MCP server); the API server keeps the key on the
    controller record instead.
    """
    if isinstance(env_prefix, str) and env_prefix:
        where = f"set UNIFI_{env_prefix}_API_KEY (or UNIFI_API_KEY) in the server environment"
    else:
        where = "add it to this controller's configuration"
    return (
        "The DPI catalog is read through the UniFi integration API, which needs a Network API key, "
        f"and none is configured. Create one on the controller ({_KEY_SOURCE}) and {where}."
    )


def _status_error(status: int) -> Exception:
    """Fixed text for a non-200 integration-API answer; never quotes the response or URL."""
    prefix = f"DPI catalog request failed (HTTP {status})."
    if status == 401:
        return UniFiAuthError(f"{prefix} The controller rejected the configured API key.")
    if status == 403:
        return UniFiPermissionError(f"{prefix} The API key lacks permission to read the DPI catalog.")
    if status == 404:
        return UniFiOperationError(f"{prefix} This controller does not serve the integration DPI endpoint.")
    return UniFiOperationError(prefix)


def _parse_non_negative_integer(value: Any) -> int | None:
    """Return a catalogue integer without accepting bools or fractional values."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


class DpiManager:
    """Manages DPI application and category lookups via the official UniFi API."""

    def __init__(self, connection_manager: ConnectionManager, auth: UniFiAuth | None):
        self._connection = connection_manager
        self._auth = auth

    async def _request_integration_api(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a request to the official integration API using the shared auth module.

        Args:
            path: API path (e.g., '/v1/dpi/applications')
            params: Optional query parameters

        Returns:
            The decoded response object.

        Raises:
            UniFiAuthError: no API key is configured, or the controller rejected it.
            UniFiPermissionError / UniFiOperationError: any other non-200 answer.
            UniFiMalformedResponseError: the answer is not a JSON object.

        An empty catalog is never substituted for a failure: callers would
        report "no DPI applications" for what is a configuration problem.
        """
        if self._auth is None or not self._auth.has_api_key:
            message = _missing_key_message(self._connection.tls_env_prefix)
            logger.warning("%s", message)
            raise UniFiAuthError(message)

        base_url = f"https://{self._connection.host}:{self._connection.port}"
        url = f"{base_url}/proxy/network/integration{path}"

        cert_failure: CertificateVerificationError | None = None
        try:
            session = await self._auth.get_api_key_session(base_url)
            try:
                async with session.get(
                    url,
                    params=params,
                    ssl=self._connection.ssl,
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=False,
                ) as resp:
                    if resp.status != 200:
                        logger.error("Integration API returned %s for %s", resp.status, path)
                        raise _status_error(resp.status)
                    body = await resp.json()
                    if not isinstance(body, dict):
                        raise UniFiMalformedResponseError("DPI catalog response was not a JSON object.")
                    return body
            finally:
                await session.close()
        except (UniFiAuthError, UniFiPermissionError, UniFiOperationError, UniFiMalformedResponseError):
            raise
        except Exception as e:
            if not is_certificate_error(e):
                logger.error("Error calling integration API %s: %s", path, e)
                raise
            # The certificate error's text names the controller and, for a pin
            # mismatch, both fingerprints. Keep the class and fixed guidance only.
            cert_failure = certificate_failure(e, env_prefix=self._connection.tls_env_prefix)
        # Raised outside the handler, and from None, so no traceback renders the original
        # or an exception a caller is handling.
        logger.error("Error calling integration API %s: %s", path, cert_failure)
        raise cert_failure from None

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
        """Fetch and validate every page from a DPI Integration-API collection."""
        entries: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        offset = 0
        total_count: int | None = None

        while total_count is None or len(entries) < total_count:
            try:
                page = await self._request_integration_api(
                    path,
                    {"limit": str(_DPI_CATALOG_PAGE_SIZE), "offset": str(offset)},
                )
            except Exception:
                if offset == 0:
                    # The first page's error says why (missing key, status, TLS).
                    raise
                raise RuntimeError(f"incomplete DPI {resource} catalogue") from None

            page_entries = list(page.get("data") or [])
            raw_total = page.get("totalCount")
            page_total = _parse_non_negative_integer(raw_total)
            if page_total is None:
                raise RuntimeError(f"invalid DPI {resource} catalogue totalCount")
            if total_count is None:
                total_count = page_total
            elif page_total != total_count:
                raise RuntimeError(f"DPI {resource} catalogue changed during pagination")

            reported_offset = page.get("offset")
            if reported_offset is not None:
                parsed_offset = _parse_non_negative_integer(reported_offset)
                if parsed_offset is None or parsed_offset != offset:
                    raise RuntimeError(f"incomplete DPI {resource} catalogue")
            if not page_entries and len(entries) < total_count:
                raise RuntimeError(f"incomplete DPI {resource} catalogue")
            if len(entries) + len(page_entries) > total_count:
                raise RuntimeError(f"inconsistent DPI {resource} catalogue totalCount")

            for entry in page_entries:
                entry_id = entry.get("id")
                if isinstance(entry_id, int):
                    if entry_id in seen_ids:
                        raise RuntimeError(f"duplicate DPI {resource} catalogue entry")
                    seen_ids.add(entry_id)
            entries.extend(page_entries)
            offset += len(page_entries)

        return entries

    async def get_full_dpi_catalog(self) -> Dict[str, list[dict[str, Any]]]:
        """Fetch a complete, cached DPI catalogue for ID-to-name resolution."""
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

        self._connection._update_cache(cache_key, result)
        return result
