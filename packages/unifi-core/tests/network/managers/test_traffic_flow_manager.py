"""Tests for TrafficFlowManager — caching, validation, and response shaping."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.traffic_flow_manager import TrafficFlowManager
from unifi_core.network.models.traffic_flows import TrafficFlowQuery

_EMPTY_RESPONSE = {
    "data": [],
    "total_element_count": 0,
    "total_page_count": 1,
    "has_next": False,
    "or_more": False,
    "page_number": 0,
}


def _make_connection(response=None):
    """Build a MagicMock connection with a real in-process cache store."""
    store: dict = {}
    conn = MagicMock()
    conn.site = "default"
    conn.request = AsyncMock(return_value=response if response is not None else _EMPTY_RESPONSE)
    conn.get_cached = lambda key, timeout=None: store.get(key)
    conn._update_cache = lambda key, data, timeout=None: store.update({key: data})
    return conn


# ---------------------------------------------------------------------------
# A. Caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identical_query_is_cached_within_ttl():
    """Second call with the same query must NOT issue a second controller request."""
    conn = _make_connection()
    mgr = TrafficFlowManager(conn)
    q = TrafficFlowQuery(time_from=1, time_to=2, page_number=0, page_size=100)

    await mgr.get_traffic_flows(q)
    await mgr.get_traffic_flows(q)

    assert conn.request.await_count == 1


# ---------------------------------------------------------------------------
# B. Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_time_window_raises():
    """get_traffic_flows must raise ValueError when time_from or time_to is absent."""
    conn = _make_connection()
    mgr = TrafficFlowManager(conn)

    with pytest.raises(ValueError, match="time_from and time_to are required"):
        await mgr.get_traffic_flows(TrafficFlowQuery(page_number=0, page_size=100))


# ---------------------------------------------------------------------------
# C. Response shaping — empty and malformed inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handles_empty_and_nondict_response():
    """Both {} and [{}] responses must yield flows==[] and total_element_count==0."""
    for raw in ({}, [{}]):
        conn = _make_connection(response=raw)
        mgr = TrafficFlowManager(conn)
        result = await mgr.get_traffic_flows(TrafficFlowQuery(time_from=1, time_to=2, page_number=0, page_size=100))
        assert result["flows"] == [], f"Expected empty flows for response {raw!r}"
        assert result["total_element_count"] == 0, f"Expected 0 for response {raw!r}"


# ---------------------------------------------------------------------------
# D. get_traffic_flow_statistics (latest-statistics)
# ---------------------------------------------------------------------------

_STATS_RESPONSE = {
    "allowed_count_by_risk": {"low": 103, "medium": 2},
    "blocked_count_by_risk": {"low": 7},
    "all_count_by_region": {"US": 100},
    "top_all_count_by_client": [{"count": 500, "client_mac": "aa:bb:cc:00:00:01", "client_name": "Lab-Laptop"}],
    "top_all_count_by_destination": [{"count": 200, "destination": "example.test", "mostFrequentRegion": "US"}],
    "top_all_traffic_by_application": [{"application_id": 470, "bytes": 999, "category_id": 4}],
    "top_blocked_count_by_policy": [
        {"count": 7, "policy_id": "p1", "policy_name": "Region Blocking", "policy_type": "PROTECTION"}
    ],
}


@pytest.mark.asyncio
async def test_statistics_rejects_invalid_period():
    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn)
    with pytest.raises(ValueError, match="period must be one of"):
        await mgr.get_traffic_flow_statistics(period="YEAR")
    # The controller must not have been called for an invalid period.
    assert conn.request.await_count == 0


@pytest.mark.asyncio
async def test_statistics_builds_period_and_top_query():
    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn)
    await mgr.get_traffic_flow_statistics(period="day", top=5)
    api_request = conn.request.await_args.args[0]
    assert api_request.method == "get"
    assert api_request.path == "/traffic-flow-latest-statistics?period=DAY&top=5"


@pytest.mark.asyncio
async def test_statistics_shapes_response():
    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn)
    result = await mgr.get_traffic_flow_statistics(period="DAY", top=30)
    assert result["allowed_count_by_risk"] == {"low": 103, "medium": 2}
    assert result["top_clients"][0]["client_name"] == "Lab-Laptop"
    assert result["top_destinations"][0]["most_frequent_region"] == "US"
    assert result["top_applications"][0]["application_id"] == 470
    assert result["top_applications"][0]["application_name"] is None
    assert result["top_blocked_policies"][0]["policy_name"] == "Region Blocking"


@pytest.mark.asyncio
async def test_statistics_is_cached_within_ttl():
    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn)
    await mgr.get_traffic_flow_statistics(period="DAY", top=10)
    await mgr.get_traffic_flow_statistics(period="DAY", top=10)
    assert conn.request.await_count == 1


@pytest.mark.asyncio
async def test_statistics_handles_list_wrapped_and_empty():
    for raw in ([_STATS_RESPONSE], [{}], {}):
        conn = _make_connection(response=raw)
        mgr = TrafficFlowManager(conn)
        result = await mgr.get_traffic_flow_statistics(period="HOUR", top=10)
        assert isinstance(result["top_clients"], list)
        assert isinstance(result["allowed_count_by_risk"], dict)
