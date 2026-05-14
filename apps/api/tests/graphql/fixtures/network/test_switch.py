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


@pytest.mark.asyncio
async def test_port_profiles_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "switch_manager", "get_port_profiles"): [
                {"_id": "pp-1", "name": "All", "poe_mode": "auto"},
                {"_id": "pp-2", "name": "Disabled", "poe_mode": "off"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ portProfiles(controller: "{cid}", limit: 10) {{
            items {{ id name poeMode }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["portProfiles"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"All", "Disabled"}


@pytest.mark.asyncio
async def test_port_profile_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "switch_manager", "get_port_profiles"): [
                {"_id": "pp-1", "name": "All"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ portProfile(controller: "{cid}", id: "pp-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["portProfile"]["id"] == "pp-1"


@pytest.mark.asyncio
async def test_switch_ports(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "switch_manager", "get_switch_ports"): {
                "name": "Core-Switch",
                "model": "USW48",
                "port_overrides": [],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ switchPorts(controller: "{cid}", deviceMac: "sw:01") {{
            name model
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    sw = body["data"]["network"]["switchPorts"]
    assert sw["name"] == "Core-Switch"
    assert sw["model"] == "USW48"


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
async def test_switch_capabilities(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "switch_manager", "get_switch_capabilities"): {
                "name": "Core-Switch",
                "model": "USW48",
                "stp_version": "rstp",
                "dot1x_portctrl_enabled": False,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ switchCapabilities(controller: "{cid}", deviceMac: "sw:01") {{
            name model stpVersion
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    caps = body["data"]["network"]["switchCapabilities"]
    assert caps["name"] == "Core-Switch"
    assert caps["stpVersion"] == "rstp"


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


@pytest.mark.asyncio
async def test_ap_group_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "list_ap_groups"): [
                {"_id": "ag-1", "name": "Indoor", "device_macs": ["ap:01"]},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ apGroup(controller: "{cid}", id: "ag-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["apGroup"]["id"] == "ag-1"


@pytest.mark.asyncio
async def test_user_groups_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "usergroup_manager", "get_usergroups"): [
                {"_id": "ug-1", "name": "Premium", "qos_rate_max_down": 20000},
                {"_id": "ug-2", "name": "Standard", "qos_rate_max_down": 5000},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ userGroups(controller: "{cid}", limit: 10) {{
            items {{ id name qosRateMaxDown }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["userGroups"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"Premium", "Standard"}


@pytest.mark.asyncio
async def test_user_group_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "usergroup_manager", "get_usergroups"): [
                {"_id": "ug-1", "name": "Premium"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ userGroup(controller: "{cid}", id: "ug-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["userGroup"]["id"] == "ug-1"
