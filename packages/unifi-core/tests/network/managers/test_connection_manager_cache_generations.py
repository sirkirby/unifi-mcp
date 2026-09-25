"""Cache-generation behavior for stale-read protection."""

import asyncio

import pytest
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager


def test_prefix_invalidation_does_not_track_an_unseen_cache_key() -> None:
    """Unrelated invalidations must not retain arbitrary key strings forever."""
    manager = ConnectionManager("controller.invalid", "user", "password")
    key = "settings_arbitrary_runtime_section_default"

    manager._invalidate_cache(key)

    assert key not in manager._cache_generations


def test_global_invalidation_does_not_track_an_unguarded_dynamic_cache_key() -> None:
    """Global lifecycle cleanup must not retain ordinary dynamic cache keys."""
    manager = ConnectionManager("controller.invalid", "user", "password")
    key = "settings_arbitrary_runtime_section_default"
    manager._update_cache(key, {"value": True})

    manager._invalidate_cache()

    assert key not in manager._cache_generations


@pytest.mark.asyncio
async def test_in_flight_route_read_cannot_restore_cache_after_mutation() -> None:
    connection = ConnectionManager("controller.invalid", "user", "password")
    started = asyncio.Event()
    finish = asyncio.Event()

    async def delayed_read(_request):
        started.set()
        await finish.wait()
        return {"data": [{"_id": "old-route"}]}

    connection.request = delayed_read
    read_task = asyncio.create_task(TrafficRouteManager(connection).get_traffic_routes())
    await started.wait()
    connection._invalidate_cache("traffic_routes_default")
    finish.set()

    assert await read_task == [{"_id": "old-route"}]
    assert connection.get_cached("traffic_routes_default") is None
