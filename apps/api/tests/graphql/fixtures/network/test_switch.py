"""Fixture e2e tests for network/switch+groups resolvers.

# tool: unifi_list_port_profiles
# tool: unifi_get_port_profile_details
# tool: unifi_get_switch_ports
# tool: unifi_get_port_stats
# tool: unifi_get_switch_capabilities
# tool: unifi_list_ap_groups
# tool: unifi_get_ap_group_details
# tool: unifi_list_usergroups
# tool: unifi_get_usergroup_details
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.parametrize(
    ("manager_results", "query", "query_field", "expected"),
    [
        pytest.param(
            {
                ("network", "switch_manager", "get_port_profiles"): [
                    {"_id": "pp-1", "name": "All", "poe_mode": "auto"},
                    {"_id": "pp-2", "name": "Disabled", "poe_mode": "off"},
                ]
            },
            '{ network { portProfiles(controller: "CONTROLLER_ID", limit: 10) { items { id name poeMode } } } }',
            "portProfiles",
            {"All", "Disabled"},
            id="port_profiles_list",
        ),
        pytest.param(
            {
                ("network", "usergroup_manager", "get_usergroups"): [
                    {"_id": "ug-1", "name": "Premium", "qos_rate_max_down": 20000},
                    {"_id": "ug-2", "name": "Standard", "qos_rate_max_down": 5000},
                ]
            },
            '{ network { userGroups(controller: "CONTROLLER_ID", limit: 10) { items { id name qosRateMaxDown } } } }',
            "userGroups",
            {"Premium", "Standard"},
            id="user_groups_list",
        ),
    ],
)
@pytest.mark.asyncio
async def test_switch_config_pages(tmp_path, monkeypatch, manager_results, query, query_field, expected):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, manager_results)
    body = await graphql_query(app, key, query.replace("CONTROLLER_ID", cid))
    assert body.get("errors") is None, body
    items = body["data"]["network"][query_field]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == expected


@pytest.mark.parametrize(
    ("manager_results", "query", "query_field", "expected"),
    [
        pytest.param(
            {("network", "switch_manager", "get_port_profiles"): [{"_id": "pp-1", "name": "All"}]},
            '{ network { portProfile(controller: "CONTROLLER_ID", id: "pp-1") { id name } } }',
            "portProfile",
            "pp-1",
            id="port_profile_detail",
        ),
        pytest.param(
            {
                ("network", "network_manager", "list_ap_groups"): [
                    {"_id": "ag-1", "name": "Indoor", "device_macs": ["ap:01"]}
                ]
            },
            '{ network { apGroup(controller: "CONTROLLER_ID", id: "ag-1") { id name } } }',
            "apGroup",
            "ag-1",
            id="ap_group_detail",
        ),
        pytest.param(
            {("network", "usergroup_manager", "get_usergroups"): [{"_id": "ug-1", "name": "Premium"}]},
            '{ network { userGroup(controller: "CONTROLLER_ID", id: "ug-1") { id name } } }',
            "userGroup",
            "ug-1",
            id="user_group_detail",
        ),
    ],
)
@pytest.mark.asyncio
async def test_switch_config_details(tmp_path, monkeypatch, manager_results, query, query_field, expected):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, manager_results)
    body = await graphql_query(app, key, query.replace("CONTROLLER_ID", cid))
    assert body.get("errors") is None, body
    assert body["data"]["network"][query_field]["id"] == expected


@pytest.mark.parametrize(
    ("manager_results", "query", "query_field", "value_field", "expected"),
    [
        pytest.param(
            {
                ("network", "switch_manager", "get_switch_ports"): {
                    "name": "Core-Switch",
                    "model": "USW48",
                    "port_overrides": [],
                }
            },
            '{ network { switchPorts(controller: "CONTROLLER_ID", deviceMac: "sw:01") { name model } } }',
            "switchPorts",
            "model",
            "USW48",
            id="switch_ports",
        ),
        pytest.param(
            {
                ("network", "switch_manager", "get_switch_capabilities"): {
                    "name": "Core-Switch",
                    "model": "USW48",
                    "stp_version": "rstp",
                    "dot1x_portctrl_enabled": False,
                }
            },
            (
                '{ network { switchCapabilities(controller: "CONTROLLER_ID", deviceMac: "sw:01") '
                "{ name model stpVersion } } }"
            ),
            "switchCapabilities",
            "stpVersion",
            "rstp",
            id="switch_capabilities",
        ),
    ],
)
@pytest.mark.asyncio
async def test_switch_details(tmp_path, monkeypatch, manager_results, query, query_field, value_field, expected):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, manager_results)
    body = await graphql_query(app, key, query.replace("CONTROLLER_ID", cid))
    assert body.get("errors") is None, body
    sw = body["data"]["network"][query_field]
    assert sw["name"] == "Core-Switch"
    assert sw[value_field] == expected


@pytest.mark.asyncio
async def test_port_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "switch_manager", "get_port_stats"): {
                "name": "Core-Switch",
                "model": "USW48",
                "port_table": [],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ portStats(controller: "{cid}", deviceMac: "sw:01") {{
            name model
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    ps = body["data"]["network"]["portStats"]
    assert ps["name"] == "Core-Switch"


@pytest.mark.asyncio
async def test_ap_groups_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "list_ap_groups"): [
                {"_id": "ag-1", "name": "Indoor", "device_macs": ["ap:01", "ap:02"]},
                {"_id": "ag-2", "name": "Outdoor", "device_macs": ["ap:03"]},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ apGroups(controller: "{cid}", limit: 10) {{
            items {{ id name apCount }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["apGroups"]["items"]
    assert len(items) == 2
    by_name = {it["name"]: it for it in items}
    assert by_name["Indoor"]["apCount"] == 2
    assert by_name["Outdoor"]["apCount"] == 1
