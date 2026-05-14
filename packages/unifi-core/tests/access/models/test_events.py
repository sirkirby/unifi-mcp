"""Unit tests for the Access Event and ActivitySummary read-only domain models."""

from __future__ import annotations

import datetime

from unifi_core.access.models.events import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    ActivitySummary,
    Event,
    activity_summary_from_controller,
    event_from_controller,
)


class TestFieldSets:
    def test_mutable_fields_is_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset(), "Events are read-only; MUTABLE_FIELDS must be empty"

    def test_read_only_covers_event_fields(self) -> None:
        for field in ("id", "type", "timestamp", "door_id", "user_id", "credential_id", "result"):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_read_only_covers_activity_summary_fields(self) -> None:
        for field in (
            "period_start",
            "period_end",
            "total_events",
            "granted_count",
            "denied_count",
            "top_users",
            "buckets",
        ):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_read_only_is_union_of_both_class_fields(self) -> None:
        expected = frozenset(Event.model_fields.keys()) | frozenset(ActivitySummary.model_fields.keys())
        assert READ_ONLY_FIELDS == expected

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"


class TestEventFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "evt-001",
            "type": "door_open",
            "timestamp": "2026-03-17T12:00:00Z",
            "door_id": "door-abc",
            "user_id": "user-xyz",
            "credential_id": "cred-111",
            "result": "granted",
        }
        e = event_from_controller(raw)
        assert e.id == "evt-001"
        assert e.type == "door_open"
        assert e.timestamp == "2026-03-17T12:00:00Z"
        assert e.door_id == "door-abc"
        assert e.user_id == "user-xyz"
        assert e.credential_id == "cred-111"
        assert e.result == "granted"

    def test_missing_fields_are_none(self) -> None:
        e = event_from_controller({})
        assert e.id is None
        assert e.type is None
        assert e.timestamp is None
        assert e.door_id is None
        assert e.user_id is None
        assert e.credential_id is None
        assert e.result is None

    def test_partial_dict(self) -> None:
        e = event_from_controller({"id": "evt-002", "type": "access_denied", "result": "denied"})
        assert e.id == "evt-002"
        assert e.type == "access_denied"
        assert e.result == "denied"
        assert e.timestamp is None
        assert e.door_id is None

    def test_timestamp_from_datetime_object(self) -> None:
        dt = datetime.datetime(2026, 4, 10, 9, 30, 0)
        e = event_from_controller({"id": "evt-003", "timestamp": dt})
        assert e.timestamp == dt.isoformat()

    def test_timestamp_from_time_key(self) -> None:
        """Falls back to 'time' key when 'timestamp' is absent."""
        e = event_from_controller({"id": "evt-004", "time": "2026-03-18T08:00:00Z"})
        assert e.timestamp == "2026-03-18T08:00:00Z"

    def test_timestamp_none(self) -> None:
        e = event_from_controller({"id": "evt-005", "timestamp": None})
        assert e.timestamp is None

    def test_from_object(self) -> None:
        """event_from_controller works with an attribute-bearing object."""

        class Obj:
            id = "evt-006"
            type = "door_close"
            timestamp = "2026-04-01T00:00:00Z"
            door_id = "door-def"
            user_id = "user-abc"
            credential_id = "cred-222"
            result = "granted"
            time = None

        e = event_from_controller(Obj())
        assert e.id == "evt-006"
        assert e.type == "door_close"
        assert e.door_id == "door-def"

    def test_model_dump_exclude_none_omits_missing(self) -> None:
        e = event_from_controller({"id": "evt-007", "type": "door_open"})
        dumped = e.model_dump(exclude_none=True)
        assert "id" in dumped
        assert "type" in dumped
        assert "timestamp" not in dumped
        assert "door_id" not in dumped
        assert "user_id" not in dumped
        assert "credential_id" not in dumped
        assert "result" not in dumped


class TestActivitySummaryFromController:
    def test_full_dict(self) -> None:
        raw = {
            "period_start": "2026-03-01T00:00:00Z",
            "period_end": "2026-03-07T23:59:59Z",
            "total_events": 100,
            "granted_count": 80,
            "denied_count": 20,
            "top_users": [{"user_id": "u1", "count": 50}],
            "buckets": [{"ts": "2026-03-01T00:00:00Z", "count": 10}],
        }
        s = activity_summary_from_controller(raw)
        assert s.period_start == "2026-03-01T00:00:00Z"
        assert s.period_end == "2026-03-07T23:59:59Z"
        assert s.total_events == 100
        assert s.granted_count == 80
        assert s.denied_count == 20
        assert s.top_users == [{"user_id": "u1", "count": 50}]
        assert s.buckets == [{"ts": "2026-03-01T00:00:00Z", "count": 10}]

    def test_missing_fields_are_none(self) -> None:
        s = activity_summary_from_controller({})
        assert s.period_start is None
        assert s.period_end is None
        assert s.total_events is None
        assert s.granted_count is None
        assert s.denied_count is None
        assert s.top_users is None
        assert s.buckets is None

    def test_since_until_fallback_keys(self) -> None:
        """Falls back to 'since'/'until' keys when canonical keys absent."""
        raw = {
            "since": "2026-03-10T00:00:00Z",
            "until": "2026-03-17T00:00:00Z",
            "total": 55,
        }
        s = activity_summary_from_controller(raw)
        assert s.period_start == "2026-03-10T00:00:00Z"
        assert s.period_end == "2026-03-17T00:00:00Z"
        assert s.total_events == 55

    def test_histogram_fallback_key(self) -> None:
        """Falls back to 'histogram' key when 'buckets' absent."""
        raw = {"histogram": [{"hour": 0, "count": 5}]}
        s = activity_summary_from_controller(raw)
        assert s.buckets == [{"hour": 0, "count": 5}]

    def test_period_start_datetime_coercion(self) -> None:
        dt = datetime.datetime(2026, 3, 1, 0, 0, 0)
        raw = {"period_start": dt, "period_end": "2026-03-07T23:59:59Z"}
        s = activity_summary_from_controller(raw)
        assert s.period_start == dt.isoformat()

    def test_top_users_dict_passthrough(self) -> None:
        raw = {"top_users": {"u1": 30, "u2": 20}}
        s = activity_summary_from_controller(raw)
        assert s.top_users == {"u1": 30, "u2": 20}

    def test_top_users_list_passthrough(self) -> None:
        raw = {"top_users": [{"id": "u1", "count": 30}]}
        s = activity_summary_from_controller(raw)
        assert s.top_users == [{"id": "u1", "count": 30}]

    def test_non_dict_raw_returns_empty_summary(self) -> None:
        """Non-dict, non-model-dump objects produce a summary with all None."""
        s = activity_summary_from_controller(None)
        assert s.period_start is None
        assert s.total_events is None

    def test_model_dump_exclude_none_omits_missing(self) -> None:
        s = activity_summary_from_controller({"total_events": 42, "granted_count": 30})
        dumped = s.model_dump(exclude_none=True)
        assert "total_events" in dumped
        assert "granted_count" in dumped
        assert "period_start" not in dumped
        assert "denied_count" not in dumped
        assert "top_users" not in dumped
        assert "buckets" not in dumped
