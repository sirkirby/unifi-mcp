"""The activity histogram must not ask the controller for too many buckets.

Measured against a live controller: `activities/histogram` succeeds at 100
buckets and fails with CODE_SYSTEM_ERROR at 104 and above. The default of 7
days at a hard-coded interval of 3600 asks for 168, so the tool never worked
at its own default.

The interval is therefore derived from the window rather than fixed.
"""

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from unifi_core.access.managers.event_manager import EventManager
from unifi_core.exceptions import UniFiNotFoundError

MAX_BUCKETS = 100


def _manager() -> EventManager:
    cm = MagicMock()
    cm.has_proxy = True
    cm.has_api_client = False
    cm.proxy_request = AsyncMock(return_value={"data": {"buckets": []}})
    cm.extract_data = MagicMock(side_effect=lambda d: d.get("data", {}))
    return EventManager(cm)


def _bucket_count(path: str) -> int:
    q = parse_qs(urlparse(path).query)
    since, until, interval = int(q["since"][0]), int(q["until"][0]), int(q["interval"][0])
    return (until - since) // interval


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
async def test_histogram_never_exceeds_the_controllers_bucket_cap(days) -> None:
    mgr = _manager()
    await mgr.get_activity_summary(days=days)
    path = mgr._cm.proxy_request.call_args.args[1]
    assert _bucket_count(path) <= MAX_BUCKETS, f"{days}d asked for {_bucket_count(path)} buckets"


@pytest.mark.asyncio
async def test_short_windows_keep_hourly_resolution() -> None:
    """Coarsening must not cost resolution where it was not needed: a 1-day
    window still fits in hourly buckets."""
    mgr = _manager()
    await mgr.get_activity_summary(days=1)
    path = mgr._cm.proxy_request.call_args.args[1]
    assert "interval=3600" in path, path


# --- topic vocabulary --------------------------------------------------------


def test_topics_match_the_ui_category_filter() -> None:
    """Verified live. The vocabulary is the Access UI's syslog Category list
    lowercased and snake_cased - guessing at door_openings, doors, access or
    activity finds nothing, which is what made the door history look
    unreachable."""
    from unifi_core.access.managers.event_manager import SYSTEM_LOG_TOPICS

    assert set(SYSTEM_LOG_TOPICS) == {
        "unlocks",
        "access_denial",
        "ring",
        "updates",
        "critical",
        "admin",
        "admin_activity",
    }


def test_door_history_topic_is_accepted() -> None:
    """The whole point of the tool: `unlocks` carries access.door.unlock and
    access.dps.status.update records."""
    from unifi_core.access.managers.event_manager import SYSTEM_LOG_TOPICS

    assert "unlocks" in SYSTEM_LOG_TOPICS


@pytest.mark.asyncio
async def test_an_unsupported_topic_fails_before_the_request_is_sent() -> None:
    """The controller's own error is `CODE_PARAMS_INVALID ... no such topic`,
    which tells a caller nothing about what IS valid."""
    mgr = _manager()
    with pytest.raises(ValueError) as excinfo:
        await mgr.list_events(topic="door_openings")
    msg = str(excinfo.value)
    assert "door_openings" in msg
    assert "unlocks" in msg, "the error must name the valid topics"
    mgr._cm.proxy_request.assert_not_awaited()


# --- window bounds -----------------------------------------------------------


def test_a_window_too_large_for_any_interval_is_rejected_not_silently_coarsened() -> None:
    """Falling back to the coarsest interval just re-creates the failure this
    helper exists to prevent: 1000 days at one bucket per week is 142 buckets,
    straight back to CODE_SYSTEM_ERROR. `days` is unbounded on the MCP tool and
    the GraphQL resolver, so the guard has to live here."""
    from unifi_core.access.managers.event_manager import _histogram_interval

    with pytest.raises(ValueError) as excinfo:
        _histogram_interval(1000)
    assert "672" in str(excinfo.value), "the error must say what the limit actually is"


def test_the_largest_supported_window_still_works() -> None:
    from unifi_core.access.managers.event_manager import _histogram_interval

    assert _histogram_interval(672) == 604800


# --- get_event ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_event_does_not_fan_out_across_every_topic() -> None:
    """Widening this loop to all seven topics was a regression: system-log rows
    carry `id: ""`, so a caller-supplied id cannot match one however many
    topics are searched - it only multiplied the cost of the same 404."""
    mgr = _manager()
    mgr._cm.proxy_request = AsyncMock(return_value={"data": {"events": []}})
    mgr._cm.extract_data = MagicMock(side_effect=lambda d: d.get("data", {}))

    with pytest.raises(UniFiNotFoundError):
        await mgr.get_event("nope")
    searched = {c.kwargs["json"]["topic"] for c in mgr._cm.proxy_request.call_args_list}
    assert searched == {"admin", "admin_activity"}, f"fanned out to {sorted(searched)}"


@pytest.mark.asyncio
async def test_get_event_still_finds_an_event_that_carries_a_real_id() -> None:
    mgr = _manager()
    found = {"id": "evt-9", "event_type": "access.admin.update"}

    async def _search(method, path, json=None, **kw):
        return {"data": {"events": [found] if json and json.get("topic") == "admin" else []}}

    mgr._cm.proxy_request = AsyncMock(side_effect=_search)
    mgr._cm.extract_data = MagicMock(side_effect=lambda d: d.get("data", {}))
    assert await mgr.get_event("evt-9") == found


def test_the_bucket_guard_agrees_with_its_own_advertised_limit() -> None:
    """The controller counts ceil(span/interval); flooring let days=673 pass
    and then request 97 buckets against a cap of 96."""
    from unifi_core.access.managers.event_manager import (
        _MAX_HISTOGRAM_BUCKETS,
        _histogram_interval,
    )

    interval = _histogram_interval(672)
    assert -(-672 * 86400 // interval) <= _MAX_HISTOGRAM_BUCKETS
    with pytest.raises(ValueError):
        _histogram_interval(673)
