"""Traffic-route reader compatibility with minimal connection doubles."""

from typing import Any

import pytest
from unifi_core.network.managers.firewall_manager import FirewallManager
from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager


class _LegacyTrafficRouteConnection:
    """Pre-generation reader contract used by lightweight downstream fakes."""

    site = "default"

    def __init__(self) -> None:
        self.cached: dict[str, Any] = {}

    def get_cached(self, key: str) -> Any | None:
        return self.cached.get(key)

    def _update_cache(self, key: str, data: Any, timeout: int | None = None) -> None:
        del timeout
        self.cached[key] = data

    async def ensure_connected(self) -> bool:
        return True

    async def request(self, _api_request: Any) -> dict[str, list[dict[str, str]]]:
        return {"data": [{"_id": "route-1"}]}


@pytest.mark.asyncio
async def test_canonical_reader_supports_the_legacy_connection_double() -> None:
    connection = _LegacyTrafficRouteConnection()

    routes = await TrafficRouteManager(connection).get_traffic_routes()  # type: ignore[arg-type]

    assert routes == [{"_id": "route-1"}]
    assert connection.cached["traffic_routes_default"] == routes


@pytest.mark.asyncio
async def test_legacy_reader_supports_the_legacy_connection_double() -> None:
    connection = _LegacyTrafficRouteConnection()

    routes = await FirewallManager(connection).get_traffic_routes()  # type: ignore[arg-type]

    assert [route.raw for route in routes] == [{"_id": "route-1"}]
    assert connection.cached["traffic_routes_default"] == routes
