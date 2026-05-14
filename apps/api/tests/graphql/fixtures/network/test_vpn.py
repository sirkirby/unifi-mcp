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


@pytest.mark.asyncio
async def test_vpn_client_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "vpn_manager", "get_vpn_clients"): [
                {"_id": "vc-1", "name": "Home-VPN"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ vpnClient(controller: "{cid}", id: "vc-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["vpnClient"]["id"] == "vc-1"


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


@pytest.mark.asyncio
async def test_vpn_server_detail(tmp_path, monkeypatch):
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
        network {{ vpnServer(controller: "{cid}", id: "vs-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["vpnServer"]["id"] == "vs-1"
