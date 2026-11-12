"""Site Manager managers: request shape, input validation and response curation."""

import pytest
from unifi_core.exceptions import (
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiValidationError,
)
from unifi_core.sitemanager.managers.connection_manager import SiteManagerHttpError
from unifi_core.sitemanager.managers.inventory_manager import InventoryManager
from unifi_core.sitemanager.managers.isp_metrics_manager import IspMetricsManager
from unifi_core.sitemanager.managers.sdwan_manager import SdwanManager

HOST_ID = "AAAA0000BBBB:1234567890"
HOST = {
    "id": HOST_ID,
    "hardwareId": "hw-1",
    "type": "console",
    "ipAddress": "203.0.113.7",
    "owner": True,
    "isBlocked": False,
    "registrationTime": "2026-01-02T03:04:05Z",
    "lastConnectionStateChange": "",
    "latestBackupTime": None,
    "userData": {"email": "owner@example.test", "fullName": "Example Owner", "role": "owner"},
    "reportedState": {
        "name": "Lab Console",
        "hostname": "lab-console",
        "state": "connected",
        "version": "6.0.1",
        "mac": "00:00:5E:00:53:01",
        "timezone": "UTC",
        "releaseChannel": "release",
        "anonid": "anon-1",
        "location": {"lat": 1.0, "long": 2.0},
        "uidb": {"images": {}},
        "hardware": {"name": "Example Gateway", "shortname": "EXGW", "firmwareVersion": "6.0.1", "serialno": "S1"},
        "controllers": [
            {
                "name": "network",
                "type": "controller",
                "version": "11.0.0",
                "state": "active",
                "isRunning": True,
                "isInstalled": True,
                "isConfigured": True,
                "updateAvailable": {"version": "11.0.1"},
            },
            {"name": "protect", "version": "", "state": "inactive", "isInstalled": False, "updateAvailable": None},
            "unexpected",
        ],
    },
}


def _period(time: str, latency: int, downtime: int = 0) -> dict:
    return {
        "metricTime": time,
        "version": "1",
        "data": {
            "wan": {
                "avgLatency": latency,
                "maxLatency": latency * 2,
                "packetLoss": 0,
                "download_kbps": 1000,
                "upload_kbps": 100,
                "uptime": 100,
                "downtime": downtime,
                "ispName": "Example ISP",
                "ispAsn": "64500",
            }
        },
    }


@pytest.fixture
def inventory(connection):
    return InventoryManager(connection)


@pytest.fixture
def metrics(connection):
    return IspMetricsManager(connection)


@pytest.fixture
def sdwan(connection):
    return SdwanManager(connection)


async def test_list_hosts_pages_and_drops_account_data(inventory, api):
    api.reply("GET", "/v1/hosts", {"data": [HOST], "nextToken": "next-1"})

    hosts, next_token = await inventory.list_hosts(page_size=1, next_token="tok")

    assert next_token == "next-1"
    assert api.requests[0].query == [("pageSize", "1"), ("nextToken", "tok")]
    dumped = hosts[0].model_dump(exclude_none=True)
    assert dumped["name"] == "Lab Console" and dumped["shortname"] == "EXGW" and dumped["os_version"] == "6.0.1"
    assert "last_connection_state_change" not in dumped and "latest_backup_time" not in dumped
    assert "reported_state" not in dumped
    assert "owner@example.test" not in str(dumped) and "Example Owner" not in str(dumped)
    apps = {app["name"]: app for app in dumped["applications"]}
    assert apps["network"]["update_available"] == "11.0.1" and apps["network"]["is_running"] is True
    assert "version" not in apps["protect"]


@pytest.mark.parametrize("kwargs", [{"page_size": 0}, {"page_size": 501}, {"page_size": True}, {"next_token": " "}])
async def test_page_arguments_are_validated_before_any_request(inventory, api, kwargs):
    with pytest.raises(UniFiValidationError):
        await inventory.list_hosts(**kwargs)
    assert not api.requests


