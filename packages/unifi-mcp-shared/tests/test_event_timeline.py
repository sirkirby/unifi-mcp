"""Tests for shared event timeline utilities."""

from __future__ import annotations

from datetime import datetime, timezone

from unifi_core.event_timeline import NormalizedEvent, filter_by_area, merge_timelines


class TestNormalizedEvent:
    """Test the normalized event data model."""

    def test_create_event(self):
        event = NormalizedEvent(
            timestamp=datetime(2026, 3, 24, 2, 47, 0, tzinfo=timezone.utc),
            product="protect",
            event_type="motion",
            summary="Motion detected at Front Door Camera",
            raw={"camera_id": "abc123"},
        )
        assert event.product == "protect"
        assert event.event_type == "motion"
        assert event.location_id is None
        assert event.location_name is None

    def test_to_dict_excludes_none_location(self):
        event = NormalizedEvent(
            timestamp=datetime(2026, 3, 24, 2, 47, 0, tzinfo=timezone.utc),
            product="network",
            event_type="client_connect",
            summary="New client connected",
        )
        d = event.to_dict()
        assert "location_id" not in d
        assert "location_name" not in d
        assert "normalized_fields" in d

    def test_to_dict_includes_location_when_present(self):
        event = NormalizedEvent(
            timestamp=datetime(2026, 3, 24, 2, 47, 0, tzinfo=timezone.utc),
            product="access",
            event_type="badge_scan",
            summary="Badge scan at Main Entrance",
            raw={},
            location_id="loc_123",
            location_name="Home Lab",
        )
        d = event.to_dict()
        assert d["location_id"] == "loc_123"
        assert d["location_name"] == "Home Lab"


class TestMergeTimelines:
    """Test merging multiple event lists into a sorted timeline."""

    def test_merge_empty(self):
        assert merge_timelines([]) == []

    def test_merge_single_list(self):
        events = [
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 2, 0, tzinfo=timezone.utc),
                product="network",
                event_type="a",
                summary="a",
                raw={},
            ),
        ]
        result = merge_timelines([events])
        assert len(result) == 1

    def test_merge_sorts_by_timestamp(self):
        early = NormalizedEvent(
            timestamp=datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc),
            product="network",
            event_type="a",
            summary="a",
            raw={},
        )
        late = NormalizedEvent(
            timestamp=datetime(2026, 3, 24, 3, 0, tzinfo=timezone.utc),
            product="protect",
            event_type="b",
            summary="b",
            raw={},
        )
        result = merge_timelines([[late], [early]])
        assert result[0].timestamp < result[1].timestamp

    def test_merge_multiple_products(self):
        events_a = [
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc),
                product="network",
                event_type="a",
                summary="a",
                raw={},
            ),
        ]
        events_b = [
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 2, 0, tzinfo=timezone.utc),
                product="protect",
                event_type="b",
                summary="b",
                raw={},
            ),
        ]
        result = merge_timelines([events_a, events_b])
        assert len(result) == 2
        assert result[0].product == "network"
        assert result[1].product == "protect"


class TestFilterByArea:
    """Test area_hint filtering."""

    def test_no_hint_returns_all(self):
        events = [
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc),
                product="network",
                event_type="a",
                summary="Front Door AP",
                raw={},
                area_names=["Front Door AP"],
            ),
        ]
        assert filter_by_area(events, area_hint=None) == events

    def test_case_insensitive_substring_match(self):
        match = NormalizedEvent(
            timestamp=datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc),
            product="protect",
            event_type="motion",
            summary="Motion at front door",
            raw={},
            area_names=["Front Door Camera"],
        )
        no_match = NormalizedEvent(
            timestamp=datetime(2026, 3, 24, 2, 0, tzinfo=timezone.utc),
            product="network",
            event_type="connect",
            summary="Garage AP",
            raw={},
            area_names=["Garage AP"],
        )
        result = filter_by_area([match, no_match], area_hint="front door")
        assert len(result) == 1
        assert result[0] is match
