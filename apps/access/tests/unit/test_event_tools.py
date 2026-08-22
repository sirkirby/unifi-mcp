"""Tool-layer tests for Access event identity."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.access.models.events import SYNTHETIC_EVENT_ID_PREFIX, event_identity

os.environ.setdefault("UNIFI_ACCESS_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_ACCESS_USERNAME", "test")
os.environ.setdefault("UNIFI_ACCESS_PASSWORD", "test")


@pytest.mark.asyncio
async def test_list_events_projects_a_stable_system_log_id() -> None:
    raw = {
        "id": "",
        "published": 1773766800123,
        "event_type": "access.admin.update",
        "metadata": {"user": {"id": "user-1"}},
    }

    with patch("unifi_access_mcp.tools.events.event_manager") as manager:
        manager.list_events = AsyncMock(return_value=[raw])
        from unifi_access_mcp.tools.events import access_list_events

        result = await access_list_events()

    event_id = result["data"]["events"][0]["id"]
    assert result["success"] is True
    assert event_id == event_identity(raw)
    assert event_id.startswith(SYNTHETIC_EVENT_ID_PREFIX)


@pytest.mark.asyncio
async def test_get_event_round_trips_the_synthetic_id() -> None:
    raw = {
        "id": "",
        "published": 1773766800123,
        "event_type": "access.admin.update",
        "metadata": {"user": {"id": "user-1"}},
    }
    event_id = event_identity(raw)

    with patch("unifi_access_mcp.tools.events.event_manager") as manager:
        manager.get_event = AsyncMock(return_value=raw)
        from unifi_access_mcp.tools.events import access_get_event

        result = await access_get_event(event_id)

    assert result["success"] is True
    assert result["data"]["id"] == event_id
    manager.get_event.assert_awaited_once_with(event_id)
