"""Stats on the Network 11 statistics engine: series read as legacy report rows."""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiounifi.errors import Forbidden, RequestError, ResponseError
from unifi_core.network import stats_series
from unifi_core.network.managers.stats_manager import StatsManager

HOUR = 3_600_000
END = 1_790_002_800_000  # on an hour boundary
SITE = "11111111-2222-3333-4444-555555555555"
OTHER_SITE = "66666666-7777-8888-9999-000000000000"
AP_MAC = "aa:bb:cc:00:00:01"
GW_MAC = "aa:bb:cc:00:00:09"
SATISFACTION = "avgClientSatisfactionScore"


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch):
    monkeypatch.setattr("unifi_core.network.managers.stats_manager._now_ms", lambda: END)


def _points(start: int, count: int, step: int = 300_000, **values: Any) -> List[Dict[str, Any]]:
    return [{"timestamp": start + i * step, "duration": step, **values} for i in range(count)]


def _manager(responses: Dict[str, Any]) -> tuple[StatsManager, MagicMock]:
    """A manager whose controller answers by path prefix; an exception value is raised."""
    responses = {"/self": [{"site_id": SITE}], **responses}
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None

    async def request(api_request, return_raw=False):
        for prefix, answer in responses.items():
            if api_request.path.startswith(prefix):
                if isinstance(answer, BaseException):
                    raise answer
                return answer(api_request.path) if callable(answer) else answer
        raise AssertionError(f"unexpected request {api_request.path}")

    connection.request = AsyncMock(side_effect=request)
    return StatsManager(connection, MagicMock()), connection


def _paths(connection: MagicMock) -> List[str]:
    return [call[0][0].path for call in connection.request.call_args_list]


def _series_paths(connection: MagicMock) -> List[str]:
    return [path for path in _paths(connection) if path.startswith("/recent/series")]


# --- pure helpers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("span", "period"),
    [(HOUR, "HOUR"), (24 * HOUR, "DAY"), (25 * HOUR, "WEEK"), (7 * 24 * HOUR, "WEEK"), (90 * 24 * HOUR, "MONTH")],
)
def test_period_is_the_shortest_that_covers_the_window(span: int, period: str) -> None:
    assert stats_series.period_for_window(END - span, END) == period


def test_stats_request_is_not_site_scoped() -> None:
    request = stats_series.StatsApiRequest(method="get", path="/source")
    assert request.full_path("default", True) == "/proxy/network/v2/api/stats/source"
    assert request.full_path("default", False) == "/v2/api/stats/source"


def test_points_fold_into_requested_buckets_by_metric_kind() -> None:
    """Bytes sum, distinct counts take the max, averages average; points outside the window drop."""
    rows = [
        {
            "siteId": SITE,
            "series": [
                {"timestamp": END - HOUR - 300_000, "rxBytes": 999, "distinctClientCount": 99},
                {"timestamp": END - HOUR, "rxBytes": 10, "distinctClientCount": 3, SATISFACTION: 90},
                {"timestamp": END - HOUR + 300_000, "rxBytes": 5, "distinctClientCount": 5, SATISFACTION: 80},
                {"timestamp": END, "rxBytes": 999},
            ],
        }
    ]
    fields = {"rxBytes": "rx_bytes", "distinctClientCount": "num_sta", "avgClientSatisfactionScore": "satisfaction"}

    folded = stats_series.legacy_rows(rows, fields, start_ms=END - HOUR, end_ms=END, granularity="hourly")

    assert folded == {END - HOUR: {"rx_bytes": 15, "num_sta": 5, "satisfaction": 85}}


def test_nested_band_metrics_use_the_legacy_band_prefix() -> None:
    rows = [{"series": [{"timestamp": END - HOUR, "byRadioBand": [{"radioBand": "ng", "distinctClientCount": 7}]}]}]

    folded = stats_series.legacy_rows(
        rows,
        {"distinctClientCount": "num_sta"},
        start_ms=END - HOUR,
        end_ms=END,
        granularity="5minutes",
        nested=("byRadioBand", "radioBand"),
    )

    assert folded == {END - HOUR: {"ng-num_sta": 7}}


