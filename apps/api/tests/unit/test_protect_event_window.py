"""The Protect event-list actions parse their window and apply its documented defaults."""

from datetime import datetime, timedelta, timezone

import pytest
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS

TOOLS = ("protect_list_events", "protect_list_smart_detections")


@pytest.mark.parametrize("tool", TOOLS)
def test_iso_bounds_become_utc_datetimes(tool: str) -> None:
    _, kwargs = DISPATCH_ARG_TRANSLATORS[tool]({"start": "2026-03-17T00:00:00Z", "end": "2026-03-17T06:00:00"})

    assert kwargs["start"] == datetime(2026, 3, 17, tzinfo=timezone.utc)
    # A naive timestamp is read as UTC.
    assert kwargs["end"] == datetime(2026, 3, 17, 6, tzinfo=timezone.utc)


@pytest.mark.parametrize("tool", TOOLS)
def test_omitted_bounds_default_to_the_last_24_hours(tool: str) -> None:
    before = datetime.now(timezone.utc)
    _, kwargs = DISPATCH_ARG_TRANSLATORS[tool]({"limit": 200})

    assert before <= kwargs["end"] <= datetime.now(timezone.utc)
    assert kwargs["start"] == kwargs["end"] - timedelta(hours=24)
    assert kwargs["limit"] == 200


@pytest.mark.parametrize("tool", TOOLS)
def test_start_alone_still_sends_an_end(tool: str) -> None:
    """The NVR rejects a limit above 100 unless both ends of the range are sent."""
    _, kwargs = DISPATCH_ARG_TRANSLATORS[tool]({"start": "2026-03-17T00:00:00Z", "limit": 150})

    assert kwargs["start"] == datetime(2026, 3, 17, tzinfo=timezone.utc)
    assert isinstance(kwargs["end"], datetime)


@pytest.mark.parametrize("tool", TOOLS)
def test_end_alone_starts_24_hours_earlier(tool: str) -> None:
    _, kwargs = DISPATCH_ARG_TRANSLATORS[tool]({"end": "2026-03-17T12:00:00+00:00"})

    assert kwargs["start"] == datetime(2026, 3, 16, 12, tzinfo=timezone.utc)


def test_an_unparseable_bound_is_refused() -> None:
    with pytest.raises(ValueError):
        DISPATCH_ARG_TRANSLATORS["protect_list_events"]({"start": "yesterday"})