async def test_get_host_encodes_the_id_and_can_return_reported_state(inventory, api):
    api.reply("GET", "/v1/hosts/AAAA0000BBBB%3A1234567890", {"data": HOST})

    host = await inventory.get_host(HOST_ID, include_reported_state=True)

    assert host.id == HOST_ID
    assert host.reported_state["hostname"] == "lab-console"
    assert not {"anonid", "location", "uidb"} & host.reported_state.keys()


async def test_get_host_reports_a_missing_host(inventory, api):
    api.reply("GET", "/v1/hosts/nope", {"code": "DATA_NOT_FOUND"}, status=404)

    with pytest.raises(UniFiNotFoundError, match="Host 'nope' not found"):
        await inventory.get_host("nope")


async def test_get_host_refuses_an_id_that_is_not_one_segment(inventory, api):
    with pytest.raises(UniFiValidationError):
        await inventory.get_host("../sites")
    assert not api.requests


async def test_host_with_null_reported_state_still_reads(inventory, api):
    api.reply("GET", "/v1/hosts", {"data": [{"id": "h", "reportedState": None, "registrationTime": ""}, "junk"]})

    hosts, next_token = await inventory.list_hosts()

    assert next_token is None
    assert hosts[0].model_dump(exclude_none=True) == {"id": "h", "applications": []}


async def test_list_sites_curates_meta_and_statistics(inventory, api):
    site = {
        "siteId": "site-1",
        "hostId": HOST_ID,
        "permission": "admin",
        "isOwner": True,
        "meta": {"name": "default", "desc": "Lab", "timezone": "UTC", "gatewayMac": "00:00:5E:00:53:01"},
        "statistics": {
            "counts": {"totalDevice": 4, "wifiClient": 9, "flag": True, "nested": {"x": 1}},
            "gateway": {"shortname": "EXGW", "ipsMode": "ids", "ipsSignature": {"rulesCount": 5}},
            "ispInfo": {"name": "Example ISP", "organization": "Example Org"},
            "percentages": {"wanUptime": 99},
            "internetIssues": [{"index": 1, "highLatency": True, "latencyAvgMs": 80}, "junk"],
        },
    }
    api.reply("GET", "/v1/sites", {"data": [site]})

    sites, _ = await inventory.list_sites()

    dumped = sites[0].model_dump(exclude_none=True)
    assert dumped["description"] == "Lab" and dumped["wan_uptime_percent"] == 99
    assert dumped["counts"] == {"totalDevice": 4, "wifiClient": 9}
    assert dumped["gateway"] == {"shortname": "EXGW", "ipsMode": "ids"}
    assert dumped["internet_issues"] == [{"index": 1, "highLatency": True, "latencyAvgMs": 80}]


async def test_list_devices_sends_filters_and_drops_uidb(inventory, api):
    group = {
        "hostId": HOST_ID,
        "hostName": "Lab Console",
        "updatedAt": "2026-01-02T03:04:05Z",
        "devices": [
            {
                "id": "d1",
                "mac": "00005E005302",
                "name": "AP",
                "status": "online",
                "isConsole": False,
                "updateAvailable": "",
                "uidb": {"guid": "g"},
            }
        ],
    }
    api.reply("GET", "/v1/devices", {"data": [group]})

    groups, _ = await inventory.list_devices(host_ids=[HOST_ID, "h2"], updated_since="2026-01-01T00:00:00Z")

    assert api.requests[0].query == [("hostIds[]", HOST_ID), ("hostIds[]", "h2"), ("time", "2026-01-01T00:00:00Z")]
    dumped = groups[0].model_dump(exclude_none=True)
    assert dumped["host_name"] == "Lab Console"
    assert dumped["devices"] == [
        {"id": "d1", "mac": "00005E005302", "name": "AP", "status": "online", "is_console": False}
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"host_ids": []},
        {"host_ids": [""]},
        {"host_ids": "h1"},
        {"updated_since": "yesterday"},
        {"updated_since": "2026-01-01T00:00:00"},
    ],
)
async def test_device_filters_are_validated(inventory, api, kwargs):
    with pytest.raises(UniFiValidationError):
        await inventory.list_devices(**kwargs)
    assert not api.requests


async def test_unreadable_collection_is_not_an_empty_one(inventory, api):
    api.reply("GET", "/v1/sites", {"data": {"unexpected": "object"}})

    with pytest.raises(UniFiMalformedResponseError):
        await inventory.list_sites()


