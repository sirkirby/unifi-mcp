"""Tests for bounded Network dashboard responses."""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

DASHBOARD_RAW = [
    {
        "system_status": {"status": "ok"},
        "gateway": {"count": 1},
        "radio_activity": {"series": [1, 2, 3]},
        "wan_activity": {"series": [1, 2, 3]},
        "wan_history": {"series": [1, 2, 3]},
        "wifi_activity": {"series": [1, 2, 3]},
    }
]


@pytest.mark.asyncio
async def test_dashboard_defaults_to_summary():
    with patch("unifi_network_mcp.tools.stats.stats_manager") as manager:
        manager.get_dashboard = AsyncMock(return_value=DASHBOARD_RAW)
        manager._connection.site = "default"
        from unifi_network_mcp.tools.stats import get_dashboard

        result = await get_dashboard()

    assert result["summary_mode"] is True
    assert result["dashboard"] == [{"system_status": {"status": "ok"}, "gateway": {"count": 1}}]
    assert result["omitted_sections"] == [
        "radio_activity",
        "wan_activity",
        "wan_history",
        "wifi_activity",
    ]


@pytest.mark.asyncio
async def test_dashboard_full_mode_preserves_raw_shape():
    with patch("unifi_network_mcp.tools.stats.stats_manager") as manager:
        manager.get_dashboard = AsyncMock(return_value=DASHBOARD_RAW)
        manager._connection.site = "default"
        from unifi_network_mcp.tools.stats import get_dashboard

        result = await get_dashboard(summary=False, history_seconds=3600)

    assert result["summary_mode"] is False
    assert result["dashboard"] == DASHBOARD_RAW
    manager.get_dashboard.assert_awaited_once_with(history_seconds=3600)
