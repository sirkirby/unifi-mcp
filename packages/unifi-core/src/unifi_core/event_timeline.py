"""Shared event timeline utilities.

Provides normalized event dataclasses and merge/sort/filter utilities
used by both single-product local timelines and the cross-product
relay-level timeline tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NormalizedEvent:
    """A single event normalized across products.

    All products (Network, Protect, Access) map their raw events to this
    common structure. The ``raw`` field preserves the original data.
    """

    timestamp: datetime
    product: str  # "network", "protect", "access"
    event_type: str  # "motion", "client_connect", "badge_scan", etc.
    summary: str  # Human-readable one-line description
    normalized_fields: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    # Location context (present in relay mode, absent in local/stdio)
    location_id: str | None = None
    location_name: str | None = None

    # Area names associated with this event (AP name, camera name, door name)
    # Used for area_hint filtering
    area_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for tool response, omitting None location fields."""
        d: dict[str, Any] = {
            "timestamp": self.timestamp.isoformat(),
            "product": self.product,
            "event_type": self.event_type,
            "summary": self.summary,
            "normalized_fields": self.normalized_fields,
            "raw": self.raw,
        }
        if self.location_id is not None:
            d["location_id"] = self.location_id
        if self.location_name is not None:
            d["location_name"] = self.location_name
        return d


def merge_timelines(event_lists: list[list[NormalizedEvent]]) -> list[NormalizedEvent]:
    """Merge multiple event lists into a single time-sorted timeline.

    Args:
        event_lists: List of event lists (one per product or location).

    Returns:
        Flat list sorted by timestamp (ascending).
    """
    all_events: list[NormalizedEvent] = []
    for events in event_lists:
        all_events.extend(events)
    all_events.sort(key=lambda e: e.timestamp)
    return all_events


def filter_by_area(
    events: list[NormalizedEvent],
    *,
    area_hint: str | None,
) -> list[NormalizedEvent]:
    """Filter events by area_hint (case-insensitive substring match).

    Matches against the event's ``area_names`` list. If any area name
    contains the hint as a substring, the event is included.

    Args:
        events: Events to filter.
        area_hint: Substring to match. None means no filtering.

    Returns:
        Filtered event list (original order preserved).
    """
    if not area_hint:
        return events

    hint_lower = area_hint.lower()
    return [e for e in events if any(hint_lower in name.lower() for name in e.area_names)]