async def test_metrics_default_window_summary_and_truncation(metrics, api):
    periods = [
        _period(f"2026-01-01T{hour:02d}:00:00Z", latency=10 + hour, downtime=5 if hour == 3 else 0) for hour in range(6)
    ]
    api.reply(
        "GET",
        "/v1/isp-metrics/5m",
        {"data": [{"metricType": "5m", "hostId": HOST_ID, "siteId": "s1", "periods": periods}]},
    )

    (series,) = await metrics.get_metrics("5m", period_limit=2)

    assert api.requests[0].query == [("duration", "24h")]
    assert [period.time for period in series.periods] == ["2026-01-01T04:00:00Z", "2026-01-01T05:00:00Z"]
    assert series.periods_truncated is True
    summary = series.summary
    assert (summary.period_count, summary.first_time, summary.last_time) == (
        6,
        "2026-01-01T00:00:00Z",
        "2026-01-01T05:00:00Z",
    )
    assert summary.avg_latency_ms == 12.5 and summary.max_latency_ms == 30
    assert (summary.total_downtime, summary.periods_with_downtime) == (5, 1)


async def test_metrics_series_shorter_than_the_limit_is_returned_whole(metrics, api):
    periods = [_period(f"2026-01-01T{hour:02d}:00:00Z", latency=10) for hour in range(3)]
    api.reply("GET", "/v1/isp-metrics/1h", {"data": [{"periods": periods}]})

    (series,) = await metrics.get_metrics("1h", period_limit=5)

    assert [period.time for period in series.periods] == [
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
        "2026-01-01T02:00:00Z",
    ]
    assert series.periods_truncated is False


async def test_metrics_period_limit_zero_returns_summary_only(metrics, api):
    api.reply("GET", "/v1/isp-metrics/1h", {"data": [{"periods": [_period("2026-01-01T00:00:00Z", 10)]}]})

    (series,) = await metrics.get_metrics("1h", duration="30d", period_limit=0)

    assert api.requests[0].query == [("duration", "30d")]
    assert series.periods == [] and series.periods_truncated is True and series.summary.period_count == 1


async def test_metrics_accepts_a_timestamp_range(metrics, api):
    api.reply("GET", "/v1/isp-metrics/1h", {"data": []})

    assert (
        await metrics.get_metrics(
            "1h", begin_timestamp="2026-01-01T00:00:00Z", end_timestamp="2026-01-02T00:00:00+00:00"
        )
        == []
    )
    assert api.requests[0].query == [
        ("beginTimestamp", "2026-01-01T00:00:00Z"),
        ("endTimestamp", "2026-01-02T00:00:00+00:00"),
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"metric_type": "15m"},
        {"metric_type": "5m", "duration": "7d"},
        {"metric_type": "1h", "duration": "24h"},
        {"metric_type": "1h", "duration": "7d", "begin_timestamp": "2026-01-01T00:00:00Z"},
        {"metric_type": "1h", "begin_timestamp": "2026-01-01T00:00:00Z"},
        {"metric_type": "1h", "begin_timestamp": "2026-01-01", "end_timestamp": "2026-01-02T00:00:00Z"},
        {"metric_type": "1h", "period_limit": 721},
        {"metric_type": "1h", "period_limit": -1},
    ],
)
async def test_metrics_arguments_are_validated_before_any_request(metrics, api, kwargs):
    with pytest.raises(UniFiValidationError):
        await metrics.get_metrics(**kwargs)
    assert not api.requests


async def test_metrics_query_sends_per_site_ranges_and_reports_partial_results(metrics, api):
    api.reply(
        "POST",
        "/v1/isp-metrics/5m/query",
        {
            "data": {
                "metrics": [{"hostId": HOST_ID, "siteId": "s1", "metricType": "5m", "periods": []}],
                "status": "partialSuccess",
                "message": "some sites were ignored",
            }
        },
    )

    result = await metrics.query_metrics(
        "5m",
        [
            {
                "host_id": HOST_ID,
                "site_id": "s1",
                "begin_timestamp": "2026-01-01T00:00:00Z",
                "end_timestamp": "2026-01-01T06:00:00Z",
            },
            {"host_id": "h2", "site_id": "s2"},
        ],
    )

    assert api.requests[0].body == {
        "sites": [
            {
                "hostId": HOST_ID,
                "siteId": "s1",
                "beginTimestamp": "2026-01-01T00:00:00Z",
                "endTimestamp": "2026-01-01T06:00:00Z",
            },
            {"hostId": "h2", "siteId": "s2"},
        ]
    }
    assert result.partial is True and result.message == "some sites were ignored"
    assert result.series[0].site_id == "s1"


