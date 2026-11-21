"""Read-only manager for Network 11 Matter / Thread inventory (V2 API).

Reads the two endpoints behind Settings > Matter in the Network UI
(``/thread-networks`` and ``/matter/nodes``, verified on Network 11.0.99).
Results are the raw controller lists; public shaping lives in
``unifi_core.network.models.matter`` and never copies a node's setup code.

Both endpoints are session-only V2 reads: an API-key route is refused before
any request, and failures carry fixed text plus the exception class only, so
controller response text (device names, addresses) never reaches a caller.
"""

import logging
from typing import Any, Dict, List

from aiounifi.models.api import ApiRequestV2

from unifi_core.exceptions import UniFiAuthError, UniFiOperationError
from unifi_core.network.managers.connection_manager import ConnectionManager

logger = logging.getLogger("unifi-network-mcp")

CACHE_PREFIX_MATTER = "matter"

THREAD_NETWORKS_PATH = "/thread-networks"
MATTER_NODES_PATH = "/matter/nodes"


def matter_session_required_message(env_prefix: str | None) -> str:
    """Fixed guidance for a missing Network session.

    The ``UNIFI_*`` variables are named only for a caller that reads them (an
    MCP server passes its prefix); the API server keeps credentials on the
    controller record instead.
    """
    if isinstance(env_prefix, str) and env_prefix:
        where = f"Configure UNIFI_{env_prefix}_USERNAME and UNIFI_{env_prefix}_PASSWORD."
    else:
        where = "Add a username and password to this controller's configuration."
    return f"Matter/Thread inventory requires Network session authentication. {where}"


class MatterManager:
    """Reads Thread networks and Matter nodes for the current site."""

    def __init__(self, connection_manager: ConnectionManager):
        self._connection = connection_manager

    async def list_thread_networks(self) -> List[Dict[str, Any]]:
        """Thread networks the console has detected, with border routers and fabrics."""
        return await self._read_list(THREAD_NETWORKS_PATH, "thread_networks", "Thread networks")

    async def list_matter_nodes(self) -> List[Dict[str, Any]]:
        """Matter nodes commissioned through the console."""
        return await self._read_list(MATTER_NODES_PATH, "nodes", "Matter nodes")

    async def _read_list(self, path: str, cache_name: str, label: str) -> List[Dict[str, Any]]:
        if not await self._connection.ensure_session_connected():
            raise UniFiAuthError(matter_session_required_message(getattr(self._connection, "tls_env_prefix", None)))
        cache_key = f"{CACHE_PREFIX_MATTER}_{cache_name}_{self._connection.site}"
        cached = self._connection.get_cached(cache_key)
        if cached is not None:
            return cached
        # Capture the cache generation before the request, so a set_site() or
        # cleanup() that invalidates this key while the read is in flight
        # cannot be undone by publishing pre-invalidation records.
        get_cache_generation = getattr(self._connection, "_get_cache_generation", None)
        update_cache_if_current = getattr(self._connection, "_update_cache_if_current", None)
        cache_generation = get_cache_generation(cache_key) if callable(get_cache_generation) else None
        try:
            response = await self._connection.request(ApiRequestV2(method="get", path=path))
        except Exception as e:
            logger.error("Error listing %s: %s", label, type(e).__name__)
            raise UniFiOperationError(
                f"Failed to list {label} ({type(e).__name__}). "
                "Verify controller availability and Network session permissions."
            ) from None
        if not isinstance(response, list):
            logger.warning("%s returned an unexpected response shape", label)
            raise UniFiOperationError(
                f"Failed to list {label}: the controller returned an unexpected response shape. "
                "Verify that this Network version supports Matter/Thread inventory (Network 11+)."
            )
        records = [record for record in response if isinstance(record, dict)]
        if cache_generation is not None and callable(update_cache_if_current):
            update_cache_if_current(cache_key, records, cache_generation)
        else:
            self._connection._update_cache(cache_key, records)
        return records
