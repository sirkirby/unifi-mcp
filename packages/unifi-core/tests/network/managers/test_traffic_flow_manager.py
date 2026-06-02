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
