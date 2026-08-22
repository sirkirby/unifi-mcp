"""Both API surfaces must order Access events by the same canonical key.

`paginate()` windows with a strict `(ts, id) < (last_ts, last_id)`. The two
`_event_key` helpers read `raw["timestamp"]` and `raw["id"]`, neither of which
a system-log row has — it carries `published` (epoch ms) and `id: ""`. Every
row therefore keyed to `(0, "")`: page 2 came back empty on GraphQL, and on
REST a bare `0` sitting next to a string raised TypeError inside `sorted()`.
"""

from __future__ import annotations

from unifi_api.graphql.resolvers.access import _event_key as gql_event_key
from unifi_api.routes.resources.access.events import _event_key as rest_event_key

SYSTEM_LOG_ROW = {
    "id": "",
    "log_key": "access.door.unlock",
    "event_type": "access.door.unlock",
    "message": "Access Granted (Face)",
    "published": 1787054400000,
    "result": "ACCESS",
}


def test_both_surfaces_agree_on_the_key() -> None:
    assert gql_event_key(SYSTEM_LOG_ROW) == rest_event_key(SYSTEM_LOG_ROW)


def test_a_system_log_row_does_not_key_to_zero() -> None:
    """(0, "") for every row is what emptied page 2."""
    assert gql_event_key(SYSTEM_LOG_ROW) != (0, "")


def test_distinct_rows_get_distinct_keys_on_both_surfaces() -> None:
    other = {**SYSTEM_LOG_ROW, "message": "Door status - Opened", "log_key": "access.dps.status.update"}
    assert gql_event_key(SYSTEM_LOG_ROW) != gql_event_key(other)
    assert rest_event_key(SYSTEM_LOG_ROW) != rest_event_key(other)


def test_mixed_shapes_sort_without_raising() -> None:
    """A string timestamp meeting the `0` default is the TypeError case."""
    rows = [SYSTEM_LOG_ROW, {"id": "evt-2"}, {"id": "evt-3", "timestamp": "2026-08-18T12:00:00Z"}]
    assert len(sorted(rows, key=gql_event_key)) == 3
    assert len(sorted(rows, key=rest_event_key)) == 3


def test_cursor_windowing_advances_past_a_page_of_system_log_rows() -> None:
    """The end-to-end symptom: with identical keys nothing is strictly less
    than the cursor, so the second page is empty."""
    from unifi_api.services.pagination import paginate

    rows = [{**SYSTEM_LOG_ROW, "published": 1787054400000 + i, "message": f"row {i}"} for i in range(5)]
    page1, cursor = paginate(rows, limit=2, cursor=None, key_fn=gql_event_key)
    assert len(page1) == 2 and cursor is not None
    page2, _ = paginate(rows, limit=2, cursor=cursor, key_fn=gql_event_key)
    assert len(page2) == 2, "page 2 is empty — every row shares a cursor key"
    assert {r["message"] for r in page1}.isdisjoint({r["message"] for r in page2})