def test_monthly_buckets_start_on_the_calendar_month() -> None:
    rows = [{"series": [{"timestamp": END - HOUR, "rxBytes": 1}, {"timestamp": END - 2 * HOUR, "rxBytes": 2}]}]

    folded = stats_series.legacy_rows(
        rows, {"rxBytes": "rx_bytes"}, start_ms=END - 3 * HOUR, end_ms=END, granularity="monthly"
    )

    (bucket,) = folded
    assert bucket <= END - 2 * HOUR and folded[bucket] == {"rx_bytes": 3}


# --- engine probe ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_controller_without_the_endpoint_keeps_the_report() -> None:
    manager, connection = _manager(
        {
            "/source": ResponseError("Call https://h/proxy/network/v2/api/stats/source received 404 Not Found"),
            "/stat/report/hourly.site": [{"time": 1, "rx_bytes": 5}],
        }
    )

    assert await manager.get_network_stats(duration_hours=1) == [{"time": 1, "rx_bytes": 5}]
    assert _paths(connection) == ["/source", "/stat/report/hourly.site"]


@pytest.mark.asyncio
async def test_failed_probe_with_an_empty_report_is_a_retryable_error_not_cached() -> None:
    """The history may be in the new engine, so an empty legacy report proves nothing."""
    manager, connection = _manager({"/source": RequestError("timeout"), "/stat/report/": []})

    with pytest.raises(RequestError, match="Retry"):
        await manager.get_network_stats(duration_hours=1)
    connection._update_cache.assert_not_called()


@pytest.mark.asyncio
async def test_failed_probe_still_reads_a_populated_report() -> None:
    manager, _ = _manager({"/source": RequestError("timeout"), "/stat/report/": [{"time": 1}]})

    assert await manager.get_network_stats(duration_hours=1) == [{"time": 1}]


@pytest.mark.asyncio
async def test_forbidden_engine_and_empty_report_is_an_error_not_an_empty_success() -> None:
    manager, _ = _manager({"/source": Forbidden("403"), "/stat/report/": []})

    with pytest.raises(RequestError, match="Full Admin"):
        await manager.get_gateway_stats(duration_hours=1)


# --- modern reads ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_stats_read_wan_and_client_series() -> None:
    def series(path: str):
        if "schema=wanBySite" in path:
            return [{"siteId": SITE, "series": _points(END - HOUR, 12, rxBytes=10, txBytes=1)}]
        return [{"siteId": SITE, "series": _points(END - HOUR, 12, distinctClientCount=4)}]

    manager, connection = _manager({"/source": ["MODERN"], "/recent/series": series})

    rows = await manager.get_network_stats(duration_hours=1, granularity="hourly")

    assert rows == [
        {
            "time": END - HOUR,
            "wan-rx_bytes": 120,
            "wan-tx_bytes": 12,
            "num_sta": 4,
            "rx_bytes": 120,
            "tx_bytes": 12,
            "bytes": 132,
        }
    ]
    assert not any(path.startswith("/stat/report") for path in _paths(connection))
    assert all("period=HOUR" in path and f"end={END}" in path for path in _series_paths(connection))


@pytest.mark.asyncio
async def test_site_series_on_a_multi_site_controller_keep_only_this_site() -> None:
    series = [
        {"siteId": SITE, "series": _points(END - HOUR, 1, rxBytes=10)},
        {"siteId": OTHER_SITE, "series": _points(END - HOUR, 1, rxBytes=1000)},
    ]
    manager, _ = _manager({"/source": ["MODERN"], "/recent/series": series})
    devices = AsyncMock(return_value=[{"mac": AP_MAC, "type": "uap"}])

    with patch("unifi_core.network.managers.stats_manager.DeviceManager") as device_manager:
        device_manager.return_value.get_devices = devices
        rows = await manager.get_gateway_stats(duration_hours=1)

    # No gateway in the device list, so the site WAN series is used.
    assert [row["wan-rx_bytes"] for row in rows] == [10]


