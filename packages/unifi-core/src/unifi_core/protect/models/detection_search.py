"""Shared models for the UniFi Protect detection-search filter vocabulary.

The ``detection-search/labels`` endpoint returns the legal filter values the
"Find Anything" panel offers, grouped by category (colors, vehicleTypes,
smartDetectTypes, eventTypes, groupType, devices, doorAccess, ...). Each group
is a list of ``{label, value}`` items where ``value`` is the ``key:value``
string passed back to ``detection-search`` via the repeated ``labels`` query
param (e.g. ``vehicleType:truck``).

Detection *results* reuse the existing event models (``SmartDetection`` /
``smart_detection_from_controller`` in :mod:`unifi_core.protect.models.events`);
only the filter vocabulary needs a dedicated model.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DetectionSearchLabelValue(BaseModel):
    """A single selectable filter value from the detection-search vocabulary."""

    label: Optional[str] = Field(
        default=None, description="Human-readable filter label", json_schema_extra={"mutable": False}
    )
    value: Optional[str] = Field(
        default=None,
        description="Filter token in 'key:value' form (e.g. vehicleType:truck)",
        json_schema_extra={"mutable": False},
    )


class DetectionSearchLabels(BaseModel):
    """Canonical detection-search filter vocabulary, grouped by category."""

    colors: list[DetectionSearchLabelValue] = Field(
        default_factory=list, description="Vehicle/object color filters", json_schema_extra={"mutable": False}
    )
    vehicle_types: list[DetectionSearchLabelValue] = Field(
        default_factory=list, description="Vehicle type filters", json_schema_extra={"mutable": False}
    )
    smart_detect_types: list[DetectionSearchLabelValue] = Field(
        default_factory=list, description="Smart-detection type filters", json_schema_extra={"mutable": False}
    )
    event_types: list[DetectionSearchLabelValue] = Field(
        default_factory=list, description="Event type filters", json_schema_extra={"mutable": False}
    )
    group_type: list[DetectionSearchLabelValue] = Field(
        default_factory=list, description="Recognition group type filters", json_schema_extra={"mutable": False}
    )
    devices: list[DetectionSearchLabelValue] = Field(
        default_factory=list, description="Camera/device filters", json_schema_extra={"mutable": False}
    )
    door_access: list[DetectionSearchLabelValue] = Field(
        default_factory=list, description="Door access filters", json_schema_extra={"mutable": False}
    )


# Deliberately a local copy of the trivial dict/attr accessor (the event
# manager has its own). Keeping it here avoids a cross-module import from a
# manager into a model for three lines, and lets the model stay
# self-contained. The two copies are intentionally allowed to drift if their
# needs differ (e.g. None-handling).
def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _label_values(raw: Any, *keys: str) -> list[DetectionSearchLabelValue]:
    """Coalesce a controller group (first matching key) into label/value items."""
    group: Any = None
    for key in keys:
        candidate = _get(raw, key)
        if candidate is not None:
            group = candidate
            break

    if not isinstance(group, list):
        return []

    items: list[DetectionSearchLabelValue] = []
    for entry in group:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label")
        value = entry.get("value")
        # Some firmware returns the usable prefix:value token in "label" while
        # "value" contains only the suffix. Expose a value callers can pass
        # directly back to detection-search.
        if isinstance(label, str) and ":" in label and not (isinstance(value, str) and ":" in value):
            value = label
        items.append(DetectionSearchLabelValue(label=label, value=value))
    return items


def from_controller(raw: Any) -> DetectionSearchLabels:
    """Build DetectionSearchLabels from a Protect detection-search/labels response."""
    if not isinstance(raw, dict):
        raw = {}

    return DetectionSearchLabels(
        colors=_label_values(raw, "colors"),
        vehicle_types=_label_values(raw, "vehicle_types", "vehicleTypes"),
        smart_detect_types=_label_values(raw, "smart_detect_types", "smartDetectTypes"),
        event_types=_label_values(raw, "event_types", "eventTypes"),
        group_type=_label_values(raw, "group_type", "groupType"),
        devices=_label_values(raw, "devices"),
        door_access=_label_values(raw, "door_access", "doorAccess"),
    )
