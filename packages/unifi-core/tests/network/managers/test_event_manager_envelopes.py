"""The Network EventManager tells a malformed response apart from a valid empty collection."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.incident_evidence import FailureKind, failure_from_exception
from unifi_core.network.managers.event_manager import EventManager


def _manager(use_v2: bool, response) -> EventManager:
    connection = MagicMock()
    connection.site = "default"
    connection.request = AsyncMock(return_value=response)
    manager = EventManager(connection)
    manager._use_v2 = use_v2
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("use_v2", "response"),
    [
        (True, {"data": []}),
        (True, {"logs": []}),
        (True, [{"data": [], "total_element_count": 0}]),
        (True, [{"logs": [], "total_page_count": 0}]),
        (True, [{"total_element_count": 0, "total_page_count": 0}]),
        (False, []),
        (False, {"data": []}),
    ],
)
async def test_valid_empty_collections_are_empty(use_v2, response) -> None:
    manager = _manager(use_v2, response)
    assert await manager.get_events(limit=10) == []
    assert await manager.get_alarms(limit=10) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("use_v2", "response"),
    [
        (True, {"unexpected": "envelope"}),
        (True, [{"unexpected": "envelope"}]),
        (True, []),
        (True, [{"data": []}, {"data": []}]),
        (True, [{"total_element_count": 3}]),
        (True, {"data": "invalid"}),
        (True, {"logs": {"not": "a list"}}),
        (True, "not json"),
        (True, None),
        (False, {"meta": {"rc": "ok"}}),
        (False, {"data": "invalid"}),
        (False, None),
    ],
)
async def test_malformed_envelopes_raise_instead_of_returning_empty(use_v2, response) -> None:
    manager = _manager(use_v2, response)
    with pytest.raises(UniFiMalformedResponseError) as events_error:
        await manager.get_events(limit=10)
    with pytest.raises(UniFiMalformedResponseError):
        await manager.get_alarms(limit=10)
    # Fixed operation context only; the payload is never echoed.
    assert "invalid" not in str(events_error.value) and "unexpected" not in str(events_error.value)
    assert failure_from_exception(events_error.value).kind is FailureKind.PARSE_FAILED


@pytest.mark.asyncio
async def test_malformed_later_v2_page_raises() -> None:
    manager = _manager(True, None)
    manager._connection.request.side_effect = [{"data": [{"id": f"e{i}"} for i in range(100)]}, {"oops": 1}]
    with pytest.raises(UniFiMalformedResponseError):
        await manager.get_events(limit=150)
