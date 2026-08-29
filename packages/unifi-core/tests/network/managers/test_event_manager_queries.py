"""Query-contract tests for the Network EventManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.event_manager import EventManager


@pytest.fixture
def connection() -> MagicMock:
    value = MagicMock()
    value.site = "default"
    value.request = AsyncMock()
    return value


@pytest.fixture
def manager(connection: MagicMock) -> EventManager:
    value = EventManager(connection)
    value._use_v2 = True
    return value


@pytest.mark.asyncio
async def test_v2_event_type_uses_exact_keys_filter(manager: EventManager, connection: MagicMock) -> None:
    connection.request.return_value = [{"data": [], "total_element_count": 0}]

    await manager.get_events(event_type="CLIENT_CONNECTED_WIRELESS_2")

    request = connection.request.call_args.args[0]
    assert request.data["keys"] == ["CLIENT_CONNECTED_WIRELESS_2"]
    assert request.data["searchText"] == ""


@pytest.mark.asyncio
async def test_v2_paginates_without_total_page_count(manager: EventManager, connection: MagicMock) -> None:
    connection.request.side_effect = [
        {"logs": [{"id": f"evt{i}"} for i in range(100)]},
        {"logs": [{"id": f"evt{i}"} for i in range(100, 120)]},
    ]

    events = await manager.get_events(limit=120)

    assert [event["id"] for event in events] == [f"evt{i}" for i in range(120)]
    requests = [call.args[0] for call in connection.request.call_args_list]
    assert [request.data["pageNumber"] for request in requests] == [0, 1]


@pytest.mark.asyncio
async def test_v2_honors_arbitrary_start_and_camel_case_page_count(
    manager: EventManager,
    connection: MagicMock,
) -> None:
    connection.request.side_effect = [
        {"data": [{"id": f"evt{i}"} for i in range(100, 110)], "totalPageCount": 12},
        {"data": [{"id": f"evt{i}"} for i in range(110, 120)], "totalPageCount": 12},
    ]

    events = await manager.get_events(limit=10, start=105)

    assert [event["id"] for event in events] == [f"evt{i}" for i in range(105, 115)]
    requests = [call.args[0] for call in connection.request.call_args_list]
    assert [request.data["pageNumber"] for request in requests] == [10, 11]


@pytest.mark.asyncio
async def test_event_key_discovery_samples_recent_events_and_supports_legacy_event_field(
    manager: EventManager,
) -> None:
    manager.get_events = AsyncMock(
        return_value=[
            {"key": "CLIENT_CONNECTED_WIRELESS_2"},
            {"event": "EVT_SW_Connected"},
            {"key": "CLIENT_CONNECTED_WIRELESS_2"},
        ]
    )

    event_types = await manager.get_event_type_prefixes()

    manager.get_events.assert_awaited_once_with(within=168, limit=1000)
    assert event_types == [
        {
            "key": "CLIENT_CONNECTED_WIRELESS_2",
            "prefix": "CLIENT_CONNECTED_WIRELESS_2",
            "description": "Exact event key observed in the 1,000 most recent events within the last 7 days",
            "observed_count": 2,
        },
        {
            "key": "EVT_SW_Connected",
            "prefix": "EVT_SW_Connected",
            "description": "Exact event key observed in the 1,000 most recent events within the last 7 days",
            "observed_count": 1,
        },
    ]


@pytest.mark.asyncio
async def test_event_key_discovery_can_return_empty_catalog(manager: EventManager) -> None:
    manager.get_events = AsyncMock(return_value=[])

    assert await manager.get_event_type_prefixes() == []
