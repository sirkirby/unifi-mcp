"""Tests for MCP server host/port configuration via environment variables."""

import os
from unittest import mock

import pytest
from omegaconf import OmegaConf


class TestServerPortConfig:
    """Tests for UNIFI_MCP_HOST and UNIFI_MCP_PORT configuration."""

    @pytest.fixture
    def config_yaml_path(self, tmp_path):
        """Create a temporary config file with env var interpolation."""
        config_content = """
server:
  host: ${oc.env:UNIFI_MCP_HOST,0.0.0.0}
  port: ${oc.env:UNIFI_MCP_PORT,3000}
  log_level: INFO

unifi:
  host: localhost
  username: admin
  password: test
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)
        return config_file

    @pytest.mark.parametrize(
        "env,expected_host,expected_port",
        [
            ({}, "0.0.0.0", 3000),  # defaults when neither variable is set
            ({"UNIFI_MCP_HOST": "127.0.0.1"}, "127.0.0.1", 3000),
            ({"UNIFI_MCP_PORT": "8080"}, "0.0.0.0", 8080),
            ({"UNIFI_MCP_HOST": "192.168.1.100", "UNIFI_MCP_PORT": "9000"}, "192.168.1.100", 9000),
        ],
    )
    def test_host_and_port_from_env(self, config_yaml_path, env, expected_host, expected_port):
        """Verify UNIFI_MCP_HOST / UNIFI_MCP_PORT are respected and defaults apply otherwise."""
        base = {k: v for k, v in os.environ.items() if k not in ("UNIFI_MCP_HOST", "UNIFI_MCP_PORT")}
        with mock.patch.dict(os.environ, {**base, **env}, clear=True):
            cfg = OmegaConf.load(str(config_yaml_path))
            assert cfg.server.host == expected_host
            # OmegaConf returns a string for env interpolation; main.py converts to int.
            port = int(cfg.server.get("port", 3000))
            assert port == expected_port
            assert isinstance(port, int)


class TestServerConfigFromActualFile:
    """Tests that verify the actual config.yaml has correct interpolation syntax."""

    def test_actual_config_has_env_interpolation(self):
        """Verify src/config/config.yaml uses OmegaConf env interpolation for host/port."""
        from pathlib import Path

        config_path = Path(__file__).parent.parent.parent / "src" / "unifi_network_mcp" / "config" / "config.yaml"
        content = config_path.read_text()

        assert "${oc.env:UNIFI_MCP_HOST,127.0.0.1}" in content, (
            "config.yaml should use OmegaConf env interpolation for host"
        )
        assert "${oc.env:UNIFI_MCP_PORT,3000}" in content, "config.yaml should use OmegaConf env interpolation for port"