@pytest.mark.asyncio
async def test_ap_stats_filter_by_device_and_carry_band_counts() -> None:
    def series(path: str):
        return [
            {
                "siteId": SITE,
                "deviceMac": AP_MAC,
                "series": _points(
                    END - HOUR,
                    1,
                    distinctClientCount=6,
                    avgClientSatisfactionScore=95,
                    byRadioBand=[{"radioBand": "na", "distinctClientCount": 4}],
                ),
            }
        ]

    manager, connection = _manager({"/source": ["MODERN"], "/recent/series": series})

    rows = await manager.get_device_stats(AP_MAC, duration_hours=1, granularity="5minutes", device_type="ap")

    assert rows == [{"time": END - HOUR, "ap": AP_MAC, "num_sta": 6, "satisfaction": 95, "na-num_sta": 4}]
    (path,) = _series_paths(connection)
    assert "schema=wirelessBySiteByDevice" in path and f"filter=deviceMac.eq('{AP_MAC}')" in path
    assert "nested(byRadioBand)" in path


@pytest.mark.asyncio
async def test_gateway_stats_read_the_gateway_device_series() -> None:
    def series(path: str):
        if "schema=wanBySiteByDevice" in path:
            return [{"siteId": SITE, "deviceMac": GW_MAC, "series": _points(END - HOUR, 2, rxBytes=7, txBytes=3)}]
        return [{"siteId": SITE, "deviceMac": GW_MAC, "series": _points(END - HOUR, 2, avgCpuUtilizationPct=20)}]

    manager, connection = _manager({"/source": ["MODERN"], "/recent/series": series})

    with patch("unifi_core.network.managers.stats_manager.DeviceManager") as device_manager:
        device_manager.return_value.get_devices = AsyncMock(return_value=[{"mac": GW_MAC, "type": "udm"}])
        rows = await manager.get_gateway_stats(duration_hours=1, granularity="hourly")

    assert rows == [{"time": END - HOUR, "gw": GW_MAC, "wan-rx_bytes": 14, "wan-tx_bytes": 6, "cpu": 20}]
    assert all(f"deviceMac.eq('{GW_MAC}')" in path for path in _series_paths(connection))


@pytest.mark.asyncio
async def test_series_permission_refusal_names_the_role() -> None:
    manager, _ = _manager({"/source": ["MODERN"], "/recent/series": Forbidden("403")})

    with pytest.raises(RequestError, match="Full Admin"):
        await manager.get_device_stats(AP_MAC, duration_hours=1, device_type="dev")


CLIENT_MAC = "aa:bb:cc:00:00:20"
OTHER_CLIENT = "aa:bb:cc:00:00:21"


@pytest.mark.asyncio
async def test_client_stats_read_the_client_series_from_the_network_side() -> None:
    """The series counts from the client's side, so its rx is the report's tx."""
    series = [{"siteId": SITE, "clientId": CLIENT_MAC, "series": _points(END - HOUR, 2, rxBytes=100, txBytes=3)}]
    manager, connection = _manager({"/source": ["MODERN"], "/recent/series": series})

    rows = await manager.get_client_stats(CLIENT_MAC.upper(), duration_hours=1)

    assert rows == [{"time": END - HOUR, "user": CLIENT_MAC, "tx_bytes": 200, "rx_bytes": 6, "bytes": 206}]
    (path,) = _series_paths(connection)
    assert "schema=activityBySiteByClient" in path and f"filter=clientId.eq('{CLIENT_MAC}')" in path


