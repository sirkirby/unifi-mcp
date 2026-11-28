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
            ("access", "system_manager", "list_all_users"): [
                {"unique_id": "user1", "full_name": "Alice"},
                {"unique_id": "user2", "full_name": "Bob"},
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
    assert {it["id"] for it in items} == {"user1", "user2"}


@pytest.mark.asyncio
async def test_access_users_cursor_visits_every_user_once(tmp_path, monkeypatch):
    """Users page on unique_id, the same key as the REST route, one user per page."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    rows = [{"unique_id": f"user{i}", "full_name": f"User {i}"} for i in (3, 1, 2)]
    stub_managers(monkeypatch, {("access", "system_manager", "list_all_users"): rows})

    seen: list[str] = []
    cursor = None
    for _ in range(len(rows) + 1):
        cursor_arg = f', cursor: "{cursor}"' if cursor else ""
        body = await graphql_query(
            app,
            key,
            f'''{{
            access {{ users(controller: "{cid}", limit: 1{cursor_arg}) {{
                items {{ id }}
                nextCursor
            }} }}
        }}''',
        )
        assert body.get("errors") is None, body
        page = body["data"]["access"]["users"]
        seen.extend(item["id"] for item in page["items"])
        cursor = page["nextCursor"]
        if cursor is None:
            break

    # Descending unique_id, the order paginate gives the REST route too.
    assert seen == ["user3", "user2", "user1"]
