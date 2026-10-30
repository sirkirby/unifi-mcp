"""Legacy report rows carry their bucket time and the traffic totals the summaries read."""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import ResponseError
from unifi_core.network.managers.stats_manager import StatsManager

GW_MAC = "aa:bb:cc:00:00:09"
AP_MAC = "aa:bb:cc:00:00:01"
CLIENT_MAC = "aa:bb:cc:00:00:42"
NO_ENGINE = ResponseError("Call https://h/proxy/network/v2/api/stats/source received 404 Not Found")


def _manager(report: List[Dict[str, Any]]) -> tuple[StatsManager, MagicMock]:
    """A legacy controller (no statistics engine) whose report answers with ``report``."""
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None

    async def request(api_request):
        if api_request.path == "/source":
            raise NO_ENGINE
        if api_request.path.startswith("/stat/report/"):
            return [dict(row) for row in report]
        raise AssertionError(f"unexpected request {api_request.path}")

    connection.request = AsyncMock(side_effect=request)
    return StatsManager(connection, MagicMock()), connection


def _report_attrs(connection: MagicMock) -> List[str]:
    (report_call,) = [c for c in connection.request.call_args_list if c[0][0].path.startswith("/stat/report/")]
    return report_call[0][0].data["attrs"]


@pytest.mark.asyncio
async def test_site_rows_take_their_totals_from_wan_traffic_and_come_in_time_order() -> None:
    manager, connection = _manager(
        [
            {"time": 2, "num_sta": 4, "wan-rx_bytes": 30.5, "wan-tx_bytes": 2.0},
            {"time": 1, "num_sta": 3, "wan-rx_bytes": 10.0, "wan-tx_bytes": 1.0},
        ]
    )

    rows = await manager.get_network_stats(duration_hours=2)

    assert "time" in _report_attrs(connection)
    assert [row["time"] for row in rows] == [1, 2]
    assert [(row["rx_bytes"], row["tx_bytes"], row["bytes"]) for row in rows] == [(10.0, 1.0, 11.0), (30.5, 2.0, 32.5)]


@pytest.mark.asyncio
async def test_a_total_the_controller_sends_is_kept() -> None:
    manager, _ = _manager([{"time": 1, "rx_bytes": 7, "tx_bytes": 3, "bytes": 10, "wan-rx_bytes": 99}])

    (row,) = await manager.get_network_stats(duration_hours=1)

    assert (row["rx_bytes"], row["tx_bytes"], row["bytes"]) == (7, 3, 10)


@pytest.mark.asyncio
async def test_rows_without_traffic_get_no_invented_totals() -> None:
    manager, _ = _manager([{"time": 1, "num_sta": 3}])

    (row,) = await manager.get_network_stats(duration_hours=1)

    assert row == {"time": 1, "num_sta": 3}


@pytest.mark.asyncio
async def test_gateway_device_rows_total_their_wan_traffic() -> None:
    manager, connection = _manager(
        [{"time": 1, "wan-rx_bytes": 100.0, "wan-tx_bytes": 20.0, "lan-rx_bytes": 5000.0, "lan-tx_bytes": 4000.0}]
    )

    (row,) = await manager.get_device_stats(GW_MAC, duration_hours=1, device_type="gw")

    assert "time" in _report_attrs(connection)
    assert (row["rx_bytes"], row["tx_bytes"], row["bytes"]) == (100.0, 20.0, 120.0)


@pytest.mark.asyncio
async def test_ap_rows_total_their_radio_bands() -> None:
    manager, connection = _manager(
        [{"time": 1, "num_sta": 18, "ng-rx_bytes": 12.0, "na-rx_bytes": 13.0, "ng-tx_bytes": 9.0, "na-tx_bytes": 32.0}]
    )

    (row,) = await manager.get_device_stats(AP_MAC, duration_hours=1, device_type="ap")

    assert "time" in _report_attrs(connection)
    assert (row["rx_bytes"], row["tx_bytes"], row["bytes"]) == (25.0, 41.0, 66.0)


@pytest.mark.asyncio
async def test_ap_rows_include_the_6ghz_band() -> None:
    manager, connection = _manager(
        [
            {
                "time": 1,
                "ng-rx_bytes": 1.0,
                "na-rx_bytes": 2.0,
                "6e-rx_bytes": 4.0,
                "6e-tx_bytes": 20.0,
                "ng-tx_bytes": 10,
            }
        ]
    )

    (row,) = await manager.get_device_stats(AP_MAC, duration_hours=1, device_type="ap")

    assert {"6e-rx_bytes", "6e-tx_bytes"} <= set(_report_attrs(connection))
    assert (row["rx_bytes"], row["tx_bytes"], row["bytes"]) == (7.0, 30.0, 37.0)


@pytest.mark.asyncio
async def test_client_and_gateway_reports_ask_for_the_bucket_time() -> None:
    manager, connection = _manager([{"time": 2, "rx_bytes": 1}, {"time": 1, "rx_bytes": 2}])
    rows = await manager.get_client_stats(CLIENT_MAC, duration_hours=1)
    assert "time" in _report_attrs(connection)
    assert [row["time"] for row in rows] == [1, 2]

    manager, connection = _manager([{"time": 2, "wan-rx_bytes": 1}, {"time": 1, "wan-rx_bytes": 2}])
    rows = await manager.get_gateway_stats(duration_hours=1)
    assert "time" in _report_attrs(connection)
    assert [row["time"] for row in rows] == [1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("device_type", ["ap", "gw", "dev"])
async def test_every_device_report_asks_for_the_bucket_time(device_type: str) -> None:
    manager, connection = _manager([])
    connection.request.side_effect = None
    connection.request.return_value = [{"time": 1}]

    await manager.get_device_stats(AP_MAC, duration_hours=1, device_type=device_type)

    report_attrs = [
        c[0][0].data["attrs"] for c in connection.request.call_args_list if c[0][0].path.startswith("/stat/report/")
    ]
    assert report_attrs and all("time" in attrs for attrs in report_attrs)
