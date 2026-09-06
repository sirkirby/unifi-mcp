"""Guard the call site: `main_async` must start the event listener.

`EventManager.start_listening` existed, was unit-tested, and was never called
by the application — `main_async` carried a TODO and a log line claiming the
feature was unimplemented, where the Protect server calls it. The manager tests
passed because they invoked the manager directly, so nothing caught that the
buffer could not fill in production.

These tests drive `main_async` and assert on what it actually awaits. An
earlier version asserted that the call appeared in `inspect.getsource`, which
would have passed with the call commented out — the very state it was written
to catch.
"""

import asyncio
import logging
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from unifi_access_mcp import main as access_main
from unifi_access_mcp.runtime import config


@contextmanager
def _startup(*, connected: bool, websocket_enabled: bool, listener: AsyncMock | None = None):
    """Run `main_async` with its side effects stubbed.

    Only the connection, the listener and the two long-running tails are
    replaced. The websocket decision itself runs for real, since that branch is
    what these tests are about.
    """
    events = dict(getattr(config.access, "events", {}) or {})
    events["websocket_enabled"] = websocket_enabled
    with (
        patch.object(config.access, "events", events),
        patch("unifi_mcp_shared.bootstrap.assert_credentials_configured"),
        patch.object(access_main.connection_manager, "initialize", AsyncMock(return_value=connected)),
        patch.object(access_main.event_manager, "set_server"),
        patch.object(access_main.event_manager, "start_listening", listener or AsyncMock()) as started,
        patch("unifi_mcp_shared.tool_registration.register_tools_for_mode", AsyncMock()),
        patch("unifi_mcp_shared.transport.resolve_http_config", return_value=(False, "http", "0.0.0.0", 3002)),
        patch("unifi_mcp_shared.transport.run_transports", AsyncMock()) as transports,
    ):
        asyncio.run(access_main.main_async())
        yield started, transports


def test_the_listener_is_started_on_a_successful_websocket_enabled_startup() -> None:
    with _startup(connected=True, websocket_enabled=True) as (started, transports):
        started.assert_awaited_once()
        assert transports.await_count == 1, "startup never reached its transports"


def test_the_listener_is_not_started_when_the_connection_fails() -> None:
    """A failed connection has no session to listen on."""
    with _startup(connected=False, websocket_enabled=True) as (started, _):
        started.assert_not_awaited()


def test_the_listener_is_not_started_when_the_websocket_is_disabled() -> None:
    """`websocket_enabled: false` is a supported deployment — REST queries only."""
    with _startup(connected=True, websocket_enabled=False) as (started, _):
        started.assert_not_awaited()


def test_a_listener_failure_does_not_take_the_server_down() -> None:
    """The websocket is optional: a proxy-only deployment must still serve
    tools, so the failure is logged and startup continues."""
    failing = AsyncMock(side_effect=RuntimeError("no api client"))
    with _startup(connected=True, websocket_enabled=True, listener=failing) as (started, transports):
        started.assert_awaited_once()
        assert transports.await_count == 1, "a websocket failure stopped the server starting"


def test_startup_warns_about_an_unrecognized_policy_variable(monkeypatch, caplog) -> None:
    """The scan runs from `main_async`, not only from its own unit tests."""
    monkeypatch.setenv("UNIFI_POLICY_ACCESS_DOOR_UPDATE", "true")
    with caplog.at_level(logging.WARNING), _startup(connected=True, websocket_enabled=False):
        pass
    assert "UNIFI_POLICY_ACCESS_DOOR_UPDATE" in caplog.text
    assert "UNIFI_POLICY_ACCESS_DOORS_UPDATE" in caplog.text
