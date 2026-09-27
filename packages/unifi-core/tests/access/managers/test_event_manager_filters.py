"""Tests for Access EventManager event filtering, timestamp translation, and bounded pagination."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from unifi_core.access.managers.event_manager import EventManager
from unifi_core.exceptions import UniFiOperationError


class _ConnectionManager:
    """Minimal proxy connection used by EventManager query tests."""

    has_proxy = True

    def __init__(self) -> None:
        self.proxy_request = AsyncMock()

    @staticmethod
    def extract_data(response):
        return response.get("data", response)


@pytest.fixture
def connection_manager() -> _ConnectionManager:
    return _ConnectionManager()


@pytest.fixture
def event_manager(connection_manager: _ConnectionManager) -> EventManager:
    return EventManager(connection_manager)


# Fixture events
RAW_DOOR_UNLOCK_1 = {
    "id": "",
    "event_type": "access.door.unlock",
    "published": 1787054400000,
    "result": "ACCESS",
    "metadata": {
        "actor": {"id": "user-1", "type": "user", "display_name": "Alice"},
        "door": {"id": "door-1", "type": "door", "display_name": "Front Door"},
    },
}

RAW_DOOR_UNLOCK_2 = {
    "id": "",
    "event_type": "access.door.unlock",
    "published": 1787054401000,
    "result": "ACCESS",
    "metadata": {
        "actor": {"id": "user-2", "type": "user", "display_name": "Bob"},
        "door": {"id": "door-2", "type": "door", "display_name": "Back Door"},
    },
}

RAW_HUB_STATUS = {
    "id": "",
    "event_type": "access.dps.status.update",
    "published": 1787054402000,
    "result": "SUCCESS",
    "metadata": {
        "actor": {"id": "hub-1", "type": "UA-Hub-Door-Mini", "display_name": "Front Door Hub"},
        "door": {"id": "door-1", "type": "door", "display_name": "Front Door"},
    },
}

RAW_READER_EVENT = {
    "id": "",
    "event_type": "access.device.update",
    "published": 1787054403000,
    "result": "SUCCESS",
    "metadata": {
        "actor": {"id": "user-1", "type": "user", "display_name": "Alice"},
        "device": {"id": "reader-1", "type": "UVC G6 Pro Entry", "display_name": "Reader 1"},
    },
}


@pytest.mark.asyncio
async def test_list_events_translates_start_end_to_since_until_rfc3339(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """start/end must be converted to since/until RFC3339 strings; start/end/door_id/user_id must not be sent."""
    connection_manager.proxy_request.return_value = {"total": 0, "data": {"events": []}}

    await event_manager.list_events(
        topic="unlocks",
        start="2026-09-19T00:00:00Z",
        end="2026-09-19T23:59:59Z",
        door_id="door-1",
        user_id="user-1",
    )

    body = connection_manager.proxy_request.call_args[1]["json"]
    assert body["topic"] == "unlocks"
    assert body.get("since") == "2026-09-19T00:00:00Z"
    assert body.get("until") == "2026-09-19T23:59:59Z"
    # The controller ignores these keys on insights/system_log/search
    assert "start" not in body
    assert "end" not in body
    assert "door_id" not in body
    assert "user_id" not in body


@pytest.mark.asyncio
async def test_list_events_preserves_fractional_seconds(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """Sub-second timestamps must preserve fractional seconds rather than truncating them."""
    connection_manager.proxy_request.return_value = {"total": 0, "data": {"events": []}}

    await event_manager.list_events(
        start="2026-09-19T00:00:00.123456Z",
        end="2026-09-19T23:59:59.500Z",
    )
    body = connection_manager.proxy_request.call_args[1]["json"]
    assert body.get("since") == "2026-09-19T00:00:00.123456Z"
    assert body.get("until") == "2026-09-19T23:59:59.500000Z"


@pytest.mark.asyncio
async def test_list_events_epoch_zero(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """ISO epoch zero is parsed and formatted as RFC 3339."""
    connection_manager.proxy_request.return_value = {"total": 0, "data": {"events": []}}

    await event_manager.list_events(start="1970-01-01T00:00:00Z")
    body = connection_manager.proxy_request.call_args[1]["json"]
    assert body.get("since") == "1970-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_list_events_future_time_window_returns_empty(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """A future time window where controller returns 0 events completes with an empty list."""
    connection_manager.proxy_request.return_value = {"total": 0, "data": {"events": []}}

    res = await event_manager.list_events(start="2099-01-01T00:00:00Z", end="2099-01-02T00:00:00Z")
    assert res == []


@pytest.mark.asyncio
async def test_list_events_timestamp_validation(event_manager: EventManager) -> None:
    """Invalid timestamps and inverted time windows must raise ValueError."""
    with pytest.raises(ValueError, match="Invalid timestamp"):
        await event_manager.list_events(start="not-a-timestamp")

    with pytest.raises(ValueError, match="must not be after"):
        await event_manager.list_events(
            start="2026-09-20T00:00:00Z",
            end="2026-09-19T00:00:00Z",
        )


@pytest.mark.asyncio
async def test_list_events_equal_second_mixed_fraction_regression(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """Equal-second mixed-fraction timestamps must compare datetime values, not RFC3339 strings."""
    connection_manager.proxy_request.return_value = {"total": 0, "data": {"events": []}}

    # start is 100ms after end in the same second (00.100000Z vs 00Z)
    # Lexicographically '...00.100000Z' < '...00Z', but in time start > end
    with pytest.raises(ValueError, match="must not be after"):
        await event_manager.list_events(
            start="2026-09-19T00:00:00.100000Z",
            end="2026-09-19T00:00:00Z",
        )

    # Valid reverse: start is before end
    await event_manager.list_events(
        start="2026-09-19T00:00:00Z",
        end="2026-09-19T00:00:00.100000Z",
    )
    body = connection_manager.proxy_request.call_args[1]["json"]
    assert body.get("since") == "2026-09-19T00:00:00Z"
    assert body.get("until") == "2026-09-19T00:00:00.100000Z"


@pytest.mark.asyncio
async def test_list_events_filters_by_door_and_user(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """Only events matching door_id and user_id are returned."""
    connection_manager.proxy_request.return_value = {
        "total": 3,
        "data": {"events": [RAW_DOOR_UNLOCK_1, RAW_DOOR_UNLOCK_2, RAW_HUB_STATUS]},
    }

    # Filter by door
    res = await event_manager.list_events(topic="unlocks", door_id="door-1")
    assert len(res) == 2
    assert res[0]["metadata"]["door"]["id"] == "door-1"
    assert res[1]["metadata"]["door"]["id"] == "door-1"

    # Filter by user
    res = await event_manager.list_events(topic="unlocks", user_id="user-1")
    assert len(res) == 1
    assert res[0]["metadata"]["actor"]["id"] == "user-1"


@pytest.mark.asyncio
async def test_list_events_excludes_hub_actors_from_user_matches(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """A hub actor (type != 'user') must never match a user_id filter."""
    connection_manager.proxy_request.return_value = {
        "total": 1,
        "data": {"events": [RAW_HUB_STATUS]},
    }

    res = await event_manager.list_events(topic="unlocks", user_id="hub-1")
    assert res == []


@pytest.mark.asyncio
async def test_list_events_sparse_matches_beyond_page_one(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """Filtering across multiple pages collects matches until limit or exhaustion."""
    page_1 = [RAW_DOOR_UNLOCK_1, RAW_HUB_STATUS]
    page_2 = [RAW_DOOR_UNLOCK_2]

    connection_manager.proxy_request.side_effect = [
        {"total": 3, "data": {"events": page_1}},
        {"total": 3, "data": {"events": page_2}},
    ]

    res = await event_manager.list_events(topic="unlocks", door_id="door-2", limit=5)
    assert len(res) == 1
    assert res[0]["metadata"]["door"]["id"] == "door-2"
    assert connection_manager.proxy_request.await_count == 2


@pytest.mark.asyncio
async def test_list_events_constant_page_size_across_pages(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """page_size must remain constant across page numbers to avoid offset shifts."""
    door_2_b = {**RAW_DOOR_UNLOCK_2, "published": 1787054499000}
    connection_manager.proxy_request.side_effect = [
        {"total": 200, "data": {"events": [RAW_DOOR_UNLOCK_1]}},
        {"total": 200, "data": {"events": [RAW_DOOR_UNLOCK_2, door_2_b]}},
    ]

    res = await event_manager.list_events(topic="unlocks", door_id="door-2", limit=2)
    assert len(res) == 2
    assert connection_manager.proxy_request.await_count == 2
    url_1 = connection_manager.proxy_request.await_args_list[0].args[1]
    url_2 = connection_manager.proxy_request.await_args_list[1].args[1]
    assert "page_size=100&page_num=1" in url_1
    assert "page_size=100&page_num=2" in url_2


@pytest.mark.asyncio
async def test_list_events_detects_repeated_pages(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """If the controller returns identical page data across pages, raise UniFiOperationError."""
    # Controller returns the same page twice
    connection_manager.proxy_request.side_effect = [
        {"total": 100, "data": {"events": [RAW_DOOR_UNLOCK_1]}},
        {"total": 100, "data": {"events": [RAW_DOOR_UNLOCK_1]}},
    ]

    with pytest.raises(UniFiOperationError, match="repeated page data"):
        await event_manager.list_events(topic="unlocks", door_id="door-2", limit=5)


@pytest.mark.asyncio
async def test_list_events_duplicate_identities_do_not_fill_limit(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate event identities must not be counted twice towards filling the requested limit."""
    monkeypatch.setattr("unifi_core.access.managers.event_manager._MAX_SCAN_PAGES", 2)
    # Page 1 has door-2 unlock; Page 2 has the same door-2 unlock plus another event
    # We alter event type of the second event to make page_sig distinct, but keep the matching event duplicate
    dup_matching_event = dict(RAW_DOOR_UNLOCK_2)
    distinct_second_event = {**RAW_DOOR_UNLOCK_1, "published": 1787054499000}

    connection_manager.proxy_request.side_effect = [
        {"total": 100, "data": {"events": [RAW_DOOR_UNLOCK_2]}},
        {"total": 100, "data": {"events": [dup_matching_event, distinct_second_event]}},
    ]

    # limit=2, but only 1 unique door-2 event exists across the 2 pages
    with pytest.raises(UniFiOperationError, match="Cannot establish completeness"):
        await event_manager.list_events(topic="unlocks", door_id="door-2", limit=2)


