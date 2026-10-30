"""Stats summaries total the rows they summarize on a legacy controller (#945)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiounifi.errors import ResponseError

from unifi_core.network.managers.stats_manager import StatsManager

NO_ENGINE = ResponseError("Call https://h/proxy/network/v2/api/stats/source received 404 Not Found")


def _legacy_stats_manager(report_rows):
    """A real StatsManager on a controller without the Network 11 engine."""
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None

    async def request(api_request):
        if api_request.path == "/source":
            raise NO_ENGINE
        return [dict(row) for row in report_rows]

    connection.request = AsyncMock(side_effect=request)
    return StatsManager(connection, MagicMock()), connection


@pytest.mark.asyncio
async def test_network_stats_summary_totals_the_wan_traffic_of_its_rows():
    manager, _ = _legacy_stats_manager(
        [
            {"time": 1, "num_sta": 106, "wan-rx_bytes": 5193311626.5, "wan-tx_bytes": 81186081.0, "o": "site"},
            {"time": 2, "num_sta": 102, "wan-rx_bytes": 1000.0, "wan-tx_bytes": 10.0, "o": "site"},
        ]
    )
    with patch("unifi_network_mcp.tools.stats.stats_manager", manager):
        from unifi_network_mcp.tools.stats import get_network_stats

        result = await get_network_stats(duration="daily", granularity="hourly")

    assert result["success"] is True
    assert result["summary"]["total_rx_bytes"] == 5193312626
    assert result["summary"]["total_tx_bytes"] == 81186091
    assert result["summary"]["total_bytes"] == 5193312626 + 81186091
    assert result["summary"]["avg_clients"] == 104


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("controller_type", "report", "row", "totals"),
    [
        (
            "udm",
            "/stat/report/hourly.gw",
            {"time": 1, "wan-rx_bytes": 100.0, "wan-tx_bytes": 20.0, "lan-rx_bytes": 9e9, "o": "gw"},
            (100.0, 20.0, 120.0),
        ),
        (
            "uxg",
            "/stat/report/hourly.gw",
            {"time": 1, "wan-rx_bytes": 7.0, "wan-tx_bytes": 3.0, "o": "gw"},
            (7.0, 3.0, 10.0),
        ),
        (
            "uap",
            "/stat/report/hourly.ap",
            {
                "time": 1,
                "num_sta": 18,
                "ng-rx_bytes": 12.0,
                "na-rx_bytes": 13.0,
                "ng-tx_bytes": 9.0,
                "na-tx_bytes": 32.0,
            },
            (25.0, 41.0, 66.0),
        ),
    ],
)
async def test_device_stats_summary_totals_its_rows(controller_type, report, row, totals):
    manager, connection = _legacy_stats_manager([row])
    device = SimpleNamespace(raw={"mac": "aa:bb:cc:00:00:01", "name": "dev", "type": controller_type})
    with (
        patch("unifi_network_mcp.tools.stats.stats_manager", manager),
        patch("unifi_network_mcp.tools.stats.device_manager") as device_manager,
    ):
        device_manager.get_device_details = AsyncMock(return_value=device)
        from unifi_network_mcp.tools.stats import get_device_stats

        result = await get_device_stats(device_id="aa:bb:cc:00:00:01")

    assert result["success"] is True
    assert report in [call[0][0].path for call in connection.request.call_args_list]
    summary = result["summary"]
    assert (summary["total_rx_bytes"], summary["total_tx_bytes"], summary["total_bytes"]) == totals
