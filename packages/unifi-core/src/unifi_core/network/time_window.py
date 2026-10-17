"""Shared parsing for report time windows.

Both the MCP tools and the API dispatch layer accept the same ``duration``
enum and optional absolute ``start``/``end`` bounds; parsing them here keeps
the two surfaces from drifting. Unknown values raise ValueError rather than
falling back to a default, because a silently substituted window returns
plausible-looking data for the wrong period.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

DURATION_HOURS: dict[str, int] = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}


def duration_hours(duration: Any) -> int:
    """Map the duration enum to hours, rejecting anything else."""
    try:
        return DURATION_HOURS[str(duration)]
    except KeyError:
        raise ValueError(
            f"Invalid duration '{duration}'. Must be one of: {', '.join(DURATION_HOURS)} "
            "(use start/end for any other window)"
        ) from None


def parse_window_bound(value: Any) -> Optional[int]:
    """Parse an ISO 8601 or epoch (seconds or milliseconds) bound to epoch milliseconds.

    ``None`` means the bound was omitted. Everything else must name a time: a
    blank string is rejected rather than treated as omitted, and an ISO
    timestamp must carry ``Z`` or a UTC offset, because a naive one would be
    read in whatever time zone the server runs in (the same rule as the
    incident-window parser in ``unifi_core.incident_collection``).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Invalid time '{value}': use ISO 8601 with a UTC offset or epoch seconds/milliseconds")
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number >= 10**12 else number * 1000
    text = str(value).strip()
    if not text:
        raise ValueError(
            "Empty time bound: omit start/end to use the duration window, or pass ISO 8601 "
            "with a UTC offset (for example 2026-08-08T12:00:00Z) or epoch seconds/milliseconds"
        )
    if text.isdigit():
        number = int(text)
        return number if number >= 10**12 else number * 1000
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(
            f"Invalid time '{value}': use ISO 8601 with a UTC offset or epoch seconds/milliseconds"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            f"Time '{value}' needs an explicit UTC offset (Z or +HH:MM); without one the time is ambiguous"
        )
    return int(parsed.timestamp() * 1000)
