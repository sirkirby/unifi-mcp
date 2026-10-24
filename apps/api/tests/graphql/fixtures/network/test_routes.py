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


@pytest.mark.parametrize(
    ("manager_results", "query", "query_field", "expected"),
    [
        pytest.param(
            {("network", "routing_manager", "get_routes"): [{"_id": "rt-1", "name": "ToOffice"}]},
            '{ network { route(controller: "CONTROLLER_ID", id: "rt-1") { id name } } }',
            "route",
            "rt-1",
            id="route_detail",
        ),
        pytest.param(
            {("network", "traffic_route_manager", "get_traffic_routes"): [{"_id": "tr-1", "name": "WorkTraffic"}]},
            '{ network { trafficRoute(controller: "CONTROLLER_ID", id: "tr-1") { id name } } }',
            "trafficRoute",
            "tr-1",
            id="traffic_route_detail",
        ),
    ],
)
@pytest.mark.asyncio
async def test_route_details(tmp_path, monkeypatch, manager_results, query, query_field, expected):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, manager_results)
    body = await graphql_query(app, key, query.replace("CONTROLLER_ID", cid))
    assert body.get("errors") is None, body
    assert body["data"]["network"][query_field]["id"] == expected


@pytest.mark.parametrize(
    ("manager_results", "query", "query_field"),
    [
        pytest.param(
            {
                ("network", "routing_manager", "get_active_routes"): [
                    {"pfx": "0.0.0.0/0", "nh": "192.168.1.1"},
                    {"pfx": "10.0.0.0/8", "nh": "10.1.1.1"},
                ]
            },
            '{ network { activeRoutes(controller: "CONTROLLER_ID", limit: 10) { items { targetSubnet gateway } } } }',
            "activeRoutes",
            id="active_routes_list",
        ),
        pytest.param(
            {
                ("network", "traffic_route_manager", "get_traffic_routes"): [
                    {"_id": "tr-1", "name": "WorkTraffic"},
                    {"_id": "tr-2", "name": "GameTraffic"},
                ]
            },
            '{ network { trafficRoutes(controller: "CONTROLLER_ID", limit: 10) { items { id name } } } }',
            "trafficRoutes",
            id="traffic_routes_list",
        ),
    ],
)
@pytest.mark.asyncio
async def test_route_pages(tmp_path, monkeypatch, manager_results, query, query_field):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, manager_results)
    body = await graphql_query(app, key, query.replace("CONTROLLER_ID", cid))
    assert body.get("errors") is None, body
    items = body["data"]["network"][query_field]["items"]
    assert len(items) == 2
