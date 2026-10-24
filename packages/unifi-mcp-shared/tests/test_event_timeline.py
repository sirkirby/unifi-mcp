"""Tests for shared event timeline utilities."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from unifi_core.event_timeline import NormalizedEvent, filter_by_area, merge_timelines


class TestNormalizedEvent:
    """Test the normalized event data model."""

    @pytest.mark.parametrize(
        ("kwargs", "has_location"),
        [
            (
                {
                    "product": "network",
                    "event_type": "client_connect",
                    "summary": "New client connected",
                },
                False,
            ),
            (
                {
                    "product": "access",
                    "event_type": "badge_scan",
                    "summary": "Badge scan at Main Entrance",
                    "raw": {},
                    "location_id": "loc_123",
                    "location_name": "Home Lab",
                },
                True,
            ),
        ],
    )
    def test_normalized_event_to_dict(self, kwargs, has_location):
        event = NormalizedEvent(timestamp=datetime(2026, 3, 24, 2, 47, 0, tzinfo=timezone.utc), **kwargs)
        assert event.product == kwargs["product"]
        assert event.event_type == kwargs["event_type"]
        d = event.to_dict()
        assert "normalized_fields" in d
        if has_location:
            assert d["location_id"] == "loc_123"
            assert d["location_name"] == "Home Lab"
        else:
            assert event.location_id is None
            assert event.location_name is None
            assert "location_id" not in d
            assert "location_name" not in d


class TestMergeTimelines:
    """Test merging multiple event lists into a sorted timeline."""

    @pytest.mark.parametrize(
        ("hours_lists", "expected_products"),
        [
            ([], []),
            ([[(2, "network")]], ["network"]),
            ([[(3, "protect")], [(1, "network")]], ["network", "protect"]),
            ([[(1, "network")], [(2, "protect")]], ["network", "protect"]),
        ],
    )
    def test_merge_timelines(self, hours_lists, expected_products):
        lists = [
            [
                NormalizedEvent(
                    timestamp=datetime(2026, 3, 24, hr, 0, tzinfo=timezone.utc),
                    product=prod,
                    event_type="a",
                    summary="a",
                    raw={},
                )
                for hr, prod in sublist
            ]
            for sublist in hours_lists
        ]
        result = merge_timelines(lists)
        assert [e.product for e in result] == expected_products
        if len(result) > 1:
            assert result[0].timestamp < result[1].timestamp


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
