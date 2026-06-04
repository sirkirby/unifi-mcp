"""Fixture e2e tests for network/traffic-flows resolver.

# tool: unifi_get_traffic_flows
"""

from __future__ import annotations

import pytest
from unifi_api.graphql.resolvers.network import _decode_flow_cursor

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_traffic_flows_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "traffic_flow_manager", "get_traffic_flows"): {
                "flows": [
                    {
                        "id": "flow-1",
                        "action": "Allow",
                        "service": "HTTPS",
                        "source": {"name": "alpha", "ip": "10.0.0.5"},
                        "destination": {"ip": "203.0.113.1", "domains": ["example.com"]},
                    },
                    {
                        "id": "flow-2",
                        "action": "Block",
                        "service": "DNS",
                        "source": {"name": "beta", "ip": "10.0.0.6"},
                        "destination": {"ip": "198.51.100.1"},
                    },
                ],
                "page_number": 0,
                "total_element_count": 2,
                "total_page_count": 1,
                "has_next": False,
                "or_more": False,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ trafficFlows(controller: "{cid}", withinHours: 24, pageSize: 100) {{
            items {{ id action service source {{ name ip }} destination {{ ip domains }} }}
            nextCursor
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    page = body["data"]["network"]["trafficFlows"]
    items = page["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"flow-1", "flow-2"}
    assert items[0]["source"]["name"] == "alpha"
    assert items[0]["destination"]["domains"] == ["example.com"]
    assert page["nextCursor"] is None


@pytest.mark.asyncio
async def test_traffic_flows_next_cursor(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "traffic_flow_manager", "get_traffic_flows"): {
                "flows": [{"id": "flow-1", "action": "Allow"}],
                "page_number": 0,
                "total_element_count": 200,
                "total_page_count": 2,
                "has_next": True,
                "or_more": True,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ trafficFlows(controller: "{cid}", pageSize: 1) {{
            items {{ id }}
            nextCursor
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    page = body["data"]["network"]["trafficFlows"]
    assert len(page["items"]) == 1
    # has_next -> a cursor is returned; it must round-trip to page 1.
    assert page["nextCursor"] is not None
    assert _decode_flow_cursor(page["nextCursor"]) == 1


@pytest.mark.asyncio
async def test_traffic_flows_partial_time_window_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "traffic_flow_manager", "get_traffic_flows"): {
                "flows": [],
                "page_number": 0,
                "total_element_count": 0,
                "total_page_count": 0,
                "has_next": False,
                "or_more": False,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ trafficFlows(controller: "{cid}", timeFrom: 1000) {{
            items {{ id }}
            nextCursor
        }} }}
    }}''',
    )
    # time_from set without time_to -> resolver raises ValueError -> GraphQL errors.
    assert body.get("errors"), body
