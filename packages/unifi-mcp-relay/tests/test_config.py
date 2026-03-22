import os
import pytest
from unittest.mock import patch


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


def test_config_parses_server_list():
    env = {
        "UNIFI_RELAY_URL": "https://my-worker.workers.dev",
        "UNIFI_RELAY_TOKEN": "test-token",
        "UNIFI_RELAY_LOCATION_NAME": "Test",
        "UNIFI_RELAY_SERVERS": "http://localhost:3000,http://localhost:3001,http://localhost:3002",
    }
    with patch.dict(os.environ, env, clear=False):
        from unifi_mcp_relay.config import load_config
        cfg = load_config()
        assert cfg.servers == ["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"]


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
