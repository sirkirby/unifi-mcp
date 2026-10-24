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
@pytest.mark.parametrize(
    "kwargs,summary_mode,dashboard,omitted",
    [
        (
            {},
            True,
            [{"system_status": {"status": "ok"}, "gateway": {"count": 1}}],
            ["radio_activity", "wan_activity", "wan_history", "wifi_activity"],
        ),
        ({"summary": False, "history_seconds": 3600}, False, DASHBOARD_RAW, None),
    ],
)
async def test_dashboard_summary_and_full_modes(kwargs, summary_mode, dashboard, omitted):
    with patch("unifi_network_mcp.tools.stats.stats_manager") as manager:
        manager.get_dashboard = AsyncMock(return_value=DASHBOARD_RAW)
        manager._connection.site = "default"
        from unifi_network_mcp.tools.stats import get_dashboard

        result = await get_dashboard(**kwargs)

    assert result["summary_mode"] is summary_mode
    assert result["dashboard"] == dashboard
    if omitted:
        assert result["omitted_sections"] == omitted
    if "history_seconds" in kwargs:
        manager.get_dashboard.assert_awaited_once_with(history_seconds=kwargs["history_seconds"])