@pytest.mark.asyncio
async def test_list_events_bounded_pagination_fails_when_completeness_unestablished(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _MAX_SCAN_PAGES is reached without satisfying limit and more events remain, raise UniFiOperationError."""
    monkeypatch.setattr("unifi_core.access.managers.event_manager._MAX_SCAN_PAGES", 2)
    # Each page returns 1 non-matching distinct event; total is 100 events
    event_p1 = {**RAW_DOOR_UNLOCK_1, "published": 1787054400000}
    event_p2 = {**RAW_DOOR_UNLOCK_1, "published": 1787054400001}
    connection_manager.proxy_request.side_effect = [
        {"total": 100, "data": {"events": [event_p1]}},
        {"total": 100, "data": {"events": [event_p2]}},
    ]

    with pytest.raises(UniFiOperationError, match="Narrow the date range using start and end filters"):
        await event_manager.list_events(topic="unlocks", door_id="door-2", limit=5)


@pytest.mark.asyncio
async def test_list_events_completeness_established_when_exhausted(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """When controller has no more events, partial count is complete and does not fail."""
    # Only 1 matching event exists on controller total
    connection_manager.proxy_request.return_value = {
        "total": 1,
        "data": {"events": [RAW_DOOR_UNLOCK_2]},
    }

    res = await event_manager.list_events(topic="unlocks", door_id="door-2", limit=5)
    assert len(res) == 1
    assert res[0]["metadata"]["door"]["id"] == "door-2"


@pytest.mark.asyncio
async def test_list_events_no_filters_single_page(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """Without door or user filters, list_events requests page_size=limit."""
    connection_manager.proxy_request.return_value = {
        "total": 10,
        "data": {"events": [RAW_DOOR_UNLOCK_1, RAW_DOOR_UNLOCK_2]},
    }

    res = await event_manager.list_events(topic="unlocks", limit=2)
    assert len(res) == 2
    assert "page_size=2" in connection_manager.proxy_request.call_args[0][1]


@pytest.mark.asyncio
async def test_list_events_overlapping_middle_page_does_not_hide_final_match(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    """An overlapping middle page must not prematurely exhaust total count and hide subsequent matching events."""
    event_1 = RAW_DOOR_UNLOCK_1  # door-1 (non-matching)
    event_2 = {**RAW_DOOR_UNLOCK_1, "published": 1787054410000}  # door-1 (non-matching)
    event_3 = RAW_DOOR_UNLOCK_2  # door-2 (matching)

    # Total controller events = 3.
    # Page 1: [event_1]
    # Page 2: [event_1, event_2] (overlap from page 1: raw scanned count reaches 3, but unique is 2)
    # Page 3: [event_3] (contains the matching event)
    connection_manager.proxy_request.side_effect = [
        {"total": 3, "data": {"events": [event_1]}},
        {"total": 3, "data": {"events": [event_1, event_2]}},
        {"total": 3, "data": {"events": [event_3]}},
    ]

    res = await event_manager.list_events(topic="unlocks", door_id="door-2", limit=2)
    assert len(res) == 1
    assert res[0]["metadata"]["door"]["id"] == "door-2"
    assert connection_manager.proxy_request.await_count == 3


@pytest.mark.asyncio
async def test_unfiltered_large_limit_can_cross_filtered_scan_budget(event_manager, connection_manager):
    connection_manager.proxy_request.side_effect = [
        {"total": 5000, "data": {"events": [{"id": str(page * 100 + i)} for i in range(100)]}} for page in range(15)
    ]
    events = await event_manager.list_events(topic="unlocks", limit=1500)
    assert len(events) == 1500
    assert len({event["id"] for event in events}) == 1500
    assert connection_manager.proxy_request.await_count == 15


@pytest.mark.asyncio
async def test_unfiltered_large_limit_recovers_overlapping_pages(event_manager, connection_manager):
    connection_manager.proxy_request.side_effect = [
        {"total": 5000, "data": {"events": [{"id": str(page * 99 + i)} for i in range(100)]}} for page in range(16)
    ]
    events = await event_manager.list_events(topic="unlocks", limit=1500)
    assert len(events) == 1500
    assert len({event["id"] for event in events}) == 1500
    assert connection_manager.proxy_request.await_count == 16


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [5001, 1_000_000])
async def test_event_limit_bounds_controller_requests(event_manager, connection_manager, limit):
    with pytest.raises(ValueError, match="limit must not exceed 5000"):
        await event_manager.list_events(topic="unlocks", limit=limit)
    connection_manager.proxy_request.assert_not_awaited()
