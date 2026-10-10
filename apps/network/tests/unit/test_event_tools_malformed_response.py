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


# --- through the SDK's real decoding and ConnectionManager -------------------------

PRIVATE = "fixture-private-controller-text"


def _sdk_manager(body, *, v2=True) -> EventManager:
    """A real ConnectionManager whose only replaced part is the HTTP exchange."""
    import json

    from unifi_core.network.managers.connection_manager import ConnectionManager

    connection = ConnectionManager("controller.invalid", "fixture-user", "fixture-password")
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.controller = MagicMock()

    async def transport(api_request):
        return api_request.decode(json.dumps(body).encode())

    connection.controller.request = transport
    manager = EventManager(connection)
    manager._use_v2 = v2
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["list_events", "list_alarms"])
async def test_sdk_wrapped_empty_logs_envelope_lists_nothing(monkeypatch, tool):
    from unifi_network_mcp.tools import events as events_module

    monkeypatch.setattr(events_module, "_get_event_manager", lambda: _sdk_manager({"logs": [], "total_page_count": 0}))

    result = await getattr(events_module, tool)()

    assert result["success"] is True
    assert result["count"] == 0
    assert result["events" if tool == "list_events" else "alarms"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["list_events", "list_alarms"])
@pytest.mark.parametrize("body", [{"unexpected": PRIVATE}, {"data": [PRIVATE]}, {"data": [None]}])
async def test_sdk_unreadable_responses_are_tool_errors_without_controller_text(monkeypatch, caplog, tool, body):
    from unifi_network_mcp.tools import events as events_module

    monkeypatch.setattr(events_module, "_get_event_manager", lambda: _sdk_manager(body))

    with caplog.at_level("DEBUG"):
        result = await getattr(events_module, tool)()

    assert result["success"] is False
    assert PRIVATE not in result["error"] and PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "operation"), [("list_events", "list events"), ("list_alarms", "list alarms")])
async def test_legacy_rejection_text_never_reaches_tool_results_or_logs(monkeypatch, caplog, tool, operation):
    from unifi_network_mcp.tools import events as events_module

    body = {"meta": {"rc": "error", "msg": "api.err.FixtureFailure", "detail": PRIVATE}, "data": []}
    monkeypatch.setattr(events_module, "_get_event_manager", lambda: _sdk_manager(body, v2=False))

    with caplog.at_level("DEBUG"):
        result = await getattr(events_module, tool)()

    assert result["success"] is False
    assert result["error"].startswith(f"Failed to {operation}: /stat/")
    assert "failed (AiounifiException)" in result["error"]
    for text in (result["error"], caplog.text):
        assert PRIVATE not in text and "FixtureFailure" not in text
