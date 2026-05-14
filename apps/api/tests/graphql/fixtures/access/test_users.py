"""Fixture e2e tests for access/users resolvers.

# tool: access_list_users
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_access_users_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "system_manager", "list_users"): [
                {"id": "user1", "name": "Alice"},
                {"id": "user2", "name": "Bob"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ users(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["users"]["items"]
    assert len(items) == 2
    assert {it["name"] for it in items} == {"Alice", "Bob"}
