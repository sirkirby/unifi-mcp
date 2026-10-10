"""Tool-visible behaviour when the controller returns an unreadable event envelope.

The manager raises instead of returning an empty list, so the tools answer
with their standard error envelope rather than a successful empty listing.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

from unifi_core.network.managers.event_manager import EventManager  # noqa: E402


def _manager(response) -> EventManager:
    connection = MagicMock()
    connection.site = "default"
    connection.request = AsyncMock(return_value=response)
    manager = EventManager(connection)
    manager._use_v2 = True
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "operation"),
    [("list_events", "list events"), ("list_alarms", "list alarms")],
)
async def test_malformed_envelope_is_a_tool_error_not_an_empty_success(monkeypatch, tool, operation):
    from unifi_network_mcp.tools import events as events_module

    monkeypatch.setattr(events_module, "_get_event_manager", lambda: _manager({"unexpected": "envelope"}))

    result = await getattr(events_module, tool)()

    assert result["success"] is False
    assert result["error"].startswith(f"Failed to {operation}: Unexpected response shape from /system-log/")
    assert "envelope" not in result["error"]
    assert set(result) == {"success", "error"}


@pytest.mark.asyncio
async def test_valid_empty_envelope_is_still_an_empty_success(monkeypatch):
    from unifi_network_mcp.tools import events as events_module

    monkeypatch.setattr(events_module, "_get_event_manager", lambda: _manager({"data": []}))

    result = await events_module.list_events()

    assert result["success"] is True
    assert result["events"] == [] and result["count"] == 0
