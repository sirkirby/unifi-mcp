"""Tests for MCP protocol abstraction layer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from unifi_mcp_shared.protocol import create_mcp_tool_adapter, get_protocol_version


class TestGetProtocolVersion:
    """Test protocol version resolution from env var."""

    def test_default_is_v1(self):
        assert get_protocol_version() == "v1"

    def test_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_VERSION", "v2")
        assert get_protocol_version() == "v2"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_VERSION", "  v1  ")
        assert get_protocol_version() == "v1"


class TestCreateMcpToolAdapter:
    """Test the tool decorator adapter factory."""

    def test_v1_returns_original_decorator(self):
        mock_decorator = MagicMock(name="fastmcp_tool_decorator")
        adapter = create_mcp_tool_adapter(mock_decorator, protocol_version="v1")
        assert adapter is mock_decorator

    def test_unsupported_version_raises(self):
        mock_decorator = MagicMock()
        with pytest.raises(ValueError, match="Unsupported protocol version"):
            create_mcp_tool_adapter(mock_decorator, protocol_version="v99")

    def test_v2_raises_not_implemented(self):
        mock_decorator = MagicMock()
        with pytest.raises(ValueError, match="not yet implemented"):
            create_mcp_tool_adapter(mock_decorator, protocol_version="v2")

    def test_default_version_uses_env(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_VERSION", "v1")
        mock_decorator = MagicMock()
        adapter = create_mcp_tool_adapter(mock_decorator)
        assert adapter is mock_decorator
