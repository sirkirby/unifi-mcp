"""Fixture e2e tests for network/vpn resolvers.

# tool: unifi_list_vpn_clients
# tool: unifi_get_vpn_client_details
# tool: unifi_list_vpn_servers
# tool: unifi_get_vpn_server_details
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_vpn_clients_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "vpn_manager", "get_vpn_clients"): [
                {"_id": "vc-1", "name": "Home-VPN"},
                {"_id": "vc-2", "name": "Work-VPN"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ vpnClients(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["vpnClients"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"Home-VPN", "Work-VPN"}


@pytest.mark.parametrize(
    ("manager_results", "query", "query_field", "expected"),
    [
        pytest.param(
            {("network", "vpn_manager", "get_vpn_clients"): [{"_id": "vc-1", "name": "Home-VPN"}]},
            '{ network { vpnClient(controller: "CONTROLLER_ID", id: "vc-1") { id name } } }',
            "vpnClient",
            "vc-1",
            id="vpn_client_detail",
        ),
        pytest.param(
            {("network", "vpn_manager", "get_vpn_servers"): [{"_id": "vs-1", "name": "Main-Server"}]},
            '{ network { vpnServer(controller: "CONTROLLER_ID", id: "vs-1") { id name } } }',
            "vpnServer",
            "vs-1",
            id="vpn_server_detail",
        ),
    ],
)
@pytest.mark.asyncio
async def test_vpn_details(tmp_path, monkeypatch, manager_results, query, query_field, expected):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, manager_results)
    body = await graphql_query(app, key, query.replace("CONTROLLER_ID", cid))
    assert body.get("errors") is None, body
    assert body["data"]["network"][query_field]["id"] == expected


@pytest.mark.asyncio
async def test_vpn_servers_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "vpn_manager", "get_vpn_servers"): [
                {"_id": "vs-1", "name": "Main-Server"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ vpnServers(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["vpnServers"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Main-Server"
