"""System management for UniFi Access.

Provides methods to query Access system information, health,
and user listings from the Access controller.  Each method
tries the API client first (if available) and falls back to
the proxy session path.

Proxy paths discovered via browser inspection:
- ``access/info`` -- Access application info (version, etc.)
- ``dashboard/stats?expand[]=stats.hub&...`` -- dashboard statistics
- ``settings`` -- Access settings
- Users are under the ULP-Go sub-proxy:
  ``/proxy/access/ulp-go/api/v2/users/search?page_num=1&page_size=25``
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from unifi_core.access.managers.connection_manager import AccessConnectionManager, reconnects_on_demand

logger = logging.getLogger(__name__)

# Fields to keep in compact mode.  The stripped fields (scopes at 74%,
# permissions, groups, roles, resources, SSO fields, empty strings)
# account for ~85% of per-user payload size.
_COMPACT_USER_KEYS = frozenset(
    {
        "unique_id",
        "full_name",
        "email",
        "status",
        "nfc_display_id",
        "nfc_card_type",
        "create_time",
        "last_activity_time",
    }
)

# Query parameters for the dashboard stats endpoint (includes all
# useful expansions discovered from browser network inspection).
_STATS_EXPAND = (
    "expand[]=stats.hub"
    "&expand[]=stats.reader"
    "&expand[]=stats.viewer"
    "&expand[]=stats.visitor"
    "&expand[]=stats.credential"
    "&expand[]=stats.user"
)


@reconnects_on_demand
class SystemManager:
    """Reads system-level data from the Access controller."""

    def __init__(self, connection_manager: AccessConnectionManager) -> None:
        self._cm = connection_manager

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compact_user(user: Dict[str, Any]) -> Dict[str, Any]:
        """Strip low-value fields from a user dict.

        Keeps identity, status, credential, and activity fields.
        Strips scopes (74%), permissions, groups, roles, resources,
        SSO fields, and empty string fields (~85% smaller).
        """
        return {k: v for k, v in user.items() if k in _COMPACT_USER_KEYS}

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_system_info(self) -> Dict[str, Any]:
        """Return Access controller model, version, uptime, and overview.

        Uses the API client ``get_doors`` as a connectivity probe when
        available; falls back to the proxy ``access/info`` endpoint.
        """
        if self._cm.has_api_client:
            try:
                # py-unifi-access does not expose a dedicated system-info
                # endpoint, but we can use get_doors() as a health probe
                # and report basic connectivity information.
                doors = await self._cm.api_client.get_doors()
                return {
                    "source": "api_client",
                    "host": self._cm.host,
                    "api_port": self._cm.api_port,
                    "connected": True,
                    "door_count": len(doors),
                }
            except Exception as exc:
                logger.warning(
                    "[system] API client system info failed, falling back to proxy: %s",
                    exc,
                )

        if self._cm.has_proxy:
            try:
                data = await self._cm.proxy_request("GET", "access/info")
                return self._cm.extract_data(data)
            except Exception as exc:
                logger.error("[system] Failed to get system info via proxy: %s", exc, exc_info=True)
                raise

        raise self._cm.unavailable_error("No auth path available for get_system_info")

    async def get_health(self) -> Dict[str, Any]:
        """Return system health summary.

        Checks both auth paths and reports their individual status.
        Uses the ``dashboard/stats`` endpoint for a meaningful health probe.
        """
        health: Dict[str, Any] = {
            "host": self._cm.host,
            "is_connected": self._cm.is_connected,
            "api_client_available": self._cm.has_api_client,
            "proxy_available": self._cm.has_proxy,
        }

        async def _probe_api() -> None:
            try:
                await self._cm.api_client.get_doors()
                health["api_client_healthy"] = True
            except Exception as exc:
                logger.warning("[system] API client health probe failed: %s", exc)
                health["api_client_healthy"] = False
                health["api_client_error"] = str(exc)

        async def _probe_proxy() -> None:
            try:
                await self._cm.proxy_request("GET", f"dashboard/stats?{_STATS_EXPAND}")
                health["proxy_healthy"] = True
            except Exception as exc:
                logger.warning("[system] Proxy health probe failed: %s", exc)
                health["proxy_healthy"] = False
                health["proxy_error"] = str(exc)

        # Run available probes concurrently
        probes = []
        if self._cm.has_api_client:
            probes.append(_probe_api())
        if self._cm.has_proxy:
            probes.append(_probe_proxy())
        if probes:
            await asyncio.gather(*probes)

        return health

    async def list_users(self, page_num: int = 1, page_size: int = 25, compact: bool = False) -> list[Dict[str, Any]]:
        """List users with access.

        Users are served by the UniFi OS Users application at
        ``/proxy/users/api/v2/users/search`` (GET request), not the
        Access proxy.

        Parameters
        ----------
        page_num:
            Page number for pagination (default 1).
        page_size:
            Number of users per page (default 25).
        compact:
            When True, strip high-volume/low-value fields from user
            responses (~85% smaller).
        """
        if self._cm.has_proxy:
            try:
                path = (
                    f"users/search?including_resource=true"
                    f"&page_num={page_num}&page_size={page_size}"
                    f"&expand=with_last_activity,with_assignments"
                )
                data = await self._cm.proxy_request_users("GET", path)
                result = self._cm.extract_data(data)
                if isinstance(result, list):
                    users = result
                else:
                    users = [result] if result else []
                if compact:
                    users = [self._compact_user(u) for u in users]
                return users
            except Exception as exc:
                logger.error("[system] Failed to list users via users proxy: %s", exc, exc_info=True)
                raise

        raise self._cm.unavailable_error("No auth path available for list_users (proxy session required)")
