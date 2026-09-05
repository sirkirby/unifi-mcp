"""Guard the call site: `main_async` must start and stop the event listener.

`EventManager.start_listening` existed and was never called by the Network
server, so the websocket buffer behind `unifi_recent_events` could not fill in
production. These tests drive `main_async` and assert on what it awaits.
"""

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from unifi_network_mcp import main as network_main
from unifi_network_mcp.runtime import config


@contextmanager
def _startup(
    *,
    connected: bool,
    websocket_enabled: bool,
    listener: AsyncMock | None = None,
    transports: AsyncMock | None = None,
):
    events = dict(getattr(config.network, "events", {}) or {})
    events["websocket_enabled"] = websocket_enabled
    with (
        patch.object(config.network, "events", events),
        patch("unifi_mcp_shared.bootstrap.assert_credentials_configured"),
        patch.object(network_main.connection_manager, "initialize", AsyncMock(return_value=connected)),
        patch.object(network_main.event_manager, "start_listening", listener or AsyncMock()) as started,
        patch.object(network_main.event_manager, "stop_listening", AsyncMock()) as stopped,
        patch("unifi_mcp_shared.tool_registration.register_tools_for_mode", AsyncMock()),
        patch("unifi_mcp_shared.transport.resolve_http_config", return_value=(False, "http", "0.0.0.0", 3000)),
        patch("unifi_mcp_shared.transport.run_transports", transports or AsyncMock()) as ran,
    ):
        yield started, stopped, ran


def test_the_listener_is_started_on_a_successful_websocket_enabled_startup() -> None:
    with _startup(connected=True, websocket_enabled=True) as (started, _, ran):
        asyncio.run(network_main.main_async())
        started.assert_awaited_once()
        assert ran.await_count == 1, "startup never reached its transports"


def test_the_listener_is_not_started_when_the_connection_fails() -> None:
    with _startup(connected=False, websocket_enabled=True) as (started, _, _):
        asyncio.run(network_main.main_async())
        started.assert_not_awaited()


def test_the_listener_is_not_started_when_the_websocket_is_disabled() -> None:
    with _startup(connected=True, websocket_enabled=False) as (started, _, _):
        asyncio.run(network_main.main_async())
        started.assert_not_awaited()


def test_a_listener_failure_does_not_take_the_server_down() -> None:
    failing = AsyncMock(side_effect=RuntimeError("no websocket"))
    with _startup(connected=True, websocket_enabled=True, listener=failing) as (started, _, ran):
        asyncio.run(network_main.main_async())
        started.assert_awaited_once()
        assert ran.await_count == 1, "a websocket failure stopped the server starting"


def test_the_listener_is_stopped_when_the_transports_return() -> None:
    with _startup(connected=True, websocket_enabled=True) as (_, stopped, _):
        asyncio.run(network_main.main_async())
        stopped.assert_awaited_once()


def test_the_listener_is_stopped_when_the_transports_fail() -> None:
    """The background socket task must not outlive the server on an error exit."""
    crashing = AsyncMock(side_effect=RuntimeError("bind failed"))
    with _startup(connected=True, websocket_enabled=True, transports=crashing) as (_, stopped, _):
        try:
            asyncio.run(network_main.main_async())
        except RuntimeError:
            pass
        stopped.assert_awaited_once()
