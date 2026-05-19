"""Tests for the optional `metadata` field on Event + SmartDetection models.

Verifies that `from_controller` / `smart_detection_from_controller` pass
through the metadata dict when present and leave it as None when absent.
"""

from unifi_core.protect.models.events import (
    from_controller,
    smart_detection_from_controller,
)


def test_event_from_controller_passes_metadata_through() -> None:
    e = from_controller({"id": "evt-1", "metadata": {"linesStatus": {"1": {}}}})
    assert e.metadata == {"linesStatus": {"1": {}}}


def test_event_from_controller_metadata_is_none_when_absent() -> None:
    e = from_controller({"id": "evt-2"})
    assert e.metadata is None


def test_smart_detection_from_controller_passes_metadata_through() -> None:
    sd = smart_detection_from_controller({"id": "sd-1", "metadata": {"weather": {"temperature": 16}}})
    assert sd.metadata == {"weather": {"temperature": 16}}


def test_smart_detection_from_controller_metadata_is_none_when_absent() -> None:
    sd = smart_detection_from_controller({"id": "sd-2"})
    assert sd.metadata is None
