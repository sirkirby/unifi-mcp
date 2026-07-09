"""Tests for MCP protocol abstraction layer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from unifi_mcp_shared.protocol import (
    DEFAULT_MCP_PROTOCOL_REVISION,
    FUTURE_MCP_PROTOCOL_REVISION,
    create_mcp_tool_adapter,
    get_protocol_revision,
    get_request_protocol_revision,
    is_known_protocol_target,
    structured_content_supported,
)


@pytest.mark.parametrize("revision", ["2025-06-18", "2025-11-25", "2026-07-28", "2027-01-01"])
def test_structured_content_supported_for_current_and_future_revisions(revision):
    assert structured_content_supported(revision) is True


@pytest.mark.parametrize("revision", [None, "", "2024-11-05", "2025-03-26", "not-a-date"])
def test_structured_content_not_assumed_for_old_or_unknown_revisions(revision):
    assert structured_content_supported(revision) is False


def test_request_protocol_revision_reads_current_sdk_session():
    server = MagicMock()
    server.get_context.return_value.session.client_params.protocolVersion = "2025-11-25"
    assert get_request_protocol_revision(server) == "2025-11-25"


def test_request_protocol_revision_returns_none_outside_request():
    server = MagicMock()
    server.get_context.side_effect = ValueError("Context is not available outside of a request")
    assert get_request_protocol_revision(server) is None


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

    def test_future_revision_is_known_target(self):
        assert FUTURE_MCP_PROTOCOL_REVISION == "2026-07-28"
        assert is_known_protocol_target("2026-07-28") is True

    def test_unknown_revision_is_not_known_target(self):
        assert is_known_protocol_target("2026-06-18") is False


class TestCreateMcpToolAdapter:
    """Test the tool decorator adapter factory."""

    def test_current_revision_returns_original_decorator(self):
        mock_decorator = MagicMock(name="fastmcp_tool_decorator")
        adapter = create_mcp_tool_adapter(mock_decorator, protocol_revision="2025-11-25")
        assert adapter is mock_decorator

    def test_legacy_v1_revision_alias_returns_original_decorator(self):
        mock_decorator = MagicMock(name="fastmcp_tool_decorator")
        adapter = create_mcp_tool_adapter(mock_decorator, protocol_revision="v1")
        assert adapter is mock_decorator

    def test_unsupported_revision_raises(self):
        mock_decorator = MagicMock()
        with pytest.raises(ValueError, match="Unsupported MCP protocol revision"):
            create_mcp_tool_adapter(mock_decorator, protocol_revision="2026-06-18")

    def test_future_target_revision_is_not_runtime_supported(self):
        mock_decorator = MagicMock()
        with pytest.raises(ValueError, match="Unsupported MCP protocol revision"):
            create_mcp_tool_adapter(mock_decorator, protocol_revision="2026-07-28")

    def test_v2_revision_alias_raises(self):
        mock_decorator = MagicMock()
        with pytest.raises(ValueError, match="Use date-based MCP protocol revisions"):
            create_mcp_tool_adapter(mock_decorator, protocol_revision="v2")

    def test_default_revision_uses_env(self, monkeypatch):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_REVISION", "2025-11-25")
        mock_decorator = MagicMock()
        adapter = create_mcp_tool_adapter(mock_decorator)
        assert adapter is mock_decorator
