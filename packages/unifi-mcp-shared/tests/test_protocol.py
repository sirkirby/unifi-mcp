"""Tests for MCP protocol abstraction layer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from unifi_mcp_shared.protocol import (
    DEFAULT_MCP_PROTOCOL_REVISION,
    create_mcp_tool_adapter,
    get_protocol_revision,
    get_protocol_version,
)


class TestGetProtocolRevision:
    """Test protocol revision resolution from env vars."""

    def test_default_is_current_supported_revision(self):
        assert get_protocol_revision() == DEFAULT_MCP_PROTOCOL_REVISION

    def test_reads_from_revision_env(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_REVISION", "2025-11-25")
        assert get_protocol_revision() == "2025-11-25"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_REVISION", "  2025-11-25  ")
        assert get_protocol_revision() == "2025-11-25"

    def test_revision_env_takes_precedence_over_legacy_version_env(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_REVISION", "2025-11-25")
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_VERSION", "v1")
        assert get_protocol_revision() == "2025-11-25"

    def test_legacy_v1_env_alias_maps_to_current_revision(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_VERSION", "v1")
        assert get_protocol_revision() == DEFAULT_MCP_PROTOCOL_REVISION


class TestGetProtocolVersion:
    """Test deprecated protocol version compatibility helper."""

    def test_default_legacy_version_is_v1(self):
        assert get_protocol_version() == "v1"

    def test_reads_legacy_version_env(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_VERSION", "  v1  ")
        assert get_protocol_version() == "v1"


class TestCreateMcpToolAdapter:
    """Test the tool decorator adapter factory."""

    def test_current_revision_returns_original_decorator(self):
        mock_decorator = MagicMock(name="fastmcp_tool_decorator")
        adapter = create_mcp_tool_adapter(mock_decorator, protocol_revision="2025-11-25")
        assert adapter is mock_decorator

    def test_legacy_v1_version_alias_returns_original_decorator(self):
        mock_decorator = MagicMock(name="fastmcp_tool_decorator")
        adapter = create_mcp_tool_adapter(mock_decorator, protocol_version="v1")
        assert adapter is mock_decorator

    def test_unsupported_revision_raises(self):
        mock_decorator = MagicMock()
        with pytest.raises(ValueError, match="Unsupported MCP protocol revision"):
            create_mcp_tool_adapter(mock_decorator, protocol_revision="2026-06-18")

    def test_v2_version_alias_raises(self):
        mock_decorator = MagicMock()
        with pytest.raises(ValueError, match="Use date-based MCP protocol revisions"):
            create_mcp_tool_adapter(mock_decorator, protocol_version="v2")

    def test_conflicting_revision_and_version_overrides_raise(self):
        mock_decorator = MagicMock()
        with pytest.raises(ValueError, match="Pass either protocol_revision or protocol_version"):
            create_mcp_tool_adapter(
                mock_decorator,
                protocol_revision="2025-11-25",
                protocol_version="v1",
            )

    def test_default_revision_uses_env(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_REVISION", "2025-11-25")
        mock_decorator = MagicMock()
        adapter = create_mcp_tool_adapter(mock_decorator)
        assert adapter is mock_decorator
