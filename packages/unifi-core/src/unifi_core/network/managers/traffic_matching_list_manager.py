"""Manager for Integration API traffic matching lists.

Traffic matching lists are reusable IP/IPv4/port lists referenced by firewall
policy traffic filters through ``trafficMatchingListId``. They are a distinct
Integration API resource (UUIDs) from the V1 firewall groups and the V2 MAC
ACL rules; IDs are not portable across those resources.

API endpoint: /proxy/network/integration/v1/sites/{siteId}/traffic-matching-lists
"""

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from unifi_core.auth import UniFiAuth, api_key_variables
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiMalformedResponseError,
    UniFiOperationError,
    UniFiPermissionError,
)
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.models.traffic_matching_lists import to_controller_create
from unifi_core.operation_gate import write_request_bound
from unifi_core.request_paths import check_request_path, object_id
from unifi_core.tls import CertificateVerificationError, certificate_failure, is_certificate_error

logger = logging.getLogger("unifi-network-mcp")

INTEGRATION_PAGE_DEFAULT_LIMIT = 25
INTEGRATION_API_PAGE_SIZE = 200


def _missing_key_message(env_prefix: str | None) -> str:
    """Fixed text naming the setting that enables the traffic matching list family.

    The ``UNIFI_*`` variables are named only for a caller that reads them
    (``env_prefix`` set by an MCP server); the API server keeps the key on the
    controller record instead.
    """
    variables = api_key_variables(env_prefix)
    if variables:
        where = f"set {variables}"
    else:
        where = "add it to this controller's configuration"
    return (
        "Network Integration API access requires a UniFi API key. "
        f"Create a Network API token in UniFi Control Plane -> Integrations and {where}."
    )


def _status_error(status: int) -> Exception:
    """Fixed text for a non-2xx integration-API answer; never quotes the response or URL."""
    prefix = f"Network Integration API request failed (HTTP {status})."
    if status == 401:
        return UniFiAuthError(f"{prefix} The controller rejected the configured API key.")
    if status == 403:
        return UniFiPermissionError(f"{prefix} The API key lacks permission for this Integration API resource.")
    if status == 404:
        return UniFiOperationError(f"{prefix} This controller does not serve that Integration API endpoint.")
    return UniFiOperationError(f"{prefix} The controller refused the request.")


