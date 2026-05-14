"""Fixture e2e tests for network/routes resolvers.

# tool: unifi_list_routes
# tool: unifi_get_route_details
# tool: unifi_list_active_routes
# tool: unifi_list_traffic_routes
# tool: unifi_get_traffic_route_details
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_routes_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "routing_manager", "get_routes"): [
                {"_id": "rt-1", "name": "ToOffice", "network": "192.168.10.0/24"},
                {"_id": "rt-2", "name": "ToCloud", "network": "10.10.0.0/16"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ routes(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["routes"]["items"]
    assert len(items) == 2
    names = {it["name"] for it in items}
    assert names == {"ToOffice", "ToCloud"}


@pytest.mark.asyncio
async def test_route_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "routing_manager", "get_routes"): [
                {"_id": "rt-1", "name": "ToOffice"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ route(controller: "{cid}", id: "rt-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["route"]["id"] == "rt-1"


@pytest.mark.asyncio
async def test_active_routes_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "routing_manager", "get_active_routes"): [
                {"pfx": "0.0.0.0/0", "nh": "192.168.1.1"},
                {"pfx": "10.0.0.0/8", "nh": "10.1.1.1"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ activeRoutes(controller: "{cid}", limit: 10) {{
            items {{ targetSubnet gateway }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["activeRoutes"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_traffic_routes_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "traffic_route_manager", "get_traffic_routes"): [
                {"_id": "tr-1", "name": "WorkTraffic"},
                {"_id": "tr-2", "name": "GameTraffic"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ trafficRoutes(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["trafficRoutes"]["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_traffic_route_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "traffic_route_manager", "get_traffic_routes"): [
                {"_id": "tr-1", "name": "WorkTraffic"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ trafficRoute(controller: "{cid}", id: "tr-1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["trafficRoute"]["id"] == "tr-1"
