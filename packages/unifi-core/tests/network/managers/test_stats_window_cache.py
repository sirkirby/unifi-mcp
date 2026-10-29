"""Report windows the caller pins explicitly must never share a cache entry."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.stats_manager import StatsManager, _window_cache_key

# Two explicit windows inside the same wall-clock minutes.
FIRST = (1_760_000_000_000, 1_760_000_600_000)
SECOND = (FIRST[0] + 20_000, FIRST[1] + 20_000)


def _manager(response: Any) -> tuple[StatsManager, MagicMock]:
    cache: Dict[str, Any] = {}
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.side_effect = lambda key, timeout=None: cache.get(key)
    connection._update_cache.side_effect = lambda key, value, timeout=None: cache.__setitem__(key, value)
    connection.request = AsyncMock(return_value=response)
    return StatsManager(connection, MagicMock()), connection


def test_explicit_bounds_are_keyed_exactly() -> None:
    assert _window_cache_key(*FIRST, *FIRST) != _window_cache_key(*SECOND, *SECOND)


def test_moving_bounds_are_bucketed_to_the_minute() -> None:
    assert _window_cache_key(*FIRST, None, None) == _window_cache_key(FIRST[0] + 1, FIRST[1] + 1, None, None)


@pytest.mark.asyncio
async def test_top_clients_distinct_explicit_windows_do_not_share_cache() -> None:
    rows = [{"user": "aa:bb:cc:dd:ee:ff", "rx_bytes": 5, "tx_bytes": 7, "time": FIRST[0]}]
    manager, connection = _manager(rows)

    first = await manager.get_top_clients(start_ms=FIRST[0], end_ms=FIRST[1], granularity="5minutes")
    second = await manager.get_top_clients(start_ms=SECOND[0], end_ms=SECOND[1], granularity="5minutes")
    again = await manager.get_top_clients(start_ms=FIRST[0], end_ms=FIRST[1], granularity="5minutes")

    assert len([c for c in connection.request.call_args_list if c[0][0].path.startswith("/stat/")]) == 2
    assert (first[0]["start"], first[0]["end"]) == FIRST
    assert (second[0]["start"], second[0]["end"]) == SECOND
    assert (again[0]["start"], again[0]["end"]) == FIRST


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_site_dpi_traffic", "get_client_dpi_traffic"])
async def test_dpi_distinct_explicit_windows_do_not_share_cache(method: str) -> None:
    manager, connection = _manager({"total_usage_by_app": [], "client_usage_by_app": []})
    args = ("aa:bb:cc:dd:ee:ff",) if method == "get_client_dpi_traffic" else ()

    await getattr(manager, method)(*args, start_ms=FIRST[0], end_ms=FIRST[1])
    await getattr(manager, method)(*args, start_ms=SECOND[0], end_ms=SECOND[1])
    await getattr(manager, method)(*args, start_ms=FIRST[0], end_ms=FIRST[1])

    assert connection.request.await_count == 2
