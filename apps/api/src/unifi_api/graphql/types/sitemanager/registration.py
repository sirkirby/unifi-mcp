"""The nine account read projections; separate from console manager routing."""

from unifi_api.graphql.types.sitemanager.devices import SiteManagerHostDevices
from unifi_api.graphql.types.sitemanager.hosts import SiteManagerHost
from unifi_api.graphql.types.sitemanager.isp_metrics import SiteManagerIspMetricSeries, SiteManagerIspMetricsQueryResult
from unifi_api.graphql.types.sitemanager.sdwan import (
    SiteManagerSdwanConfig,
    SiteManagerSdwanConfigStatus,
    SiteManagerSdwanConfigSummary,
)
from unifi_api.graphql.types.sitemanager.sites import SiteManagerSite

REGISTRATIONS = {
    "sitemanager_list_hosts": ("hosts", SiteManagerHost, "list"),
    "sitemanager_get_host": ("hosts/{host_id}", SiteManagerHost, "detail"),
    "sitemanager_list_sites": ("sites", SiteManagerSite, "list"),
    "sitemanager_list_devices": ("devices", SiteManagerHostDevices, "list"),
    "sitemanager_get_isp_metrics": ("isp-metrics", SiteManagerIspMetricSeries, "list"),
    "sitemanager_query_isp_metrics": ("isp-metrics/query", SiteManagerIspMetricsQueryResult, "detail"),
    "sitemanager_list_sdwan_configs": ("sd-wan-configs", SiteManagerSdwanConfigSummary, "list"),
    "sitemanager_get_sdwan_config": ("sd-wan-configs/{config_id}", SiteManagerSdwanConfig, "detail"),
    "sitemanager_get_sdwan_config_status": (
        "sd-wan-configs/{config_id}/status",
        SiteManagerSdwanConfigStatus,
        "detail",
    ),
}


def register_types(registry):
    for name, (resource, projection, kind) in REGISTRATIONS.items():
        registry.register_tool_type(name, projection, kind)
        registry.register_type("sitemanager", resource, projection)
