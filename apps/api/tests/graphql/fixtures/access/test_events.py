"""Fixture e2e tests for access/events resolvers.

# tool: access_list_events
# tool: access_get_event
# tool: access_get_activity_summary
"""

from __future__ import annotations

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


@pytest.mark.asyncio
async def test_access_events_list(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "event_manager", "list_events"): [
                {"id": "evt1", "type": "ACCESS_GRANTED", "timestamp": 1000, "door_id": "door1"},
                {"id": "evt2", "type": "ACCESS_DENIED", "timestamp": 2000, "door_id": "door1"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ events(controller: "{cid}", limit: 10) {{
            items {{ id type }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["events"]["items"]
    assert len(items) == 2
    assert {it["id"] for it in items} == {"evt1", "evt2"}


@pytest.mark.asyncio
async def test_access_event_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "event_manager", "list_events"): [
                {"id": "evt1", "type": "ACCESS_GRANTED", "timestamp": 1000, "door_id": "door1"},
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ event(controller: "{cid}", id: "evt1") {{
            id type
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    assert body["data"]["access"]["event"]["id"] == "evt1"
    assert body["data"]["access"]["event"]["type"] == "ACCESS_GRANTED"


@pytest.mark.asyncio
async def test_access_activity_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "event_manager", "get_activity_summary"): {
                "period_start": "2024-01-01",
                "period_end": "2024-01-07",
                "total_events": 42,
                "granted_count": 38,
                "denied_count": 4,
            },
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ activitySummary(controller: "{cid}", days: 7) {{
            totalEvents grantedCount deniedCount
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    summary = body["data"]["access"]["activitySummary"]
    assert summary["totalEvents"] == 42
    assert summary["grantedCount"] == 38
    assert summary["deniedCount"] == 4


@pytest.mark.asyncio
async def test_access_events_expose_the_controller_message(tmp_path, monkeypatch):
    """The system-log rows carry a human-readable summary; the API surfaces
    must not drop it. `access.door.unlock` renders as "Access Granted (Face)",
    which is the only field that says what actually happened."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "event_manager", "list_events"): [
                {
                    "id": "evt1",
                    "type": "access.door.unlock",
                    "message": "Access Granted (Face)",
                    "timestamp": "2026-08-18T12:00:00+00:00",
                },
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ events(controller: "{cid}", limit: 10) {{
            items {{ id message }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    items = body["data"]["access"]["events"]["items"]
    assert items[0]["message"] == "Access Granted (Face)"


@pytest.mark.asyncio
async def test_access_events_project_the_real_system_log_shape(tmp_path, monkeypatch):
    """`access_list_events` returns raw controller rows, not Event models, and
    the system-log shape uses `event_type` / `published` / nested `metadata`.
    Reading `type`/`timestamp`/`door_id`/`user_id` off it yielded a row that was
    nothing but an id and a result — on GraphQL and REST, the exact bug the core
    model fix addresses."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "event_manager", "list_events"): [
                {
                    "id": "",
                    "log_key": "access.door.unlock",
                    "event_type": "access.door.unlock",
                    "message": "Access Granted (Face)",
                    "published": 1787054400000,
                    "result": "ACCESS",
                    "metadata": {
                        "actor": {"id": "person-uuid", "type": "user", "display_name": "Test Person"},
                        "door": {"id": "door-uuid", "type": "door", "display_name": "Test Door"},
                    },
                },
            ],
        },
    )
    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ events(controller: "{cid}", limit: 10) {{
            items {{ type timestamp doorId userId message result }}
        }} }}
    }}''',
    )
    assert body.get("errors") is None, body
    row = body["data"]["access"]["events"]["items"][0]
    assert row["type"] == "access.door.unlock", row
    assert row["timestamp"] is not None, "every system-log row was timeless"
    assert row["doorId"] == "door-uuid", row
    assert row["userId"] == "person-uuid", row
    assert row["message"] == "Access Granted (Face)"
    assert row["result"] == "ACCESS"
