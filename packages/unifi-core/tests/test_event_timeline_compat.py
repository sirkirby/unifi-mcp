"""Legacy timeline shape projected from incident evidence records."""

from __future__ import annotations

from datetime import datetime, timezone

from unifi_core.event_timeline import NormalizedEvent, merge_timelines, normalized_event_from_record
from unifi_core.incident_evidence import TimeWindow
from unifi_core.protect.incident_evidence import normalize_protect_records, protect_events_context

UTC = timezone.utc
WINDOW = TimeWindow.from_datetimes(datetime(2026, 8, 8, 12, tzinfo=UTC), datetime(2026, 8, 8, 13, tzinfo=UTC))


def _records():
    context = protect_events_context(
        requested_window=WINDOW,
        collected_at=datetime(2026, 8, 8, 13, 5, tzinfo=UTC),
        start="2026-08-08T12:00:00Z",
        end="2026-08-08T13:00:00Z",
        location_id="loc-fixture-1",
    )
    raw = [
        {"id": "p1", "type": "motion", "camera": "cam-fixture-000a", "start": "2026-08-08T12:10:00+00:00"},
        {"id": "p2", "type": "ring", "camera": "cam-fixture-000a"},
    ]
    return normalize_protect_records(raw, context).records


def test_timed_records_project_to_normalized_events() -> None:
    event = normalized_event_from_record(_records()[0], location_name="fixture-site")
    assert isinstance(event, NormalizedEvent)
    assert event.timestamp == datetime(2026, 8, 8, 12, 10, tzinfo=UTC)
    assert event.product == "protect"
    assert event.event_type == "motion"
    assert event.location_id == "loc-fixture-1"
    assert event.normalized_fields == {"evidence_id": "protect.events:str:p1", "time_status": "in_window"}
    assert merge_timelines([[event]]) == [event]


def test_untimed_records_are_not_given_a_substitute_time() -> None:
    assert normalized_event_from_record(_records()[1]) is None