class TrafficMatchingListManager:
    """Manages Integration API traffic matching lists."""

    def __init__(self, connection_manager: ConnectionManager, auth: UniFiAuth | None = None):
        self._connection = connection_manager
        self._auth = auth

    async def _request_integration_api(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call the official UniFi Network integration API.

        The integration API rejects local controller cookies for these
        endpoints, so an API key is required. Errors are typed with fixed
        text — the controller's response body, the URL and the exception text
        never reach callers, logs or audits.

        Raises:
            UniFiAuthError: no API key is configured, or the controller rejected it.
            UniFiPermissionError / UniFiOperationError: any other non-2xx answer.
            UniFiMalformedResponseError: the answer is neither a JSON object nor
                an empty body (an empty 2xx is a documented DELETE success).
        """
        if self._auth is None or not self._auth.has_api_key:
            logger.warning("The traffic matching list family needs a Network API key and none is configured.")
            raise UniFiAuthError(_missing_key_message(getattr(self._connection, "tls_env_prefix", None)))
        # This call bypasses ConnectionManager.request, so the path backstop
        # has to run here before the path reaches the controller URL.
        check_request_path(path)

        base_url = f"https://{self._connection.host}:{self._connection.port}"
        url = f"{base_url}/proxy/network/integration{path}"
        timeout = aiohttp.ClientTimeout(total=10)

        # get_api_key_session() supplies the required X-API-Key header. The
        # integration endpoints reject the local controller cookie session.
        session = await self._auth.get_api_key_session(base_url)

        cert_failure: CertificateVerificationError | None = None
        try:
            # Inside a held write, bounded by what is left of its hold budget;
            # a no-op for reads. The POST and DELETE this manager sends are
            # writes and must mark the write ticket.
            async with (
                write_request_bound(),
                session.request(
                    method.upper(),
                    url,
                    params=params,
                    json=data,
                    ssl=self._connection.ssl,
                    timeout=timeout,
                    allow_redirects=False,
                ) as resp,
            ):
                if resp.status < 200 or resp.status >= 300:
                    logger.error("Integration API returned %s for %s", resp.status, path)
                    raise _status_error(resp.status)
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    # An empty 2xx body is a documented DELETE success.
                    return {}
                if body is None:
                    # A literal JSON null is the same empty-body DELETE success.
                    return {}
                if not isinstance(body, dict):
                    raise UniFiMalformedResponseError("Network Integration API response was not a JSON object.")
                return body
        except (UniFiAuthError, UniFiPermissionError, UniFiOperationError, UniFiMalformedResponseError):
            raise
        except Exception as e:
            if not is_certificate_error(e):
                raise
            # The certificate error's text names the controller and, for a pin
            # mismatch, both fingerprints. Keep the class and fixed guidance only.
            cert_failure = certificate_failure(e, env_prefix=self._connection.tls_env_prefix)
        finally:
            await session.close()
        # Raised outside the handler, and from None, so no traceback renders the original
        # or an exception a caller is handling. Unreachable without a cert failure:
        # every other error path above re-raised or returned.
        if cert_failure is not None:
            raise cert_failure from None
        raise UniFiOperationError("Network Integration API request failed without a response.")

    async def _get_integration_site_id(self) -> str:
        """Resolve the configured site name/key to the integration API site ID."""
        cache_key = f"integrations_site_id_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if isinstance(cached, str) and cached:
            return cached

        result = await self._request_integration_api("get", "/v1/sites")
        sites = result.get("data", []) if isinstance(result, dict) else []
        if not isinstance(sites, list) or not sites:
            return self._connection.site

        configured = self._connection.site
        match = next(
            (
                s
                for s in sites
                if isinstance(s, dict)
                and configured
                in {
                    str(s.get("id", "")),
                    str(s.get("name", "")),
                    str(s.get("key", "")),
                    str(s.get("siteId", "")),
                }
            ),
            None,
        )
        if match is None and len(sites) == 1 and isinstance(sites[0], dict):
            match = sites[0]

        site_id = str((match or {}).get("id") or configured)
        self._connection._update_cache(cache_key, site_id)
        return site_id

    async def list_traffic_matching_lists(
        self,
        *,
        offset: int = 0,
        limit: int = INTEGRATION_PAGE_DEFAULT_LIMIT,
        filter_expr: Optional[str] = None,
        site_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List traffic matching lists on a site.

        Returns:
            The raw page payload: ``count``, ``data[]``, ``limit``, ``offset``,
            ``totalCount``.
        """
        resolved_site = site_id or await self._get_integration_site_id()
        path = f"/v1/sites/{object_id(resolved_site, 'site')}/traffic-matching-lists"
        params: Dict[str, str] = {"offset": str(int(offset)), "limit": str(int(limit))}
        if filter_expr:
            params["filter"] = filter_expr
        result = await self._request_integration_api("get", path, params=params)
        if not isinstance(result.get("data"), list):
            raise UniFiMalformedResponseError("Controller returned an invalid traffic matching list page")
        return result

    async def list_all_traffic_matching_lists(self, *, site_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return every list on a site, across all Integration API pages.

        Cursor-paginated REST and GraphQL reads need the complete snapshot; the
        paged ``list_traffic_matching_lists`` stays available for callers that
        request one page explicitly.
        """
        lists: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.list_traffic_matching_lists(
                offset=offset, limit=INTEGRATION_API_PAGE_SIZE, site_id=site_id
            )
            data = page.get("data", [])
            if not isinstance(data, list):
                raise UniFiMalformedResponseError("Controller returned an invalid traffic matching list page")
            rows = [item for item in data if isinstance(item, dict)]
            lists.extend(rows)
            total_count = page.get("totalCount")
            if not rows or not isinstance(total_count, int) or len(lists) >= total_count:
                return lists
            offset += len(data)

    async def get_traffic_matching_list(self, list_id: str, *, site_id: Optional[str] = None) -> Dict[str, Any]:
        """Read one traffic matching list, including its items."""
        resolved_site = site_id or await self._get_integration_site_id()
        path = (
            f"/v1/sites/{object_id(resolved_site, 'site')}/traffic-matching-lists/"
            f"{object_id(list_id, 'traffic matching list')}"
        )
        result = await self._request_integration_api("get", path)
        if not isinstance(result, dict) or not result:
            raise UniFiMalformedResponseError("Controller returned an invalid traffic matching list response")
        return result

    async def create_traffic_matching_list(
        self,
        name: str,
        list_type: str,
        *,
        items: Optional[List[Dict[str, Any]]] = None,
        site_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a traffic matching list.

        The published create body is ``name`` plus ``type``; the list DTOs also
        carry ``items`` (Port matching / IPv4 matching), so an explicit items
        list is sent when the caller supplies one. The controller is the
        authority on accepted item shapes: no item keys are invented here.
        """
        if not name or not name.strip():
            raise ValueError("name is required")
        if not list_type or not list_type.strip():
            raise ValueError("type is required")
        if items is not None and (not isinstance(items, list) or not all(isinstance(item, dict) for item in items)):
            raise ValueError("items must be a list of objects")
        payload = to_controller_create(name, list_type, items)

        resolved_site = site_id or await self._get_integration_site_id()
        path = f"/v1/sites/{object_id(resolved_site, 'site')}/traffic-matching-lists"
        result = await self._request_integration_api("post", path, data=payload)
        if not isinstance(result, dict) or not result:
            raise UniFiMalformedResponseError("Controller returned an invalid traffic matching list create response")
        return result

    async def delete_traffic_matching_list(self, list_id: str, *, site_id: Optional[str] = None) -> bool:
        """Delete a traffic matching list.

        A list referenced by firewall policies may be refused by the
        controller; that error is raised, never swallowed.
        """
        resolved_site = site_id or await self._get_integration_site_id()
        path = (
            f"/v1/sites/{object_id(resolved_site, 'site')}/traffic-matching-lists/"
            f"{object_id(list_id, 'traffic matching list')}"
        )
        await self._request_integration_api("delete", path)
        return True
