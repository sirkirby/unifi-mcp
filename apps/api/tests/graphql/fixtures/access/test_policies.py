"""Fixture e2e tests for access/policies and schedules resolvers.

# tool: access_list_policies
# tool: access_get_policy
# tool: access_list_schedules
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_access_policies_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "policy_manager", "list_policies"): [
                {"id": "pol1", "name": "Office Hours", "door_ids": [], "user_group_ids": [], "enabled": True},
                {"id": "pol2", "name": "After Hours", "door_ids": [], "user_group_ids": [], "enabled": False},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ policies(controller: "{cid}", limit: 10) {{
            items {{ id name enabled }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["policies"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"pol1", "pol2"}


@pytest.mark.asyncio
async def test_access_policy_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "policy_manager", "list_policies"): [
                {"id": "pol1", "name": "Office Hours", "door_ids": [], "user_group_ids": [], "enabled": True},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ policy(controller: "{cid}", id: "pol1") {{
            id name enabled
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["access"]["policy"]["id"] == "pol1"
    assert body["data"]["access"]["policy"]["name"] == "Office Hours"


@pytest.mark.asyncio
async def test_access_schedules_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "policy_manager", "list_schedules"): [
                {"id": "sched1", "name": "Weekdays", "weekly_pattern": {}, "enabled": True},
                {"id": "sched2", "name": "Weekends", "weekly_pattern": {}, "enabled": False},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ schedules(controller: "{cid}", limit: 10) {{
            items {{ id name enabled }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["schedules"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"sched1", "sched2"}
