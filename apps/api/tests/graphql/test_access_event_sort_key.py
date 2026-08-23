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


def test_a_full_cursor_traversal_returns_every_row_exactly_once() -> None:
    """Reviewer's live check on #549: traversing a 68-row snapshot at
    `limit=2` returned 67 rows, because one colliding pair was windowed out
    together. Page-at-a-time is the only way to catch that - a single
    `paginate()` call cannot.
    """
    from unifi_api.services.pagination import paginate

    rows = []
    for i in range(34):
        base = {
            "id": "",
            "log_key": "admin.activity",
            "event_type": "admin.activity",
            "message": f"Admin action {i}",
            "published": 1787054400000 + i,
            "result": "SUCCESS",
        }
        # Each pair shares every top-level field and differs only in nested
        # actor metadata - the shape that collided live.
        rows.append({**base, "metadata": {"user": {"id": f"user-{i}-a", "type": "user"}}})
        rows.append({**base, "metadata": {"user": {"id": f"user-{i}-b", "type": "user"}}})

    for key_fn in (gql_event_key, rest_event_key):
        seen: list[dict] = []
        cursor = None
        for _ in range(len(rows) + 1):
            page, cursor = paginate(rows, limit=2, cursor=cursor, key_fn=key_fn)
            seen.extend(page)
            if cursor is None:
                break
        assert cursor is None, "traversal did not terminate"
        assert len(seen) == len(rows), f"traversal lost {len(rows) - len(seen)} of {len(rows)} rows"
        keys = {key_fn(r) for r in rows}
        assert len(keys) == len(rows), "distinct rows share an ordering key"