async def test_metrics_query_reports_a_gateway_error_as_an_upstream_failure(metrics, api):
    api.reply("POST", "/v1/isp-metrics/1h/query", {"code": "BAD_GATEWAY"}, status=502)

    with pytest.raises(SiteManagerHttpError) as raised:
        await metrics.query_metrics("1h", [{"host_id": "h", "site_id": "s"}])

    assert raised.value.status == 502


@pytest.mark.parametrize("data", [None, [], {}, {"metrics": None}, {"status": "partialSuccess"}])
async def test_metrics_query_unreadable_result_is_not_an_empty_one(metrics, api, data):
    api.reply("POST", "/v1/isp-metrics/1h/query", {"data": data})

    with pytest.raises(UniFiMalformedResponseError):
        await metrics.query_metrics("1h", [{"host_id": "h", "site_id": "s"}])


async def test_metrics_query_with_no_metrics_for_a_site_is_empty_and_complete(metrics, api):
    api.reply("POST", "/v1/isp-metrics/1h/query", {"data": {"metrics": []}})

    result = await metrics.query_metrics("1h", [{"host_id": "h", "site_id": "s"}])

    assert (result.series, result.partial, result.message) == ([], False, None)


@pytest.mark.parametrize(
    "sites",
    [
        [],
        "s1",
        [{"host_id": "h"}],
        [{"host_id": "h", "site_id": "s", "end_timestamp": "later"}],
        [{"host_id": "h", "site_id": "s"}] * 51,
    ],
)
async def test_metrics_query_sites_are_validated(metrics, api, sites):
    with pytest.raises(UniFiValidationError):
        await metrics.query_metrics("5m", sites)
    assert not api.requests


async def test_sdwan_list_get_and_status(sdwan, api):
    api.reply("GET", "/v1/sd-wan-configs", {"data": [{"id": "cfg_1", "name": "Mesh", "type": "sdwan-hbsp"}]})
    api.reply(
        "GET",
        "/v1/sd-wan-configs/cfg_1",
        {
            "data": {
                "id": "cfg_1",
                "name": "Mesh",
                "type": "sdwan-hbsp",
                "variant": "distributed",
                "settings": {"hubsInterconnect": True},
                "hubs": [{"id": "hub_1", "hostId": HOST_ID}],
                "spokes": None,
            }
        },
    )
    api.reply(
        "GET",
        "/v1/sd-wan-configs/cfg_1/status",
        {
            "data": {
                "id": "",
                "fingerprint": "fp",
                "generateStatus": "OK",
                "updatedAt": 1767225600000,
                "lastGeneratedAt": 0,
                "hubs": [{"id": "hub_1", "applyStatus": "OK"}],
                "spokes": [],
                "errors": [],
                "warnings": [{}],
            }
        },
    )

    (summary,) = await sdwan.list_configs()
    config = await sdwan.get_config("cfg_1")
    status = await sdwan.get_config_status("cfg_1")

    assert summary.model_dump() == {"id": "cfg_1", "name": "Mesh", "type": "sdwan-hbsp"}
    assert config.settings == {"hubsInterconnect": True} and config.hubs[0]["id"] == "hub_1" and config.spokes == []
    assert status.id is None and status.updated_at == 1767225600000 and status.hubs[0]["applyStatus"] == "OK"


async def test_sdwan_missing_config(sdwan, api):
    api.reply("GET", "/v1/sd-wan-configs/gone/status", status=404)

    with pytest.raises(UniFiNotFoundError, match="SD-WAN configuration 'gone' not found"):
        await sdwan.get_config_status("gone")
