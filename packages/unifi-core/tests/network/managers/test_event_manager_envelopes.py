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
        (True, [{"data": []}, {"data": []}]),
        (True, [{"data": []}, {"id": "alarm-1"}]),
        (True, ["invalid row"]),
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


@pytest.mark.asyncio
async def test_empty_critical_log_is_empty_but_empty_all_log_is_malformed() -> None:
    manager = _manager(True, [])
    with pytest.raises(UniFiMalformedResponseError):
        await manager.get_events(limit=10)
    page = await manager.get_alarms_page(limit=10)
    assert page.rows == []
    assert page.total_reported == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_rows", "expected_total"),
    [
        ([{"id": "alarm-1", "severity": "HIGH"}], [{"id": "alarm-1", "severity": "HIGH"}], None),
        (
            [{"id": "alarm-1", "severity": "HIGH"}, {"id": "alarm-2", "severity": "VERY_HIGH"}],
            [{"id": "alarm-1", "severity": "HIGH"}, {"id": "alarm-2", "severity": "VERY_HIGH"}],
            None,
        ),
        ([{"data": [{"id": "alarm-1"}], "total_element_count": 1, "total_page_count": 1}], [{"id": "alarm-1"}], 1),
    ],
)
async def test_critical_log_accepts_bare_rows_and_wrapped_envelope(response, expected_rows, expected_total) -> None:
    manager = _manager(True, response)

    page = await manager.get_alarms_page(limit=10)

    assert page.rows == expected_rows
    assert page.total_reported == expected_total
    assert page.has_more is False


@pytest.mark.asyncio
async def test_full_page_of_bare_critical_rows_leaves_totals_and_more_unknown() -> None:
    rows = [{"id": f"alarm-{i}", "severity": "HIGH"} for i in range(10)]
    manager = _manager(True, rows)

    page = await manager.get_alarms_page(limit=10)

    assert page.rows == rows
    assert page.total_reported is None
    assert page.has_more is None
