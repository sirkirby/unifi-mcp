"""Hosts, sites and devices from the Site Manager API.

These three collections are paged by the API. One call here fetches one page
and returns the token for the next; nothing crawls every page on its own.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from unifi_core.exceptions import UniFiMalformedResponseError, UniFiValidationError
from unifi_core.sitemanager.managers.connection_manager import SiteManagerConnectionManager, path_segment
from unifi_core.sitemanager.models.devices import HostDevices, host_devices_from_api
from unifi_core.sitemanager.models.hosts import Host, host_from_api
from unifi_core.sitemanager.models.sites import Site, site_from_api

MAX_PAGE_SIZE = 500
MAX_HOST_FILTER = 100


def page_params(page_size: int | None, next_token: str | None) -> list[tuple[str, str]]:
    """Query parameters for one page of a paged collection."""
    params: list[tuple[str, str]] = []
    if page_size is not None:
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise UniFiValidationError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        params.append(("pageSize", str(page_size)))
    if next_token is not None:
        if not isinstance(next_token, str) or not next_token.strip():
            raise UniFiValidationError("next_token must be the token returned by the previous page")
        params.append(("nextToken", next_token))
    return params


def rfc3339(value: Any, name: str) -> str:
    """Return ``value`` if it is an RFC 3339 timestamp with a UTC offset."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            return value
    raise UniFiValidationError(f"{name} must be an RFC 3339 timestamp such as 2026-01-31T00:00:00Z")


def _entries(data: Any, what: str) -> list[Any]:
    if not isinstance(data, list):
        raise UniFiMalformedResponseError(f"Site Manager API returned an unreadable {what} list.")
    return data


class InventoryManager:
    """Reads the account's hosts, sites and devices."""

    def __init__(self, connection: SiteManagerConnectionManager) -> None:
        self._connection = connection

    async def list_hosts(
        self, *, page_size: int | None = None, next_token: str | None = None
    ) -> tuple[list[Host], str | None]:
        response = await self._connection.get("/v1/hosts", params=page_params(page_size, next_token))
        return [host_from_api(entry) for entry in _entries(response.data, "host")], response.next_token

    async def get_host(self, host_id: str, *, include_reported_state: bool = False) -> Host:
        response = await self._connection.get(f"/v1/hosts/{path_segment(host_id, 'host')}", resource=("Host", host_id))
        if not isinstance(response.data, dict):
            raise UniFiMalformedResponseError("Site Manager API returned an unreadable host.")
        return host_from_api(response.data, include_reported_state=include_reported_state)

    async def list_sites(
        self, *, page_size: int | None = None, next_token: str | None = None
    ) -> tuple[list[Site], str | None]:
        response = await self._connection.get("/v1/sites", params=page_params(page_size, next_token))
        return [site_from_api(entry) for entry in _entries(response.data, "site")], response.next_token

    async def list_devices(
        self,
        *,
        host_ids: list[str] | None = None,
        updated_since: str | None = None,
        page_size: int | None = None,
        next_token: str | None = None,
    ) -> tuple[list[HostDevices], str | None]:
        """List devices grouped by host, optionally only for ``host_ids``."""
        params = page_params(page_size, next_token)
        if host_ids is not None:
            if (
                not isinstance(host_ids, list)
                or not 1 <= len(host_ids) <= MAX_HOST_FILTER
                or not all(isinstance(host_id, str) and host_id.strip() for host_id in host_ids)
            ):
                raise UniFiValidationError(f"host_ids must list between 1 and {MAX_HOST_FILTER} host ids")
            params.extend(("hostIds[]", host_id) for host_id in host_ids)
        if updated_since is not None:
            params.append(("time", rfc3339(updated_since, "updated_since")))
        response = await self._connection.get("/v1/devices", params=params)
        return [host_devices_from_api(entry) for entry in _entries(response.data, "device")], response.next_token
