"""Fixture e2e tests for access/events resolvers.

# tool: access_list_events
# tool: access_get_event
# tool: access_get_activity_summary
"""

from __future__ import annotations

import base64
import json

import pytest
from unifi_api.services.access_event_key import event_sort_key
from unifi_api.services.pagination import Cursor
from unifi_core.access.models.events import with_event_identity

from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers


def _legacy_event_key(row: dict) -> tuple:
    """The exact Access REST ordering key used before timestamp normalization."""
    return (row.get("timestamp") or row.get("time") or 0, row.get("id") or "")


def _legacy_cursor(row: dict) -> str:
    timestamp, identity = _legacy_event_key(row)
    return Cursor(last_id=identity, last_ts=timestamp).encode()


def _migration_rows(timestamp_format: str) -> tuple[list[dict], dict]:
    if timestamp_format == "published":
        raw_rows = [
            {
                "id": "",
                "log_key": "access.door.unlock",
                "event_type": "access.door.unlock",
                "message": f"row {index}",
                "published": 1787054400000 + offset,
            }
            for index, offset in enumerate((1000, 0, -1000))
        ]
        rows = [with_event_identity(row) for row in raw_rows]
    elif timestamp_format == "seconds":
        rows = [{"id": f"evt-{index}", "timestamp": 1787054400 + offset} for index, offset in enumerate((1, 0, -1))]
    elif timestamp_format == "millis":
        rows = [
            {"id": f"evt-{index}", "timestamp": 1787054400000 + offset} for index, offset in enumerate((1000, 0, -1000))
        ]
    else:
        rows = [
            {"id": "evt-0", "timestamp": "2026-08-18T12:00:01Z"},
            {"id": "evt-1", "timestamp": "2026-08-18T12:00:00Z"},
            {"id": "evt-2", "timestamp": "2026-08-18T11:59:59Z"},
        ]
    return rows, rows[1]


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
@pytest.mark.parametrize("timestamp_format", ["published", "seconds", "millis", "iso"])
async def test_access_events_resume_legacy_cursor(tmp_path, monkeypatch, timestamp_format):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    rows, legacy_target = _migration_rows(timestamp_format)
    stub_managers(
        monkeypatch,
        {("access", "event_manager", "list_events"): rows},
    )
    cursor = _legacy_cursor(legacy_target)

    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ events(controller: "{cid}", limit: 10, cursor: "{cursor}") {{
            items {{ id }}
            nextCursor
        }} }}
    }}''',
    )

    assert body.get("errors") is None, body
    returned_ids = [item["id"] for item in body["data"]["access"]["events"]["items"]]
    assert returned_ids == [rows[2]["id"]]
    assert len(returned_ids) == len(set(returned_ids))
    assert rows[0]["id"] not in returned_ids
    assert rows[1]["id"] not in returned_ids


@pytest.mark.asyncio
async def test_access_events_encoded_cursor_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    raw_rows = []
    for index in range(34):
        base = {
            "id": "",
            "log_key": "admin.activity",
            "event_type": "admin.activity",
            "message": f"Admin action {index}",
            "published": 1787054400000 + index,
        }
        raw_rows.append({**base, "metadata": {"user": {"id": f"user-{index}-a"}}})
        raw_rows.append({**base, "metadata": {"user": {"id": f"user-{index}-b"}}})
    rows = [with_event_identity(row) for row in raw_rows]
    stub_managers(
        monkeypatch,
        {("access", "event_manager", "list_events"): rows},
    )

    seen: list[str] = []
    cursor = None
    for _ in range(len(rows) + 1):
        cursor_arg = f', cursor: "{cursor}"' if cursor else ""
        body = await graphql_query(
            app,
            key,
            f'''{{
            access {{ events(controller: "{cid}", limit: 2{cursor_arg}) {{
                items {{ id }}
                nextCursor
            }} }}
        }}''',
        )
        assert body.get("errors") is None, body
        page = body["data"]["access"]["events"]
        page_ids = [item["id"] for item in page["items"]]
        assert set(page_ids).isdisjoint(seen)
        seen.extend(page_ids)
        cursor = page["nextCursor"]
        if cursor is None:
            break

        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        assert payload["resource"] == "access_events"
        assert payload["version"] == 1

    expected = [row["id"] for row in sorted(rows, key=event_sort_key, reverse=True)]
    assert cursor is None, "traversal did not terminate"
    assert seen == expected
    assert len(seen) == len(rows)
    assert len(set(seen)) == len(rows)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cursor", "expected_message"),
    [
        (Cursor(last_id="missing", last_ts="not-a-time").encode(), "timestamp is unrecoverable"),
        (Cursor(last_id="missing", last_ts=float("nan")).encode(), "last_ts must be finite"),
        (Cursor(last_id="missing", last_ts=float("inf")).encode(), "last_ts must be finite"),
        (Cursor(last_id="missing", last_ts=float("-inf")).encode(), "last_ts must be finite"),
        (
            base64.urlsafe_b64encode(
                json.dumps({"resource": "access_events", "version": 99, "last_id": "evt", "last_ts": 1}).encode()
            ).decode(),
            "unsupported Access event cursor version",
        ),
        (
            base64.urlsafe_b64encode(
                json.dumps({"resource": "network_events", "version": 1, "last_id": "evt", "last_ts": 1}).encode()
            ).decode(),
            "unknown resource format",
        ),
        ("not-base64", "invalid Access event cursor"),
    ],
)
async def test_access_events_reject_unrecoverable_cursor(
    tmp_path,
    monkeypatch,
    cursor,
    expected_message,
):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {("access", "event_manager", "list_events"): []},
    )

    body = await graphql_query(
        app,
        key,
        f'''{{
        access {{ events(controller: "{cid}", cursor: "{cursor}") {{ items {{ id }} }} }}
    }}''',
    )

    assert body["data"] is None
    assert expected_message in body["errors"][0]["message"]
    assert body["errors"][0]["extensions"]["code"] == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_access_event_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="access")
    stub_managers(
        monkeypatch,
        {
            ("access", "event_manager", "get_event"): {
                "id": "evt1",
                "type": "ACCESS_GRANTED",
                "timestamp": 1000,
                "door_id": "door1",
            },
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
