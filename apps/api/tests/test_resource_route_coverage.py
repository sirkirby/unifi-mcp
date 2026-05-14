"""CI gate: every read tool must have a registered GET resource route.

Mirrors test_serializer_coverage.py. Adding a new unifi_list_*, unifi_get_*_details,
protect_list_*, protect_get_*, access_list_*, access_get_*, or *_recent_events tool
fails this test if no matching GET route is registered.

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

    manifest = ManifestRegistry.load_from_apps()
    read_tools = [t for t in manifest.all_tools() if is_read_tool(t)]

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
