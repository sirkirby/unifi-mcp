"""Tool wrappers: argument pass-through, response shape and error reporting."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock

import pytest

from unifi_core.exceptions import UniFiAuthError, UniFiNotFoundError, UniFiValidationError
from unifi_core.sitemanager.managers.isp_metrics_manager import IspMetricsQueryResult
from unifi_core.sitemanager.models.devices import host_devices_from_api
from unifi_core.sitemanager.models.hosts import host_from_api
from unifi_core.sitemanager.models.isp_metrics import series_from_api
from unifi_core.sitemanager.models.sdwan import sdwan_config_from_api, sdwan_status_from_api, sdwan_summary_from_api
from unifi_core.sitemanager.models.sites import site_from_api
from unifi_sitemanager_mcp.tools import devices, hosts, isp_metrics, sdwan, sites

HOST = host_from_api({"id": "host-1", "type": "console", "reportedState": {"hostname": "fixture-console"}})
SITE = site_from_api({"siteId": "site-1", "hostId": "host-1", "meta": {"name": "fixture-site"}})
DEVICES = host_devices_from_api(
    {"hostId": "host-1", "hostName": "fixture-console", "devices": [{"id": "d1"}, {"id": "d2"}]}
)
SERIES = series_from_api({"metricType": "1h", "hostId": "host-1", "siteId": "site-1", "periods": []})


@pytest.fixture
def inventory(monkeypatch):
    manager = AsyncMock()
    for module in (hosts, sites, devices):
        monkeypatch.setattr(module, "inventory_manager", manager)
    return manager


@pytest.fixture
def metrics(monkeypatch):
    manager = AsyncMock()
    monkeypatch.setattr(isp_metrics, "isp_metrics_manager", manager)
    return manager


@pytest.fixture
def sdwan_manager(monkeypatch):
    manager = AsyncMock()
    monkeypatch.setattr(sdwan, "sdwan_manager", manager)
    return manager


async def test_list_hosts_returns_one_page(inventory):
    inventory.list_hosts.return_value = ([HOST], "token-2")

    result = await hosts.sitemanager_list_hosts(page_size=1, cursor="token-1")

    inventory.list_hosts.assert_awaited_once_with(page_size=1, next_token="token-1")
    assert result["success"] is True
    assert result["data"]["count"] == 1 and result["data"]["next_cursor"] == "token-2"
    assert result["data"]["hosts"][0]["id"] == "host-1"
    assert result["data"]["hosts"][0]["hostname"] == "fixture-console"


async def test_get_host_passes_the_state_flag(inventory):
    inventory.get_host.return_value = HOST

    result = await hosts.sitemanager_get_host("host-1", include_reported_state=True)

    inventory.get_host.assert_awaited_once_with("host-1", include_reported_state=True)
    assert result == {"success": True, "data": {"host": HOST.model_dump(exclude_none=True)}}


async def test_list_sites_returns_one_page(inventory):
    inventory.list_sites.return_value = ([SITE], None)

    result = await sites.sitemanager_list_sites()

    inventory.list_sites.assert_awaited_once_with(page_size=None, next_token=None)
    assert result["data"]["count"] == 1 and result["data"]["next_cursor"] is None
    assert result["data"]["sites"][0]["site_id"] == "site-1"


async def test_list_devices_passes_filters_and_counts_devices(inventory):
    inventory.list_devices.return_value = ([DEVICES], None)

    result = await devices.sitemanager_list_devices(host_ids=["host-1"], updated_since="2026-01-01T00:00:00Z")

    inventory.list_devices.assert_awaited_once_with(
        host_ids=["host-1"], updated_since="2026-01-01T00:00:00Z", page_size=None, next_token=None
    )
    assert (result["data"]["host_count"], result["data"]["device_count"]) == (1, 2)
    assert [device["id"] for device in result["data"]["hosts"][0]["devices"]] == ["d1", "d2"]


async def test_get_isp_metrics_passes_the_window(metrics):
    metrics.get_metrics.return_value = [SERIES]

    result = await isp_metrics.sitemanager_get_isp_metrics("5m", duration="24h", period_limit=3)

    metrics.get_metrics.assert_awaited_once_with(
        "5m", duration="24h", begin_timestamp=None, end_timestamp=None, period_limit=3
    )
    assert result["data"]["count"] == 1
    assert result["data"]["sites"][0]["site_id"] == "site-1"


@pytest.mark.parametrize(("message", "has_message"), [("2 sites were left out", True), (None, False)])
async def test_query_isp_metrics_reports_partial_results(metrics, message, has_message):
    metrics.query_metrics.return_value = IspMetricsQueryResult(series=[SERIES], partial=True, message=message)
    requested = [{"host_id": "host-1", "site_id": "site-1"}]

    result = await isp_metrics.sitemanager_query_isp_metrics(requested)

    metrics.query_metrics.assert_awaited_once_with("1h", [{"host_id": "host-1", "site_id": "site-1"}], period_limit=12)
    assert result["data"]["partial"] is True and result["data"]["count"] == 1
    assert ("message" in result["data"]) is has_message


async def test_query_isp_metrics_refuses_a_misspelled_site_field(metrics):
    requested = [{"host_id": "host-1", "site_id": "site-1", "beginTimestamp": "2026-01-01T00:00:00Z"}]

    result = await isp_metrics.sitemanager_query_isp_metrics(requested)

    assert result["success"] is False
    assert "beginTimestamp" in result["error"] and "begin_timestamp" in result["error"]
    metrics.query_metrics.assert_not_awaited()


async def test_sdwan_tools_return_models(sdwan_manager):
    sdwan_manager.list_configs.return_value = [sdwan_summary_from_api({"id": "cfg-1", "name": "fixture"})]
    sdwan_manager.get_config.return_value = sdwan_config_from_api({"id": "cfg-1", "hubs": [{"id": "hub-1"}]})
    sdwan_manager.get_config_status.return_value = sdwan_status_from_api({"id": "cfg-1", "generateStatus": "OK"})

    listed = await sdwan.sitemanager_list_sdwan_configs()
    config = await sdwan.sitemanager_get_sdwan_config("cfg-1")
    status = await sdwan.sitemanager_get_sdwan_config_status("cfg-1")

    assert listed["data"] == {"configs": [{"id": "cfg-1", "name": "fixture"}], "count": 1}
    assert config["data"]["config"]["hubs"] == [{"id": "hub-1"}]
    assert status["data"]["status"]["generate_status"] == "OK"
    sdwan_manager.get_config.assert_awaited_once_with("cfg-1")
    sdwan_manager.get_config_status.assert_awaited_once_with("cfg-1")


async def test_an_account_without_sdwan_configs_lists_none(sdwan_manager):
    sdwan_manager.list_configs.return_value = []

    assert await sdwan.sitemanager_list_sdwan_configs() == {"success": True, "data": {"configs": [], "count": 0}}


CALLS = [
    (hosts.sitemanager_list_hosts, {}, "inventory", "list_hosts", "list hosts"),
    (hosts.sitemanager_get_host, {"host_id": "host-1"}, "inventory", "get_host", "get host"),
    (sites.sitemanager_list_sites, {}, "inventory", "list_sites", "list sites"),
    (devices.sitemanager_list_devices, {}, "inventory", "list_devices", "list devices"),
    (isp_metrics.sitemanager_get_isp_metrics, {}, "metrics", "get_metrics", "get ISP metrics"),
    (
        isp_metrics.sitemanager_query_isp_metrics,
        {"sites": [{"host_id": "h", "site_id": "s"}]},
        "metrics",
        "query_metrics",
        "query ISP metrics",
    ),
    (sdwan.sitemanager_list_sdwan_configs, {}, "sdwan_manager", "list_configs", "list SD-WAN configurations"),
    (sdwan.sitemanager_get_sdwan_config, {"config_id": "c"}, "sdwan_manager", "get_config", "get SD-WAN configuration"),
    (
        sdwan.sitemanager_get_sdwan_config_status,
        {"config_id": "c"},
        "sdwan_manager",
        "get_config_status",
        "get SD-WAN configuration status",
    ),
]


@pytest.mark.parametrize(("tool", "arguments", "fixture", "method", "operation"), CALLS)
async def test_every_tool_reports_a_typed_error_with_its_operation(
    request, tool, arguments, fixture, method, operation
):
    manager = request.getfixturevalue(fixture)
    getattr(manager, method).side_effect = UniFiAuthError("The Site Manager API rejected the API key (trace tr-1).")

    result = await tool(**arguments)

    assert result == {
        "success": False,
        "error": f"Failed to {operation}: The Site Manager API rejected the API key (trace tr-1).",
    }


@pytest.mark.parametrize(
    "error",
    [UniFiNotFoundError("Host", "host-9"), UniFiValidationError("Invalid host id")],
)
async def test_not_found_and_validation_errors_reach_the_caller(inventory, error):
    inventory.get_host.side_effect = error

    result = await hosts.sitemanager_get_host("host-9")

    assert result["success"] is False
    assert result["error"] == f"Failed to get host: {error}"


async def test_an_unexpected_error_is_reported_by_class_only(inventory, caplog):
    inventory.list_hosts.side_effect = RuntimeError("X-API-Key=secret-value host=fixture-console")

    with caplog.at_level(logging.DEBUG):
        result = await hosts.sitemanager_list_hosts()

    assert result == {"success": False, "error": "Failed to list hosts: unexpected RuntimeError"}
    assert "secret-value" not in caplog.text and "fixture-console" not in caplog.text
    assert "RuntimeError" in caplog.text


async def test_responses_are_redacted_unless_the_operator_turns_it_off(inventory, monkeypatch):
    monkeypatch.delenv("UNIFI_REDACT_SENSITIVE_FIELDS", raising=False)
    monkeypatch.delenv("UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS", raising=False)
    state = {"hostname": "fixture-console", "password": "fixture-secret"}
    inventory.get_host.return_value = host_from_api(
        {"id": "host-1", "reportedState": state}, include_reported_state=True
    )

    redacted = await hosts.sitemanager_get_host("host-1", include_reported_state=True)
    monkeypatch.setenv("UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS", "false")
    plain = await hosts.sitemanager_get_host("host-1", include_reported_state=True)

    assert "fixture-secret" not in json.dumps(redacted)
    assert redacted["data"]["host"]["reported_state"]["hostname"] == "fixture-console"
    assert plain["data"]["host"]["reported_state"]["password"] == "fixture-secret"
