"""Tests for the optional `metadata` field on Event + SmartDetection models.

Verifies that `from_controller` / `smart_detection_from_controller` pass
through the metadata dict when present and leave it as None when absent.
"""

import pytest
from unifi_core.protect.models.events import (
    from_controller,
    smart_detection_from_controller,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"id": "evt-1", "metadata": {"linesStatus": {"1": {}}}}, {"linesStatus": {"1": {}}}),
        ({"id": "evt-2"}, None),
    ],
    ids=["present", "absent"],
)
def test_event_from_controller_metadata(raw: dict, expected: dict | None) -> None:
    assert from_controller(raw).metadata == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"id": "sd-1", "metadata": {"weather": {"temperature": 16}}}, {"weather": {"temperature": 16}}),
        ({"id": "sd-2"}, None),
    ],
    ids=["present", "absent"],
)
def test_smart_detection_from_controller_metadata(raw: dict, expected: dict | None) -> None:
    assert smart_detection_from_controller(raw).metadata == expected
