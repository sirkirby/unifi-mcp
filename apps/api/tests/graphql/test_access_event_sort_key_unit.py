"""Access events need one canonical ordering identity, shared by every surface.

Both API surfaces sorted on `(raw["timestamp"], raw["id"])`. System-log rows
carry neither: the time is `published` (epoch ms) and the id is the empty
string. Every row therefore keyed to `(0, "")`, and since `paginate()` windows
with `(ts, id) < (last_ts, last_id)`, page 2 of an events query came back
empty - nothing can be strictly less than the key every row shares.
"""

from unifi_api.services.access_event_key import event_sort_key

SYSTEM_LOG_ROW = {
    "id": "",
    "log_key": "access.door.unlock",
    "event_type": "access.door.unlock",
    "message": "Access Granted (Face)",
    "published": 1787054400000,
    "result": "ACCESS",
}


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


# --- projection unwrapping ----------------------------------------------------


def test_projection_unwraps_a_raw_wrapped_row() -> None:
    """Manager output may be a wrapper exposing `.raw`. This module's `_get`
    unwraps it; the core normaliser's does not, so handing the wrapper straight
    over yielded an all-None row - silently, with no error."""
    from unifi_api.graphql.types.access.events import Event

    class Wrapped:
        def __init__(self, raw):
            self.raw = raw

    row = Wrapped({"event_type": "access.door.unlock", "message": "Access Granted (Face)", "published": 1787054400000})
    projected = Event.from_manager_output(row)
    assert projected.type == "access.door.unlock"
    assert projected.message == "Access Granted (Face)"
    assert projected.timestamp is not None


def test_projection_reads_message_without_touching_the_model_attribute() -> None:
    """The declared unifi-core floor has no `message` field on Event, so
    reading `norm.message` raises AttributeError and 500s every events
    request. The value must come from the row."""
    from unifi_api.graphql.types.access.events import Event

    assert Event.from_manager_output({"id": "e1", "message": "Access Granted (Face)"}).message == (
        "Access Granted (Face)"
    )
