"""Fixture e2e tests for access/visitors resolvers.

# tool: access_list_visitors
# tool: access_get_visitor
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_access_visitors_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "visitor_manager", "list_visitors"): [
                {"id": "vis1", "name": "Alice Guest", "status": "active"},
                {"id": "vis2", "name": "Bob Guest", "status": "expired"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ visitors(controller: "{cid}", limit: 10) {{
            items {{ id name status }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["visitors"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"vis1", "vis2"}


@pytest.mark.asyncio
async def test_access_visitor_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "visitor_manager", "list_visitors"): [
                {"id": "vis1", "name": "Alice Guest", "status": "active"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ visitor(controller: "{cid}", id: "vis1") {{
            id name status
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["access"]["visitor"]["id"] == "vis1"
    assert body["data"]["access"]["visitor"]["name"] == "Alice Guest"
