"""Tests for HTTP transport configuration and uvicorn logging fix."""

import pytest

from unifi_network_mcp.utils.config_helpers import parse_config_bool


class TestUvicornLoggingConfig:
    """Tests for uvicorn access log redirection to stderr."""

    def test_uvicorn_default_access_log_uses_stdout(self):
        """Verify uvicorn's default config uses stdout for access logs (the problem)."""
        import uvicorn.config

        # Get fresh default config
        default_stream = uvicorn.config.LOGGING_CONFIG["handlers"]["access"]["stream"]
        assert default_stream == "ext://sys.stdout", "Expected uvicorn default access log to use stdout"

    def test_uvicorn_config_modification_redirects_to_stderr(self):
        """Verify our fix redirects access logs to stderr."""
        import uvicorn.config

        # Save original
        original = uvicorn.config.LOGGING_CONFIG["handlers"]["access"]["stream"]

        try:
            # Apply our fix
            uvicorn.config.LOGGING_CONFIG["handlers"]["access"]["stream"] = "ext://sys.stderr"

            # Verify it took effect
            assert uvicorn.config.LOGGING_CONFIG["handlers"]["access"]["stream"] == "ext://sys.stderr"

            # Verify uvicorn.Config uses our modified config
            config = uvicorn.Config(app=None, host="127.0.0.1", port=8000)
            assert config.log_config["handlers"]["access"]["stream"] == "ext://sys.stderr", (
                "uvicorn.Config should use the modified LOGGING_CONFIG"
            )
        finally:
            # Restore original to not affect other tests
            uvicorn.config.LOGGING_CONFIG["handlers"]["access"]["stream"] = original


class TestParseConfigBool:
    """Tests for parse_config_bool utility function."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Truthy string values
            ("true", True),
            ("TRUE", True),
            ("True", True),
            ("1", True),
            ("yes", True),
            ("YES", True),
            ("on", True),
            ("ON", True),
            # Falsy string values
            ("false", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
            ("off", False),
            ("", False),
            ("invalid", False),
            # Whitespace handling
            ("  true  ", True),
            ("  false  ", False),
            # Boolean values pass through
            (True, True),
            (False, False),
            # None uses default
            (None, False),
        ],
    )
    def test_parse_config_bool(self, value, expected: bool):
        """Verify config bool parsing handles all expected inputs."""
        result = parse_config_bool(value)
        assert result == expected, f"Expected parse_config_bool({value!r}) to be {expected}"

    @pytest.mark.parametrize("default", [True, False])
    def test_parse_config_bool_default_used_when_none(self, default: bool):
        """Verify the default is used when value is None."""
        assert parse_config_bool(None, default=default) is default


class TestHttpForceFlag:
    """Tests for UNIFI_MCP_HTTP_FORCE configuration option."""

    @pytest.mark.parametrize(
        "force_http,is_main_container_process,expected",
        [
            (True, False, True),  # force flag bypasses the PID check
            (False, False, False),  # PID != 1 without force flag disables HTTP
            (False, True, True),  # PID == 1 keeps HTTP enabled
        ],
    )
    def test_http_enabled_depends_on_pid_and_force_flag(self, force_http, is_main_container_process, expected):
        """Simulate the logic from main.py."""
        http_enabled = True

        if http_enabled and not is_main_container_process and not force_http:
            http_enabled = False

        assert http_enabled is expected


class TestHttpTransportSelection:
    """Tests for UNIFI_MCP_HTTP_TRANSPORT configuration option."""

    VALID_HTTP_TRANSPORTS = {"streamable-http", "sse"}

    def _resolve_transport(self, raw_value):
        """Replicate the transport resolution logic from main.py."""
        http_transport = raw_value if raw_value is not None else "streamable-http"
        if isinstance(http_transport, str):
            http_transport = http_transport.lower()
        if http_transport not in self.VALID_HTTP_TRANSPORTS:
            http_transport = "streamable-http"
        return http_transport

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, "streamable-http"),
            ("streamable-http", "streamable-http"),
            ("sse", "sse"),
            ("Streamable-HTTP", "streamable-http"),
            ("SSE", "sse"),
            ("bogus", "streamable-http"),
            ("", "streamable-http"),
            ("websocket", "streamable-http"),
        ],
    )
    def test_transport_resolution(self, raw, expected):
        """Defaults to streamable-http; case-insensitive; invalid values (incl. websocket) fall back."""
        assert self._resolve_transport(raw) == expected


class TestTransportLogLabels:
    """Tests for transport-aware log label generation."""

    def _get_label(self, transport):
        """Replicate the label logic from main.py."""
        return "Streamable HTTP" if transport == "streamable-http" else "HTTP SSE"

    @pytest.mark.parametrize("transport,label", [("streamable-http", "Streamable HTTP"), ("sse", "HTTP SSE")])
    def test_transport_label(self, transport, label):
        assert self._get_label(transport) == label


class TestTransportConfigYaml:
    """Tests for transport config in config.yaml via OmegaConf."""

    @pytest.mark.parametrize("env_value,expected", [(None, "streamable-http"), ("sse", "sse")])
    def test_config_yaml_transport_resolves(self, tmp_path, monkeypatch, env_value, expected):
        """Transport key resolves to its default and can be overridden via environment variable."""
        from omegaconf import OmegaConf

        monkeypatch.delenv("UNIFI_MCP_HTTP_TRANSPORT", raising=False)
        if env_value is not None:
            monkeypatch.setenv("UNIFI_MCP_HTTP_TRANSPORT", env_value)

        yaml_content = """
server:
  http:
    enabled: false
    force: false
    transport: ${oc.env:UNIFI_MCP_HTTP_TRANSPORT,streamable-http}
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        cfg = OmegaConf.load(config_file)
        OmegaConf.resolve(cfg)
        assert cfg.server.http.transport == expected
