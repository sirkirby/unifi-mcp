"""Pytest configuration for unifi-protect-mcp tests."""

import sys
from pathlib import Path

import pytest

# Add the protect app's src directory to path so unifi_protect_mcp is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "controller_reconnect: let ProtectConnectionManager.ensure_connected run; the test must mock the SDK client",
    )


@pytest.fixture(autouse=True)
def _no_automatic_reconnect(request, monkeypatch):
    """Keep unit tests from opening a controller connection.

    Domain tools ensure a connection before they run, and the runtime
    connection manager is built from the developer's environment, so a real
    reconnect attempt could reach a real controller. Tests that exercise the
    reconnect opt in with the ``controller_reconnect`` marker and mock the
    SDK client.
    """
    if request.node.get_closest_marker("controller_reconnect"):
        return
    from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

    async def _no_reconnect(self):
        return self._initialized and self._client is not None

    monkeypatch.setattr(ProtectConnectionManager, "ensure_connected", _no_reconnect)
