"""Access events need one canonical ordering identity, shared by every surface.

Both API surfaces sorted on `(raw["timestamp"], raw["id"])`. System-log rows
carry neither: the time is `published` (epoch ms) and the id is the empty
string. Every row therefore keyed to `(0, "")`, and since `paginate()` windows
with `(ts, id) < (last_ts, last_id)`, page 2 of an events query came back
empty - nothing can be strictly less than the key every row shares.
"""

import base64
import json
from datetime import datetime, timezone

import pytest
from unifi_api.graphql.resolvers.access import _event_key as gql_event_key
from unifi_api.routes.resources.access.events import _event_key as rest_event_key
from unifi_api.services.access_event_key import (
    InvalidAccessEventCursor,
    _decode_access_event_cursor,
    event_sort_key,
    paginate_access_events,
)
from unifi_api.services.pagination import Cursor

SYSTEM_LOG_ROW = {
    "id": "",
    "log_key": "access.door.unlock",
    "event_type": "access.door.unlock",
    "message": "Access Granted (Face)",
    "published": 1787054400000,
    "result": "ACCESS",
}


def _encode_cursor_payload(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def test_a_system_log_row_has_a_real_timestamp_not_zero() -> None:
    assert event_sort_key(SYSTEM_LOG_ROW)[0] > 0


def test_rows_order_by_published_time() -> None:
    older = {**SYSTEM_LOG_ROW, "published": 1787054391000}
    newer = {**SYSTEM_LOG_ROW, "published": 1787054490000}
    assert event_sort_key(older) < event_sort_key(newer)


def test_distinct_rows_never_share_a_key() -> None:
    """The cursor filter is strict `<`, so any two rows sharing a key make the
    next page drop both."""
    a = {**SYSTEM_LOG_ROW, "published": 1787054400000, "message": "Access Granted (Face)"}
    b = {**SYSTEM_LOG_ROW, "published": 1787054400000, "message": "Door status - Opened"}
    assert event_sort_key(a) != event_sort_key(b)


def test_sub_second_ordering_is_preserved() -> None:
    """`published` is milliseconds; truncating to whole seconds collapses
    events that happen within the same second into one key."""
    a = {**SYSTEM_LOG_ROW, "published": 1787054400100}
    b = {**SYSTEM_LOG_ROW, "published": 1787054400900}
    assert event_sort_key(a) < event_sort_key(b)


def test_a_real_id_is_used_as_the_identity_when_present() -> None:
    row = {**SYSTEM_LOG_ROW, "id": "evt-1"}
    assert event_sort_key(row)[1] == "evt-1"


def test_the_key_is_reproducible_across_calls() -> None:
    """Cursors are handed back to a later request; an unstable identity would
    silently skip or repeat rows."""
    assert event_sort_key(SYSTEM_LOG_ROW) == event_sort_key(dict(SYSTEM_LOG_ROW))


def test_legacy_websocket_rows_still_key() -> None:
    legacy = {"id": "evt-1", "type": "access.door.unlock", "timestamp": "2026-08-18T12:00:00Z"}
    ts, ident = event_sort_key(legacy)
    assert ts > 0
    assert ident == "evt-1"


def test_a_row_with_no_time_at_all_sorts_last_rather_than_raising() -> None:
    ts, ident = event_sort_key({"id": "evt-2"})
    assert ts == 0
    assert ident == "evt-2"


def test_the_key_is_comparable_across_a_mixed_list() -> None:
    """sorted() raises TypeError the moment a str meets an int in the tuple."""
    rows = [SYSTEM_LOG_ROW, {"id": "evt-2"}, {"id": "evt-3", "timestamp": "2026-08-18T12:00:00Z"}]
    assert len(sorted(rows, key=event_sort_key)) == 3


# --- scale, timezone and identity ---------------------------------------------


def test_epoch_seconds_and_millis_sort_together() -> None:
    """Legacy rows carry seconds, system-log rows carry millis. Left
    unconverted a seconds row keys ~1000x lower and sinks below every millis
    row, where the cursor window can strand it."""
    secs = {"id": "a", "timestamp": 1787054400}
    millis = {"id": "b", "published": 1787054400000}
    assert abs(event_sort_key(secs)[0] - event_sort_key(millis)[0]) < 1000


def test_a_naive_iso_string_is_read_as_utc() -> None:
    """Otherwise it is read in the host's local zone, so the key differs
    between workers and a cursor minted by one windows wrongly on another."""
    naive = {"id": "a", "timestamp": "2026-08-18T12:00:00"}
    aware = {"id": "b", "timestamp": "2026-08-18T12:00:00+00:00"}
    assert event_sort_key(naive)[0] == event_sort_key(aware)[0]


def test_same_millisecond_rows_for_different_doors_do_not_collide() -> None:
    """Two door-status rows published in the same millisecond with the same
    rendered message must not share an identity - a shared key drops both from
    the next page."""
    base = {
        "id": "",
        "log_key": "access.dps.status.update",
        "event_type": "access.dps.status.update",
        "message": "Door status - Opened",
        "published": 1787054400000,
        "result": "SUCCESS",
    }
    a = {**base, "metadata": {"door": {"id": "door-1", "type": "door"}}}
    b = {**base, "metadata": {"door": {"id": "door-2", "type": "door"}}}
    assert event_sort_key(a) != event_sort_key(b)


def test_rows_differing_only_in_nested_user_metadata_do_not_collide() -> None:
    """Two admin rows identical except for `metadata.user.id` once collided,
    so a cursor traversal dropped both.

    A hand-picked field subset cannot be proven exhaustive - any nested field
    left out of it is a collision waiting for the row that differs only there.
    """
    base = {
        "id": "",
        "log_key": "admin.activity",
        "event_type": "admin.activity",
        "message": "Admin updated a setting",
        "published": 1787054400000,
        "result": "SUCCESS",
    }
    a = {**base, "metadata": {"user": {"id": "user-1", "type": "user"}}}
    b = {**base, "metadata": {"user": {"id": "user-2", "type": "user"}}}
    assert event_sort_key(a) != event_sort_key(b)


def test_rows_differing_only_in_an_unmodelled_field_do_not_collide() -> None:
    """The same class of defect one level out: a field this module has never
    heard of still distinguishes two controller rows."""
    base = {
        "id": "",
        "log_key": "access.door.unlock",
        "event_type": "access.door.unlock",
        "message": "Access Granted (Face)",
        "published": 1787054400000,
    }
    assert event_sort_key({**base, "some_future_field": "a"}) != event_sort_key({**base, "some_future_field": "b"})


@pytest.mark.parametrize(
    ("row", "expected_millis"),
    [
        ({"id": "evt", "timestamp": 1787054400.75}, 1787054400750),
        ({"id": "evt", "timestamp": "1787054400"}, 1787054400000),
        ({"id": "evt", "timestamp": "1787054400000"}, 1787054400000),
        ({"id": "evt", "timestamp": "2026-08-18T08:00:00-04:00"}, 1787054400000),
        ({"id": "evt", "timestamp": ""}, 0),
        ({"id": "evt", "timestamp": True}, 0),
        ({"id": "evt", "timestamp": "not-a-time"}, 0),
        ({"id": "evt", "timestamp": "1787054400.5"}, 0),
        ({"id": "evt", "published": "bad", "timestamp": 1787054400}, 1787054400000),
        ({"id": "evt", "published": "", "time": "2026-08-18T12:00:00Z"}, 1787054400000),
    ],
)
def test_timestamp_normalization_and_fallbacks_match_on_both_surfaces(row, expected_millis) -> None:
    assert event_sort_key(row)[0] == expected_millis
    assert gql_event_key(row) == (expected_millis, "evt")
    assert rest_event_key(row) == (expected_millis, "evt")


def test_fractional_epoch_seconds_preserve_sub_second_ordering() -> None:
    earlier = {"id": "earlier", "timestamp": 1787054400.1}
    later = {"id": "later", "timestamp": 1787054400.9}
    assert event_sort_key(earlier)[0] == 1787054400100
    assert event_sort_key(later)[0] == 1787054400900
    assert event_sort_key(earlier) < event_sort_key(later)


def test_mapping_without_native_identity_uses_complete_row_digest() -> None:
    first = {"timestamp": 1787054400, "unknown": {"value": "first"}}
    second = {"timestamp": 1787054400, "unknown": {"value": "second"}}
    assert event_sort_key(first)[1]
    assert event_sort_key(first) != event_sort_key(second)


def test_unserializable_mapping_values_still_receive_stable_identity() -> None:
    row = {
        "timestamp": 1787054400,
        "unknown": datetime(2026, 8, 18, 12, tzinfo=timezone.utc),
    }
    assert event_sort_key(row) == event_sort_key(dict(row))
    assert event_sort_key(row)[1]


def test_raw_wrappers_match_dict_keys_on_both_surfaces() -> None:
    class Wrapped:
        def __init__(self, raw) -> None:
            self.raw = raw

    wrapped = Wrapped(SYSTEM_LOG_ROW)
    assert gql_event_key(wrapped) == gql_event_key(SYSTEM_LOG_ROW)
    assert rest_event_key(wrapped) == rest_event_key(SYSTEM_LOG_ROW)


def test_plain_objects_without_stable_identity_fail_closed() -> None:
    class UnsupportedEvent:
        timestamp = 1787054400

    with pytest.raises(ValueError, match="lacks a stable identity"):
        gql_event_key(UnsupportedEvent())
    with pytest.raises(ValueError, match="lacks a stable identity"):
        rest_event_key(UnsupportedEvent())


@pytest.mark.parametrize(
    "legacy_timestamp",
    [1787054400, 1787054400000, "2026-08-18T12:00:00Z"],
    ids=["epoch-seconds", "epoch-millis", "iso"],
)
def test_legacy_cursor_normalizes_timestamp_when_identity_is_not_in_snapshot(legacy_timestamp) -> None:
    rows = [
        {"id": "newer", "timestamp": 1787054401},
        {"id": "older", "timestamp": 1787054399},
    ]
    legacy_cursor = Cursor(last_id="event-no-longer-in-snapshot", last_ts=legacy_timestamp).encode()

    page, next_cursor = paginate_access_events(
        rows,
        limit=10,
        cursor=legacy_cursor,
        key_fn=event_sort_key,
    )

    assert [row["id"] for row in page] == ["older"]
    assert next_cursor is None


@pytest.mark.parametrize(
    ("last_id", "last_ts"),
    [
        ("event-id", "2026-08-18T12:00:00Z"),
        (42, 1787054400000),
        ("event-id", 1787054400.75),
        ("event-id", None),
    ],
    ids=["iso", "integer", "finite-float", "null"],
)
def test_legacy_cursor_accepts_exact_supported_contract(last_id, last_ts) -> None:
    encoded = _encode_cursor_payload({"last_id": last_id, "last_ts": last_ts})

    cursor, is_legacy = _decode_access_event_cursor(encoded)

    assert is_legacy is True
    assert cursor == Cursor(last_id=str(last_id), last_ts=last_ts)


def test_versioned_access_cursor_is_not_treated_as_legacy() -> None:
    encoded = _encode_cursor_payload(
        {
            "resource": "access_events",
            "version": 1,
            "last_id": "event-id",
            "last_ts": 1787054400000,
        }
    )

    cursor, is_legacy = _decode_access_event_cursor(encoded)

    assert is_legacy is False
    assert cursor == Cursor(last_id="event-id", last_ts=1787054400000)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"last_id": "event-id"}, "unknown legacy format"),
        ({"last_ts": 1787054400000}, "unknown legacy format"),
        ({"last_id": "event-id", "last_ts": 1787054400000, "extra": True}, "unknown legacy format"),
        ({"last_id": "", "last_ts": 1787054400000}, "last_id must be a stable identity"),
        ({"last_id": True, "last_ts": 1787054400000}, "last_id must be a string or integer"),
        ({"last_id": 1.5, "last_ts": 1787054400000}, "last_id must be a string or integer"),
        ({"last_id": None, "last_ts": 1787054400000}, "last_id must be a string or integer"),
        ({"last_id": ["event-id"], "last_ts": 1787054400000}, "last_id must be a string or integer"),
        ({"last_id": {"id": "event-id"}, "last_ts": 1787054400000}, "last_id must be a string or integer"),
        ({"last_id": "event-id", "last_ts": True}, "last_ts must be a string, integer, float, or null"),
        ({"last_id": "event-id", "last_ts": [1787054400000]}, "last_ts must be a string, integer, float, or null"),
        (
            {"last_id": "event-id", "last_ts": {"millis": 1787054400000}},
            "last_ts must be a string, integer, float, or null",
        ),
        ({"last_id": "event-id", "last_ts": float("nan")}, "last_ts must be finite"),
        ({"last_id": "event-id", "last_ts": float("inf")}, "last_ts must be finite"),
        ({"last_id": "event-id", "last_ts": float("-inf")}, "last_ts must be finite"),
        (
            {"resource": "network_events", "version": 1, "last_id": "event-id", "last_ts": 1787054400000},
            "unknown resource format",
        ),
        ({"version": 1, "last_id": "event-id", "last_ts": 1787054400000}, "unknown resource format"),
        (
            {"resource": "access_events", "version": 99, "last_id": "event-id", "last_ts": 1787054400000},
            "unsupported Access event cursor version",
        ),
    ],
)
def test_legacy_cursor_rejects_values_outside_supported_contract(payload, error) -> None:
    with pytest.raises(InvalidAccessEventCursor, match=error):
        _decode_access_event_cursor(_encode_cursor_payload(payload))
