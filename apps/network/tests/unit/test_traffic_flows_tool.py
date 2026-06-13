"""Tests for the unifi_get_traffic_flows tool."""

from unittest.mock import AsyncMock, patch

import pytest

from unifi_network_mcp.runtime import traffic_flow_manager
from unifi_network_mcp.tools.traffic_flows import (
    get_traffic_flow_statistics,
    get_traffic_flows,
)

# Patch the manager METHOD on the class so interception is robust regardless of
# which TrafficFlowManager instance the tool resolves (real singleton vs mock)
# or import/lazy-load ordering across the full suite.
_MANAGER_METHOD = "unifi_core.network.managers.traffic_flow_manager.TrafficFlowManager.get_traffic_flows"

# Distinct envelope so every pagination key is independently asserted (a tool
# that dropped any of them would not silently pass).
_ENVELOPE = {
    "flows": [{"id": "f1"}],
    "page_number": 3,
    "total_element_count": 42,
    "total_page_count": 5,
    "has_next": True,
    "or_more": True,
}


@pytest.mark.asyncio
async def test_tool_maps_params_and_returns_success():
    with patch(_MANAGER_METHOD, new_callable=AsyncMock) as mock_get:
        mock_get.return_value = dict(_ENVELOPE)
        out = await get_traffic_flows(
            within_hours=2,
            destination_domain="x.test",
            source_name="host1",
            risk="high",
            source_mac="aa:bb:cc:dd:ee:ff",
        )

    assert out["success"] is True
    assert out["site"] == traffic_flow_manager._connection.site
    # Whole manager envelope must spread through unchanged (all 6 keys).
    for key, value in _ENVELOPE.items():
        assert out[key] == value

    # AsyncMock on the class is not a descriptor, so self is not passed: args[0] is the query.
    query = mock_get.call_args.args[0]
    # Scalar filters are wrapped into single-element lists via _as_list.
    assert query.destination_domain == ["x.test"]
    assert query.risk == ["high"]
    assert query.source_mac == ["aa:bb:cc:dd:ee:ff"]
    # The one non-obvious rename: tool param source_name -> model field source_host.
    assert query.source_host == ["host1"]
    # Omitted filters stay None (not [] or [None]).
    assert query.action is None
    assert query.destination_ip is None
    # within_hours=2 -> window is ~2h wide (allow small clock-skew).
    assert query.time_from is not None and query.time_to is not None
    assert abs((query.time_to - query.time_from) - 2 * 3600 * 1000) < 2000


@pytest.mark.asyncio
async def test_tool_rejects_half_specified_window():
    # XOR guard must reject either half alone, symmetrically.
    out_from = await get_traffic_flows(time_from=1000)  # time_to missing
    assert out_from["success"] is False
    assert "both time_from and time_to" in out_from["error"]

    out_to = await get_traffic_flows(time_to=1000)  # time_from missing
    assert out_to["success"] is False
    assert "both time_from and time_to" in out_to["error"]


@pytest.mark.asyncio
async def test_tool_rejects_nonpositive_within_hours():
    out = await get_traffic_flows(within_hours=0)
    assert out["success"] is False
    assert "within_hours" in out["error"]


@pytest.mark.asyncio
async def test_tool_clamps_page_size():
    with patch(_MANAGER_METHOD, new_callable=AsyncMock) as mock_get:
        mock_get.return_value = dict(_ENVELOPE)
        await get_traffic_flows(time_from=1, time_to=2, page_size=5000)
        assert mock_get.call_args.args[0].page_size == 1000
        await get_traffic_flows(time_from=1, time_to=2, page_size=0)
        assert mock_get.call_args.args[0].page_size == 1


@pytest.mark.asyncio
async def test_tool_negative_page_returns_error_envelope():
    # page=-1 violates the model's page_number ge=0; the tool must surface this
    # as the uniform error envelope, not let a ValidationError escape.
    with patch(_MANAGER_METHOD, new_callable=AsyncMock) as mock_get:
        out = await get_traffic_flows(time_from=1, time_to=2, page=-1)
    assert out["success"] is False
    assert "error" in out
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_tool_manager_failure_returns_error_envelope():
    with patch(_MANAGER_METHOD, new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = RuntimeError("boom")
        out = await get_traffic_flows(time_from=1, time_to=2)
    assert out["success"] is False
    assert "Failed to get traffic flows" in out["error"]


# ---------------------------------------------------------------------------
# unifi_get_traffic_flow_statistics
# ---------------------------------------------------------------------------

_STATS_METHOD = "unifi_core.network.managers.traffic_flow_manager.TrafficFlowManager.get_traffic_flow_statistics"

_STATS_ENVELOPE = {
    "allowed_count_by_risk": {"low": 9},
    "blocked_count_by_risk": {"low": 1},
    "top_clients": [{"count": 5, "client_mac": "aa:bb:cc:00:00:01", "client_name": "Lab"}],
    "top_applications": [{"application_id": 470, "category_id": 4, "bytes": 9, "application_name": None}],
}


@pytest.mark.asyncio
async def test_stats_tool_maps_params_and_returns_success():
    with patch(_STATS_METHOD, new_callable=AsyncMock) as mock_get:
        mock_get.return_value = dict(_STATS_ENVELOPE)
        out = await get_traffic_flow_statistics(period="WEEK", top=5)

    assert out["success"] is True
    assert out["site"] == traffic_flow_manager._connection.site
    for key, value in _STATS_ENVELOPE.items():
        assert out[key] == value
    # period/top forwarded as kwargs.
    assert mock_get.call_args.kwargs == {"period": "WEEK", "top": 5}


@pytest.mark.asyncio
async def test_stats_tool_invalid_period_returns_error_envelope():
    # The real manager validates period before any controller call, so no patch.
    out = await get_traffic_flow_statistics(period="YEAR")
    assert out["success"] is False
    assert "period must be one of" in out["error"]


@pytest.mark.asyncio
async def test_stats_tool_manager_failure_returns_error_envelope():
    with patch(_STATS_METHOD, new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = RuntimeError("boom")
        out = await get_traffic_flow_statistics(period="DAY")
    assert out["success"] is False
    assert "Failed to get traffic flow statistics" in out["error"]
