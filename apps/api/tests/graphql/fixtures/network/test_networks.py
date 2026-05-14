"""Fixture e2e tests for network/networks resolvers.

# tool: unifi_list_networks
# tool: unifi_get_network_details
# tool: unifi_get_network_health
# tool: unifi_get_network_stats
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_networks_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_networks"): [
                {"_id": "net-1", "name": "Trusted"},
                {"_id": "net-2", "name": "IoT"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ networks(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["networks"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"Trusted", "IoT"}


@pytest.mark.asyncio
async def test_network_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "network_manager", "get_networks"): [
                {"_id": "net-1", "name": "Trusted"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ networkDetail(controller: "{cid}", id: "net-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["networkDetail"]["id"] == "net-1"


@pytest.mark.asyncio
async def test_network_health(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "system_manager", "get_network_health"): [
                {"subsystem": "wan", "status": "ok"},
                {"subsystem": "wlan", "status": "ok"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ networkHealth(controller: "{cid}") {{
            subsystem status
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    health = body["data"]["network"]["networkHealth"]
    assert len(health) == 2
    subsystems = {h["subsystem"] for h in health}
    assert subsystems == {"wan", "wlan"}


@pytest.mark.asyncio
async def test_network_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "stats_manager", "get_network_stats"): [
                {"time": 1000},
                {"time": 2000},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ networkStats(controller: "{cid}") {{
            ts
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    stats = body["data"]["network"]["networkStats"]
    assert len(stats) == 2
