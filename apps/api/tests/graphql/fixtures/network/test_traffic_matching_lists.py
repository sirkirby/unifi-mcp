"""Fixture e2e tests for network/traffic_matching_lists resolvers.

# tool: unifi_list_traffic_matching_lists
# tool: unifi_get_traffic_matching_list
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import (
    bootstrap,
    graphql_query,
    stub_managers,
)


@pytest.mark.asyncio
async def test_traffic_matching_lists_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "traffic_matching_list_manager", "list_all_traffic_matching_lists"): [
                {"id": "list-1", "name": "Allowed port list", "type": "PORTS", "items": []},
                {"id": "list-2", "name": "Protected IP list", "type": "IPV4_ADDRESSES", "items": []},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ trafficMatchingLists(controller: "{cid}", limit: 10) {{
            items {{ id name type }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["network"]["trafficMatchingLists"]["items"]
    assert len(items) == 2
    assert {i["name"] for i in items} == {"Allowed port list", "Protected IP list"}


@pytest.mark.asyncio
async def test_traffic_matching_list_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "traffic_matching_list_manager", "get_traffic_matching_list"): {
                "id": "list-1",
                "name": "Allowed port list",
                "type": "PORTS",
                "items": [{"type": "PORT_NUMBER", "value": 443}],
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        network {{ trafficMatchingList(controller: "{cid}", id: "list-1") {{
            id name items
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    detail = body["data"]["network"]["trafficMatchingList"]
    assert detail["id"] == "list-1"
    assert detail["items"] == [{"type": "PORT_NUMBER", "value": 443}]
