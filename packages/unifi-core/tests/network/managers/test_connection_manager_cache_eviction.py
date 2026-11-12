"""Expired cache entries are evicted, so query-keyed caches stay bounded."""

import time

import pytest
from unifi_core.network.managers import connection_manager as connection_module
from unifi_core.network.managers.connection_manager import ConnectionManager


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def time(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(connection_module, "_cache_clock", fake.time)
    return fake


def _manager() -> ConnectionManager:
    return ConnectionManager("controller.invalid", "user", "password", cache_timeout=30)


def test_distinct_query_keys_do_not_accumulate_past_their_ttl(clock: _Clock) -> None:
    manager = _manager()

    for window in range(200):
        manager._update_cache(f"traffic_flows_window_{window}_default", {"flows": [window]}, timeout=45)
        clock.now += 60

    assert set(manager._cache) == {"traffic_flows_window_199_default"}
    assert set(manager._last_cache_update) == {"traffic_flows_window_199_default"}
    assert set(manager._cache_retention) == {"traffic_flows_window_199_default"}


def test_entries_inside_their_ttl_survive_a_sweep(clock: _Clock) -> None:
    manager = _manager()
    manager._update_cache("dns_records_default", ["record"], timeout=300)
    manager._update_cache("health_default", {"ok": True}, timeout=10)

    clock.now += 31
    manager._update_cache("trigger_sweep_default", True)

    assert manager.get_cached("dns_records_default", timeout=300) == ["record"]
    assert "health_default" not in manager._cache
    assert manager.get_cached("trigger_sweep_default") is True


def test_entry_is_kept_at_least_for_the_default_timeout(clock: _Clock) -> None:
    manager = _manager()
    clock.now += 25
    manager._update_cache("short_default", "value", timeout=5)

    clock.now += 10
    manager._update_cache("other_default", "value")

    assert "short_default" in manager._cache
    clock.now += 31
    manager._update_cache("last_default", "value")
    assert "short_default" not in manager._cache


def test_a_reader_with_a_longer_ttl_extends_retention(clock: _Clock) -> None:
    manager = _manager()
    manager._update_cache("catalog_default", {"apps": 1})

    clock.now += 10
    assert manager.get_cached("catalog_default", timeout=900) == {"apps": 1}

    clock.now += 100
    manager._update_cache("trigger_sweep_default", True)

    assert manager.get_cached("catalog_default", timeout=900) == {"apps": 1}


def test_sweep_runs_at_most_once_per_cache_timeout(clock: _Clock) -> None:
    manager = _manager()
    clock.now += 5
    manager._update_cache("written_before_sweep_default", "value")
    clock.now += 25
    manager._update_cache("sweeps_now_default", "value")
    assert "written_before_sweep_default" in manager._cache

    clock.now += 10
    manager._update_cache("too_soon_to_sweep_default", "value")
    assert manager.get_cached("written_before_sweep_default") is None
    assert "written_before_sweep_default" in manager._cache

    clock.now += 20
    manager._update_cache("sweeps_again_default", "value")
    assert "written_before_sweep_default" not in manager._cache


def test_invalidation_drops_retention_with_the_entry(clock: _Clock) -> None:
    manager = _manager()
    manager._update_cache("dns_records_default", ["record"], timeout=300)

    manager._invalidate_cache("dns_records")

    assert "dns_records_default" not in manager._cache
    assert "dns_records_default" not in manager._cache_retention


def test_a_rewrite_keeps_the_longer_ttl_a_reader_already_used(clock: _Clock) -> None:
    manager = _manager()
    manager._update_cache("catalog_default", {"apps": 1})
    assert manager.get_cached("catalog_default", timeout=900) == {"apps": 1}

    manager._update_cache("catalog_default", {"apps": 2})
    clock.now += 100
    manager._update_cache("trigger_sweep_default", True)

    assert manager.get_cached("catalog_default", timeout=900) == {"apps": 2}


def test_cache_ages_use_a_monotonic_clock() -> None:
    """A wall-clock step (NTP, a restored VM) must not stall eviction or refresh entries."""
    assert connection_module._cache_clock is time.monotonic
