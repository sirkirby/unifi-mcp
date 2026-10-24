import os
from unittest.mock import patch

import pytest


def test_config_loads_required_vars():
    env = {
        "UNIFI_RELAY_URL": "https://my-worker.workers.dev",
        "UNIFI_RELAY_TOKEN": "test-token-abc",
        "UNIFI_RELAY_LOCATION_NAME": "Home Lab",
    }
    with patch.dict(os.environ, env, clear=False):
        from unifi_mcp_relay.config import load_config

        cfg = load_config()
        assert cfg.relay_url == "https://my-worker.workers.dev"
        assert cfg.relay_token == "test-token-abc"
        assert cfg.location_name == "Home Lab"


def test_config_missing_required_var_raises():
    env = {
        "UNIFI_RELAY_URL": "https://my-worker.workers.dev",
    }
    with patch.dict(os.environ, env, clear=True):
        from unifi_mcp_relay.config import load_config

        with pytest.raises(ValueError, match="UNIFI_RELAY_TOKEN"):
            load_config()


def test_config_defaults():
    env = {
        "UNIFI_RELAY_URL": "https://my-worker.workers.dev",
        "UNIFI_RELAY_TOKEN": "test-token",
        "UNIFI_RELAY_LOCATION_NAME": "Test",
    }
    with patch.dict(os.environ, env, clear=False):
        from unifi_mcp_relay.config import load_config

        cfg = load_config()
        assert cfg.servers == ["http://localhost:3000"]
        assert cfg.refresh_interval == 300
        assert cfg.reconnect_max_delay == 60


@pytest.mark.parametrize(
    ("var_name", "bad_value"),
    [
        ("UNIFI_RELAY_REFRESH_INTERVAL", "5m"),
        ("UNIFI_RELAY_RECONNECT_MAX_DELAY", "one-minute"),
    ],
)
def test_config_bad_integer_names_variable(var_name, bad_value):
    env = {
        "UNIFI_RELAY_URL": "https://my-worker.workers.dev",
        "UNIFI_RELAY_TOKEN": "test-token",
        "UNIFI_RELAY_LOCATION_NAME": "Test",
        var_name: bad_value,
    }
    with patch.dict(os.environ, env, clear=False):
        from unifi_mcp_relay.config import load_config

        with pytest.raises(ValueError, match=var_name):
            load_config()


def test_config_servers_with_trailing_comma():
    env = {
        "UNIFI_RELAY_URL": "https://my-worker.workers.dev",
        "UNIFI_RELAY_TOKEN": "test-token",
        "UNIFI_RELAY_LOCATION_NAME": "Test",
        "UNIFI_RELAY_SERVERS": "http://localhost:3000,http://localhost:3001,",
    }
    with patch.dict(os.environ, env, clear=False):
        from unifi_mcp_relay.config import load_config

        cfg = load_config()
        assert cfg.servers == ["http://localhost:3000", "http://localhost:3001"]
