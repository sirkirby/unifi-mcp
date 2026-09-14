"""The runtime builds the one EventManager from config.network.events.

The factories are lru_cached singletons; this test calls the undecorated
functions so the process-wide instances (and the tests that assert on them)
are left alone.
"""

import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


def test_event_buffer_capacity_comes_from_the_env_var(monkeypatch):
    from unifi_network_mcp import runtime

    monkeypatch.setenv("UNIFI_NETWORK_EVENT_BUFFER_SIZE", "7")
    monkeypatch.setattr(runtime, "get_config", runtime.get_config.__wrapped__)
    monkeypatch.setattr(runtime, "get_connection_manager", lambda: MagicMock())

    assert runtime.get_event_manager.__wrapped__().buffer_capacity == 7


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        ("UNIFI_NETWORK_EVENT_BUFFER_SIZE", "0"),
        ("UNIFI_NETWORK_EVENT_BUFFER_TTL", "invalid"),
    ],
)
def test_invalid_event_buffer_env_refuses_startup(monkeypatch, env_var, value):
    from unifi_network_mcp import runtime

    monkeypatch.setenv(env_var, value)
    monkeypatch.setattr(runtime, "get_config", runtime.get_config.__wrapped__)
    monkeypatch.setattr(runtime, "get_connection_manager", lambda: MagicMock())

    with pytest.raises(ValueError, match=env_var):
        runtime.get_event_manager.__wrapped__()
