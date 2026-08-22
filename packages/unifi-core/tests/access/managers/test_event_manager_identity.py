"""Access EventManager system-log identity and lookup tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from unifi_core.access.managers.event_manager import EventManager
from unifi_core.access.models.events import SYNTHETIC_EVENT_ID_PREFIX, event_identity
from unifi_core.exceptions import UniFiConnectionError


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


@pytest.mark.asyncio
async def test_list_events_assigns_identity_without_mutating_controller_row(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    raw = {
        "id": "",
        "published": 1773766800123,
        "event_type": "access.admin.update",
        "metadata": {"user": {"id": "user-1"}},
    }
    connection_manager.proxy_request.return_value = {"total": 1, "data": {"events": [raw]}}

    events = await event_manager.list_events()

    assert events[0]["id"].startswith(SYNTHETIC_EVENT_ID_PREFIX)
    assert raw["id"] == ""


@pytest.mark.asyncio
async def test_get_event_resolves_synthetic_id_on_later_controller_page(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("unifi_core.access.managers.event_manager._GET_EVENT_PAGE_SIZE", 2)
    target = {
        "id": "",
        "published": 1773766800123,
        "event_type": "access.admin.update",
        "metadata": {"user": {"id": "user-2"}},
    }
    first_page = [
        {"id": "", "published": 1773766802000, "event_type": "access.admin.update", "sequence": 1},
        {"id": "", "published": 1773766801000, "event_type": "access.admin.update", "sequence": 2},
    ]
    connection_manager.proxy_request.side_effect = [
        {"page": 1, "num": 2, "total": 3, "data": {"events": first_page}},
        {"page": 2, "num": 1, "total": 3, "data": {"events": [target]}},
    ]

    event = await event_manager.get_event(event_identity(target))

    assert event["id"] == event_identity(target)
    assert "page_num=2" in connection_manager.proxy_request.await_args_list[1].args[1]


@pytest.mark.asyncio
async def test_get_event_searches_every_listable_system_log_topic(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    target = {
        "id": "",
        "published": 1773766800123,
        "event_type": "access.admin.update",
    }

    async def response_for_topic(*args, **kwargs):
        if kwargs["json"]["topic"] == "admin_activity":
            return {"total": 1, "data": {"events": [target]}}
        return {"total": 0, "data": {"events": []}}

    connection_manager.proxy_request.side_effect = response_for_topic

    event = await event_manager.get_event(event_identity(target))

    assert event["id"] == event_identity(target)
    assert [call.kwargs["json"]["topic"] for call in connection_manager.proxy_request.await_args_list] == [
        "unlocks",
        "access_denial",
        "ring",
        "updates",
        "critical",
        "admin",
        "admin_activity",
    ]


@pytest.mark.asyncio
async def test_get_event_skips_topics_unsupported_by_controller_version(
    event_manager: EventManager,
    connection_manager: _ConnectionManager,
) -> None:
    target = {"id": "evt-1", "type": "door_open"}

    async def response_for_topic(*args, **kwargs):
        topic = kwargs["json"]["topic"]
        if topic == "updates":
            raise UniFiConnectionError("Invalid parameters. no such topic: updates")
        if topic == "critical":
            return {"total": 1, "data": {"events": [target]}}
        return {"total": 0, "data": {"events": []}}

    connection_manager.proxy_request.side_effect = response_for_topic

    event = await event_manager.get_event("evt-1")

    assert event == target
