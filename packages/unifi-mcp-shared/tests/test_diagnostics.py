"""Tests for the shared diagnostics module."""

from unittest.mock import MagicMock

import pytest
from unifi_core.diagnostics import (
    _redact,
    _safe_json,
    _truncate,
    diagnostics_enabled,
    init_diagnostics,
    wrap_tool,
)


class TestRedact:
    """Tests for _redact helper."""

    def test_redacts_password(self):
        result = _redact({"password": "secret", "name": "ok"})
        assert result["password"] == "***REDACTED***"
        assert result["name"] == "ok"

    def test_redacts_nested(self):
        result = _redact({"outer": {"token": "abc"}})
        assert result["outer"]["token"] == "***REDACTED***"

    def test_redacts_in_list(self):
        result = _redact([{"auth": "secret"}, {"name": "ok"}])
        assert result[0]["auth"] == "***REDACTED***"
        assert result[1]["name"] == "ok"

    def test_preserves_non_sensitive(self):
        data = {"host": "192.168.1.1", "port": 443}
        assert _redact(data) == data

    def test_handles_non_dict(self):
        assert _redact("plain string") == "plain string"
        assert _redact(42) == 42


class TestTruncate:
    """Tests for _truncate helper."""

    def test_no_truncation_under_limit(self):
        assert _truncate("short", 100) == "short"

    def test_truncates_over_limit(self):
        result = _truncate("a" * 200, 50)
        assert len(result) < 200
        assert "truncated" in result


class TestSafeJson:
    """Tests for _safe_json helper."""

    def test_serializes_dict(self):
        result = _safe_json({"key": "value"}, 1000)
        assert '"key"' in result
        assert '"value"' in result

    def test_handles_unserializable(self):
        result = _safe_json(object(), 1000)
        assert isinstance(result, str)


class TestDiagnosticsEnabled:
    """Tests for diagnostics_enabled."""

    def test_disabled_by_default(self, monkeypatch):
        init_diagnostics(config_provider=None)
        monkeypatch.delenv("UNIFI_MCP_DIAGNOSTICS", raising=False)
        assert diagnostics_enabled() is False

    def test_enabled_via_env(self, monkeypatch):
        init_diagnostics(config_provider=None)
        monkeypatch.setenv("UNIFI_MCP_DIAGNOSTICS", "true")
        assert diagnostics_enabled() is True

    def test_enabled_via_config_provider(self):
        mock_config = MagicMock()
        mock_config.server = {"diagnostics": {"enabled": True}}
        init_diagnostics(config_provider=lambda: mock_config)
        assert diagnostics_enabled() is True
        # Reset
        init_diagnostics(config_provider=None)


class TestWrapTool:
    """Tests for wrap_tool."""

    async def test_preserves_return_value(self, monkeypatch):
        init_diagnostics(config_provider=None)
        monkeypatch.delenv("UNIFI_MCP_DIAGNOSTICS", raising=False)

        async def my_tool(x: int) -> dict:
            return {"result": x * 2}

        wrapped = wrap_tool(my_tool, "my_tool")
        result = await wrapped(x=5)
        assert result == {"result": 10}

    async def test_preserves_signature(self):
        import inspect

        async def my_tool(x: int, y: str = "default") -> dict:
            return {}

        wrapped = wrap_tool(my_tool, "my_tool")
        sig = inspect.signature(wrapped)
        assert "x" in sig.parameters
        assert "y" in sig.parameters

    async def test_propagates_exception(self, monkeypatch):
        init_diagnostics(config_provider=None)
        monkeypatch.setenv("UNIFI_MCP_DIAGNOSTICS", "true")

        async def failing_tool():
            raise ValueError("boom")

        wrapped = wrap_tool(failing_tool, "failing")
        with pytest.raises(ValueError, match="boom"):
            await wrapped()
        # Reset
        init_diagnostics(config_provider=None)
