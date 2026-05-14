"""Fixture e2e tests for network/clients resolvers.

# tool: unifi_list_clients
# tool: unifi_get_client_details
# tool: unifi_list_blocked_clients
# tool: unifi_lookup_by_ip
# tool: unifi_get_client_sessions
# tool: unifi_get_client_wifi_details
# tool: unifi_list_client_groups
# tool: unifi_get_client_group_details
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_clients_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "client_manager", "get_clients"): [
                {"mac": "aa:01", "hostname": "alpha", "is_wired": True},
                {"mac": "aa:02", "hostname": "beta", "is_wired": False},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ clients(controller: "{cid}", limit: 10) {{
            items {{ mac hostname }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["clients"]["items"]
    assert len(items) == 2
    macs = {it["mac"] for it in items}
    assert macs == {"aa:01", "aa:02"}


@pytest.mark.asyncio
async def test_client_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "client_manager", "get_clients"): [
                {"mac": "aa:01", "hostname": "alpha"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ client(controller: "{cid}", mac: "aa:01") {{
            mac hostname
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["client"]["mac"] == "aa:01"


@pytest.mark.asyncio
async def test_blocked_clients_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "client_manager", "get_blocked_clients"): [
                {"mac": "bb:01", "hostname": "blocked-one"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ blockedClients(controller: "{cid}", limit: 10) {{
            items {{ mac hostname }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["blockedClients"]["items"]
    assert len(items) == 1
    assert items[0]["mac"] == "bb:01"


@pytest.mark.asyncio
async def test_lookup_by_ip(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "client_manager", "get_client_by_ip"): {
                "mac": "aa:01",
                "ip": "10.0.0.5",
                "hostname": "alpha",
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ clientByIp(controller: "{cid}", ip: "10.0.0.5") {{
            mac ip hostname
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["clientByIp"]["ip"] == "10.0.0.5"


@pytest.mark.asyncio
async def test_client_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_client_sessions"): [
                {"mac": "aa:01", "assoc_time": 1000},
                {"mac": "aa:01", "assoc_time": 2000},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ clientSessions(controller: "{cid}", mac: "aa:01", limit: 10) {{
            items {{ mac }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["clientSessions"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_client_wifi_details(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_client_wifi_details"): {
                "mac": "aa:01",
                "signal": -65,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ clientWifiDetails(controller: "{cid}", mac: "aa:01") {{
            mac
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["clientWifiDetails"]["mac"] == "aa:01"


@pytest.mark.asyncio
async def test_client_groups_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "client_group_manager", "get_client_groups"): [
                {"_id": "cg-1", "name": "Group A"},
                {"_id": "cg-2", "name": "Group B"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ clientGroups(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["clientGroups"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_client_group_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "client_group_manager", "get_client_groups"): [
                {"_id": "cg-1", "name": "Group A"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ clientGroup(controller: "{cid}", id: "cg-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["clientGroup"]["id"] == "cg-1"
