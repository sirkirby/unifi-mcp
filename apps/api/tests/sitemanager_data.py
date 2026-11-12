"""Synthetic cloud transport and account factory shared by data-surface regressions."""

import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from unifi_core.sitemanager.managers.connection_manager import SiteManagerResponse
from unifi_core.sitemanager.managers.inventory_manager import InventoryManager
from unifi_core.sitemanager.managers.isp_metrics_manager import IspMetricsManager
from unifi_core.sitemanager.managers.sdwan_manager import SdwanManager

from tests.test_controllers_routes import _bootstrap_app

TOKEN = "opaque:+/%= token\u2603"
SENSITIVE = "sensitive-example-value"
HOST = {
    "id": "synthetic-host",
    "owner": False,
    "registrationTime": 0,
    "reportedState": {
        "name": "Synthetic host",
        "state": "connected",
        "api_key": SENSITIVE,
        "nested": {"password": SENSITIVE},
        "controllers": [{"name": "network", "isInstalled": False}],
    },
}
SITE = {
    "hostId": "synthetic-host",
    "siteId": "synthetic-site",
    "isOwner": False,
    "meta": {"name": "Synthetic site"},
    "statistics": {"counts": {"devices": 0}, "percentages": {"wanUptime": 0}},
}
DEVICES = {
    "hostId": "synthetic-host",
    "hostName": "Synthetic host",
    "updatedAt": 0,
    "devices": [
        {"id": "synthetic-device", "name": "Synthetic device", "isConsole": False, "startupTime": 0},
        {"id": "synthetic-device-two", "name": "Second synthetic device", "isManaged": False},
    ],
}
METRICS = {
    "hostId": "synthetic-host",
    "siteId": "synthetic-site",
    "metricType": "1h",
    "periods": [
        {"metricTime": 0, "data": {"wan": {"avgLatency": 0, "download_kbps": 0, "downtime": 0}}},
        {"metricTime": "2026-01-01T01:00:00Z", "data": {"wan": {"avgLatency": 10, "download_kbps": 20, "downtime": 2}}},
        {"metricTime": 2, "data": {"wan": {"avgLatency": 20, "download_kbps": 40, "downtime": 4}}},
    ],
}
CONFIG = {
    "id": "synthetic-config",
    "name": "Synthetic SD-WAN",
    "type": "hub-and-spoke",
    "variant": "test",
    "settings": {"api_key": SENSITIVE},
    "hubs": [{"password": SENSITIVE}],
    "spokes": [],
}
STATUS = {
    "id": "synthetic-config",
    "generateStatus": "complete",
    "updatedAt": 0,
    "errors": [{"api_key": SENSITIVE}],
    "warnings": [],
    "hubs": [],
    "spokes": [{"secret": SENSITIVE}],
}


class DataFactory:
    def __init__(self):
        async def get(path, **kwargs):
            if path == "/v1/hosts":
                return SiteManagerResponse([copy.deepcopy(HOST)], TOKEN)
            if path.startswith("/v1/hosts/"):
                return SiteManagerResponse(copy.deepcopy(HOST))
            if path == "/v1/sites":
                return SiteManagerResponse([copy.deepcopy(SITE)], TOKEN)
            if path == "/v1/devices":
                return SiteManagerResponse([copy.deepcopy(DEVICES)], TOKEN)
            if path.startswith("/v1/isp-metrics/"):
                return SiteManagerResponse([copy.deepcopy(METRICS)])
            if path == "/v1/sd-wan-configs":
                return SiteManagerResponse([copy.deepcopy(CONFIG)])
            if path.endswith("/status"):
                return SiteManagerResponse(copy.deepcopy(STATUS))
            if path.startswith("/v1/sd-wan-configs/"):
                return SiteManagerResponse(copy.deepcopy(CONFIG))
            raise AssertionError("Unexpected synthetic cloud path")

        async def post(path, **kwargs):
            assert path.startswith("/v1/isp-metrics/") and path.endswith("/query")
            return SiteManagerResponse(
                {
                    "metrics": [copy.deepcopy(METRICS)],
                    "status": "partialSuccess",
                    "message": "One synthetic site omitted",
                }
            )

        self.connection = SimpleNamespace(get=AsyncMock(side_effect=get), post=AsyncMock(side_effect=post))
        self.bundle = SimpleNamespace(
            connection_id="synthetic-local-account",
            revision=1,
            inventory_manager=InventoryManager(self.connection),
            isp_metrics_manager=IspMetricsManager(self.connection),
            sdwan_manager=SdwanManager(self.connection),
        )
        for manager, methods in (
            (self.bundle.inventory_manager, ["list_hosts", "get_host", "list_sites", "list_devices"]),
            (self.bundle.isp_metrics_manager, ["get_metrics", "query_metrics"]),
            (self.bundle.sdwan_manager, ["list_configs", "get_config", "get_config_status"]),
        ):
            for method in methods:
                setattr(manager, method, AsyncMock(wraps=getattr(manager, method)))
        self.acquisitions = 0

    @asynccontextmanager
    async def acquire(self):
        self.acquisitions += 1
        yield self.bundle


