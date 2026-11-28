"""CI gate: every read tool must have a registered GET resource route.

Mirrors test_serializer_coverage.py. Adding a read tool to the action catalog, for any
product (Network, Protect, Access, Site Manager, InnerSpace, Drive), fails this test if no
matching resource route is registered.

The default convention is "tool name minus product prefix" (e.g., unifi_list_clients
maps to a route function named list_clients). When a route is registered under a
different name (e.g., unifi_list_usergroups -> list_user_groups), record the mapping
in TOOL_ROUTE_OVERRIDES.

When a read tool intentionally has no resource route (e.g., the data is exposed via
a different surface), document it in TOOLS_WITHOUT_ROUTE with an # explanation:
comment.
"""

import os

from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.server import create_app
from unifi_api.services.manifest import ManifestRegistry
from unifi_api.services.resource_routes import collect_resource_routes, is_read_tool

# Tools whose registered route function name doesn't match the default convention
# (tool name minus product prefix). Populated from the Task 22 audit.
TOOL_ROUTE_OVERRIDES: dict[str, str] = {
    "sitemanager_list_hosts": "list_sitemanager_hosts",
    "sitemanager_get_host": "get_sitemanager_host",
    "sitemanager_list_sites": "list_sitemanager_sites",
    "sitemanager_list_devices": "list_sitemanager_devices",
    "sitemanager_get_isp_metrics": "get_sitemanager_isp_metrics",
    "sitemanager_query_isp_metrics": "query_sitemanager_isp_metrics",
    "sitemanager_list_sdwan_configs": "list_sitemanager_sdwan_configs",
    "sitemanager_get_sdwan_config": "get_sitemanager_sdwan_config",
    "sitemanager_get_sdwan_config_status": "get_sitemanager_sdwan_config_status",
    # InnerSpace — product-prefixed route functions to disambiguate from Network and Access.
    "innerspace_get_status": "get_innerspace_status",
    "innerspace_get_project": "get_innerspace_project",
    "innerspace_list_floor_plans": "list_innerspace_floor_plans",
    "innerspace_list_walls": "list_innerspace_walls",
    "innerspace_list_placed_devices": "list_innerspace_placed_devices",
    "innerspace_list_access_points": "list_innerspace_access_points",
    "innerspace_list_switches": "list_innerspace_switches",
    "innerspace_list_inventory": "list_innerspace_inventory",
    "innerspace_get_plan_asset": "get_innerspace_plan_asset",
    # Drive — product-prefixed route functions to disambiguate from Network, Access and InnerSpace.
    "drive_get_system_info": "get_drive_system_info",
    "drive_list_storage_pools": "list_drive_storage_pools",
    "drive_list_disks": "list_drive_disks",
    "drive_list_shared_drives": "list_drive_shared_drives",
    "drive_get_shared_drive": "get_drive_shared_drive",
    "drive_get_file_services": "get_drive_file_services",
    "drive_list_nfs_connections": "list_drive_nfs_connections",
    "drive_list_logs": "list_drive_logs",
    "drive_get_storage_usage": "get_drive_storage_usage",
    "drive_get_network_throughput": "get_drive_network_throughput",
    "drive_get_fan_profile": "get_drive_fan_profile",
    "drive_get_disk_stats": "get_drive_disk_stats",
    "drive_get_snapshot_overview": "get_drive_snapshot_overview",
    "drive_list_snapshots": "list_drive_snapshots",
    "drive_get_smb_advanced_settings": "get_drive_smb_advanced_settings",
    "drive_get_rsync_settings": "get_drive_rsync_settings",
    "drive_list_users": "list_drive_users",
    "drive_list_groups": "list_drive_groups",
    # Access — domain-prefixed route functions to disambiguate from network/protect.
    "access_get_activity_summary": "get_access_activity_summary",
    "access_get_health": "get_access_health",
    # Protect — domain-prefixed health/snapshot routes.
    "protect_get_health": "get_protect_health",
    "protect_get_snapshot": "get_camera_snapshot",
    # Network — *_details tool name vs. shorter route function name.
    "unifi_get_client_details": "get_client",
    "unifi_get_device_details": "get_device",
    "unifi_get_network_details": "get_network",
    "unifi_get_wlan_details": "get_wlan",
    # Network — dashboard tool maps to stats sub-resource.
    "unifi_get_dashboard": "get_dashboard_stats",
    # Network — firewall policy tool aliases the firewall rules route.
    "unifi_get_firewall_policy_details": "get_firewall_rule",
    "unifi_list_firewall_policies": "list_firewall_rules",
    # Network — single get_* tool backed by a list_* route (collection endpoint).
    "unifi_get_lldp_neighbors": "list_lldp_neighbors",
    "unifi_get_port_stats": "list_port_stats",
    "unifi_get_rf_scan_results": "list_rf_scan_results",
    "unifi_get_switch_ports": "list_switch_ports",
    # Network — usergroup tool name (one word) vs. user_group route function (snake).
    # Incident evidence — product-prefixed route functions, one per product.
    "unifi_get_incident_evidence": "get_network_incident_evidence",
    "protect_get_incident_evidence": "get_protect_incident_evidence",
    "unifi_get_usergroup_details": "get_user_group_details",
    "unifi_list_usergroups": "list_user_groups",
}