@pytest.mark.asyncio
async def test_top_clients_sum_this_sites_client_series_over_the_window() -> None:
    series = [
        {"siteId": SITE, "clientId": CLIENT_MAC, "series": _points(END - 2 * HOUR, 30, rxBytes=10, txBytes=1)},
        {"siteId": SITE, "clientId": OTHER_CLIENT, "series": _points(END - HOUR, 1, rxBytes=0, txBytes=500)},
        {"siteId": SITE, "clientId": "aa:bb:cc:00:00:22", "series": _points(END - HOUR, 1, rxBytes=0, txBytes=0)},
        {"siteId": OTHER_SITE, "clientId": "aa:bb:cc:00:00:23", "series": _points(END - HOUR, 1, txBytes=9999)},
    ]
    manager, connection = _manager({"/source": ["MODERN"], "/recent/series": series})

    ranked = await manager.get_top_clients(duration_hours=1, sort_by="upload")

    # 30 five-minute points from two hours back: only the 12 inside the last hour count.
    assert [(c["mac"], c["upload_bytes"], c["download_bytes"]) for c in ranked] == [
        (OTHER_CLIENT, 500, 0),
        (CLIENT_MAC, 12, 120),
    ]
    assert ranked[0]["source"] == "report" and ranked[0]["rx_bytes"] == 500
    assert not any(path.startswith("/stat/") for path in _paths(connection))


@pytest.mark.asyncio
async def test_top_clients_for_a_pinned_window_name_the_role_when_forbidden() -> None:
    manager, _ = _manager({"/source": Forbidden("403"), "/stat/report/": []})

    with pytest.raises(RequestError, match="Full Admin"):
        await manager.get_top_clients(start_ms=END - HOUR, end_ms=END)


@pytest.mark.asyncio
async def test_top_clients_series_refusal_keeps_the_role_message() -> None:
    manager, _ = _manager({"/source": ["MODERN"], "/recent/series": Forbidden("403")})

    with pytest.raises(RequestError, match="Full Admin"):
        await manager.get_top_clients(duration_hours=1)


@pytest.mark.asyncio
async def test_series_holding_only_another_sites_rows_are_empty_here() -> None:
    series = [{"siteId": OTHER_SITE, "series": _points(END - HOUR, 1, rxBytes=1000)}]
    manager, _ = _manager({"/source": ["MODERN"], "/recent/series": series})

    assert await manager.get_network_stats(duration_hours=1) == []


@pytest.mark.asyncio
async def test_client_history_filtered_by_mac_keeps_only_this_sites_rows() -> None:
    series = [
        {"siteId": SITE, "clientId": CLIENT_MAC, "series": _points(END - HOUR, 1, rxBytes=10)},
        {"siteId": OTHER_SITE, "clientId": CLIENT_MAC, "series": _points(END - HOUR, 1, rxBytes=1000)},
    ]
    manager, _ = _manager({"/source": ["MODERN"], "/recent/series": series})

    rows = await manager.get_client_stats(CLIENT_MAC, duration_hours=1)

    assert [row["tx_bytes"] for row in rows] == [10]


@pytest.mark.asyncio
async def test_windows_longer_than_a_month_are_refused_not_truncated() -> None:
    manager, connection = _manager({"/source": ["MODERN"], "/recent/series": []})

    with pytest.raises(ValueError, match="30 days"):
        await manager.get_client_stats(CLIENT_MAC, start_ms=END - 31 * 24 * HOUR, end_ms=END)
    with pytest.raises(ValueError, match="30 days"):
        await manager.get_top_clients(start_ms=END - 90 * 24 * HOUR, end_ms=END)
    assert _series_paths(connection) == []


@pytest.mark.asyncio
async def test_the_monthly_duration_fits_one_read() -> None:
    manager, connection = _manager({"/source": ["MODERN"], "/recent/series": []})

    assert await manager.get_network_stats(duration_hours=720, granularity="daily") == []
    assert all("period=MONTH" in path for path in _series_paths(connection))


@pytest.mark.asyncio
async def test_top_clients_on_network_11_with_an_empty_window_do_not_use_lifetime_counters() -> None:
    manager, connection = _manager({"/source": ["MODERN"], "/recent/series": []})

    assert await manager.get_top_clients(duration_hours=1) == []
    assert not any(path.startswith("/stat/sta") for path in _paths(connection))


@pytest.mark.asyncio
async def test_top_clients_for_a_duration_name_the_role_when_forbidden() -> None:
    manager, _ = _manager({"/source": Forbidden("403"), "/stat/report/": []})

    with pytest.raises(RequestError, match="Full Admin"):
        await manager.get_top_clients(duration_hours=24)