async def bootstrap(tmp_path, monkeypatch, scope="read", *, fake=True):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes=scope)
    factory = DataFactory() if fake else app.state.sitemanager_factory
    if fake:
        app.state.sitemanager_factory = factory
    return app, key, factory


CASES = [
    (
        "sitemanager_list_hosts",
        "GET",
        "/v1/sitemanager/hosts",
        {},
        "inventory_manager",
        "list_hosts",
        "hosts { items { id owner registrationTime applications { name isInstalled } } nextCursor }",
        "hosts",
    ),
    (
        "sitemanager_get_host",
        "GET",
        "/v1/sitemanager/hosts/synthetic-host",
        {"host_id": "synthetic-host"},
        "inventory_manager",
        "get_host",
        'host(hostId:"synthetic-host") { id name owner }',
        "host",
    ),
    (
        "sitemanager_list_sites",
        "GET",
        "/v1/sitemanager/sites",
        {},
        "inventory_manager",
        "list_sites",
        "sites { items { hostId siteId counts isOwner wanUptimePercent } nextCursor }",
        "sites",
    ),
    (
        "sitemanager_list_devices",
        "GET",
        "/v1/sitemanager/devices",
        {},
        "inventory_manager",
        "list_devices",
        "devices { items { hostId updatedAt devices { id name isConsole startupTime } } nextCursor }",
        "devices",
    ),
    (
        "sitemanager_get_isp_metrics",
        "GET",
        "/v1/sitemanager/isp-metrics",
        {},
        "isp_metrics_manager",
        "get_metrics",
        (
            "ispMetrics { items { hostId siteId summary { periodCount avgLatencyMs } "
            "periods { time avgLatencyMs } } count nextCursor }"
        ),
        "ispMetrics",
    ),
    (
        "sitemanager_query_isp_metrics",
        "POST",
        "/v1/sitemanager/isp-metrics/query",
        {"sites": [{"host_id": "synthetic-host", "site_id": "synthetic-site"}]},
        "isp_metrics_manager",
        "query_metrics",
        (
            'queryIspMetrics(sites:[{hostId:"synthetic-host",siteId:"synthetic-site"}]) '
            "{ items { siteId } count partial message nextCursor }"
        ),
        "queryIspMetrics",
    ),
    (
        "sitemanager_list_sdwan_configs",
        "GET",
        "/v1/sitemanager/sd-wan-configs",
        {},
        "sdwan_manager",
        "list_configs",
        "sdwanConfigs { items { id name type } nextCursor }",
        "sdwanConfigs",
    ),
    (
        "sitemanager_get_sdwan_config",
        "GET",
        "/v1/sitemanager/sd-wan-configs/synthetic-config",
        {"config_id": "synthetic-config"},
        "sdwan_manager",
        "get_config",
        'sdwanConfig(configId:"synthetic-config") { id settings hubs spokes variant }',
        "sdwanConfig",
    ),
    (
        "sitemanager_get_sdwan_config_status",
        "GET",
        "/v1/sitemanager/sd-wan-configs/synthetic-config/status",
        {"config_id": "synthetic-config"},
        "sdwan_manager",
        "get_config_status",
        'sdwanConfigStatus(configId:"synthetic-config") { id updatedAt errors warnings spokes }',
        "sdwanConfigStatus",
    ),
]