# Tools that intentionally don't get a resource route. Document why with an
# # explanation: comment for each entry. Empty by default — every read tool
# should have a route.
TOOLS_WITHOUT_ROUTE: set[str] = set()


def test_every_read_tool_has_a_resource_route(tmp_path) -> None:
    os.environ["UNIFI_API_DB_KEY"] = "ci-gate-test"
    cfg = ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )
    app = create_app(cfg)

    routes = collect_resource_routes(app)
    route_names = {r.name for r in routes}
    assert {(r.method, r.path, r.name) for r in routes if r.path.startswith("/v1/sitemanager/")} == {
        ("GET", "/v1/sitemanager/hosts", "list_sitemanager_hosts"),
        ("GET", "/v1/sitemanager/hosts/{host_id}", "get_sitemanager_host"),
        ("GET", "/v1/sitemanager/sites", "list_sitemanager_sites"),
        ("GET", "/v1/sitemanager/devices", "list_sitemanager_devices"),
        ("GET", "/v1/sitemanager/isp-metrics", "get_sitemanager_isp_metrics"),
        ("POST", "/v1/sitemanager/isp-metrics/query", "query_sitemanager_isp_metrics"),
        ("GET", "/v1/sitemanager/sd-wan-configs", "list_sitemanager_sdwan_configs"),
        ("GET", "/v1/sitemanager/sd-wan-configs/{config_id}", "get_sitemanager_sdwan_config"),
        ("GET", "/v1/sitemanager/sd-wan-configs/{config_id}/status", "get_sitemanager_sdwan_config_status"),
    }
    assert {(r.path, r.name) for r in routes if "/drive/" in r.path} == {
        ("/v1/sites/{site_id}/drive/system", "get_drive_system_info"),
        ("/v1/sites/{site_id}/drive/storage-pools", "list_drive_storage_pools"),
        ("/v1/sites/{site_id}/drive/disks", "list_drive_disks"),
        ("/v1/sites/{site_id}/drive/shared-drives", "list_drive_shared_drives"),
        ("/v1/sites/{site_id}/drive/shared-drives/{drive_id}", "get_drive_shared_drive"),
        ("/v1/sites/{site_id}/drive/file-services", "get_drive_file_services"),
        ("/v1/sites/{site_id}/drive/nfs-connections", "list_drive_nfs_connections"),
        ("/v1/sites/{site_id}/drive/logs", "list_drive_logs"),
        ("/v1/sites/{site_id}/drive/storage-usage", "get_drive_storage_usage"),
        ("/v1/sites/{site_id}/drive/network-throughput", "get_drive_network_throughput"),
        ("/v1/sites/{site_id}/drive/fan-profile", "get_drive_fan_profile"),
        ("/v1/sites/{site_id}/drive/disk-stats", "get_drive_disk_stats"),
        ("/v1/sites/{site_id}/drive/snapshot-overview", "get_drive_snapshot_overview"),
        ("/v1/sites/{site_id}/drive/snapshots/shared/{shared_drive_name}", "list_drive_snapshots"),
        ("/v1/sites/{site_id}/drive/smb-advanced-settings", "get_drive_smb_advanced_settings"),
        ("/v1/sites/{site_id}/drive/rsync-settings", "get_drive_rsync_settings"),
        ("/v1/sites/{site_id}/drive/users", "list_drive_users"),
        ("/v1/sites/{site_id}/drive/groups", "list_drive_groups"),
    }

    manifest = ManifestRegistry.load()
    read_tools = [t for t in manifest.all_tools() if is_read_tool(t, manifest.resolve(t))]

    missing: list[tuple[str, str | None]] = []
    for tool in read_tools:
        if tool in TOOLS_WITHOUT_ROUTE:
            continue
        expected_route = TOOL_ROUTE_OVERRIDES.get(tool)
        if expected_route is None:
            parts = tool.split("_", 1)
            if len(parts) == 2:
                expected_route = parts[1]
        if expected_route not in route_names:
            missing.append((tool, expected_route))

    assert not missing, f"{len(missing)} read tools lack a resource route:\n" + "\n".join(
        f"  {t} (expected route fn: {r})" for t, r in missing[:30]
    )
