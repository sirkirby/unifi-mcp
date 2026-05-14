"""Fixture e2e tests for access/doors resolvers.

# tool: access_list_doors
# tool: access_get_door
# tool: access_list_door_groups
# tool: access_get_door_status
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_access_doors_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "door_manager", "list_doors"): [
                {"id": "door1", "name": "Front", "is_locked": True},
                {"id": "door2", "name": "Back", "is_locked": False},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ doors(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["doors"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"door1", "door2"}


@pytest.mark.asyncio
async def test_access_door_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "door_manager", "list_doors"): [
                {"id": "door1", "name": "Front", "is_locked": True},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ door(controller: "{cid}", id: "door1") {{
            id name
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["access"]["door"]["id"] == "door1"
    assert body["data"]["access"]["door"]["name"] == "Front"


@pytest.mark.asyncio
async def test_access_door_groups_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "door_manager", "list_door_groups"): [
                {"id": "grp1", "name": "Main Entrance"},
                {"id": "grp2", "name": "Server Room"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ doorGroups(controller: "{cid}", limit: 10) {{
            items {{ id name }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["doorGroups"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"grp1", "grp2"}


@pytest.mark.asyncio
async def test_access_door_status(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "door_manager", "get_door_status"): {
                "door_id": "door1",
                "is_locked": True,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ doorStatus(controller: "{cid}", id: "door1") {{
            doorId
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["access"]["doorStatus"]["doorId"] == "door1"
