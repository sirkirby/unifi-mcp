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


@pytest.mark.parametrize(
    "revision",
    [None, "", "2024-11-05", "2025-03-26", "not-a-date", "20250618", "2025-W25-3"],
)
def test_structured_content_not_assumed_for_old_or_unknown_revisions(revision):
    assert structured_content_supported(revision) is False


def test_request_protocol_revision_reads_current_sdk_session():
    context = MagicMock()
    context.request_context.protocol_version = "2025-11-25"
    assert get_request_protocol_revision(context) == "2025-11-25"


def test_request_protocol_revision_returns_none_outside_request():
    assert get_request_protocol_revision(None) is None


class TestGetProtocolRevision:
    """Test protocol revision resolution from env vars."""

    @pytest.mark.parametrize(
        ("rev_env", "ver_env", "expected"),
        [
            (None, None, DEFAULT_MCP_PROTOCOL_REVISION),
            ("2025-11-25", None, "2025-11-25"),
            ("  2025-11-25  ", None, "2025-11-25"),
            ("2025-11-25", "v1", "2025-11-25"),
            (None, "v1", DEFAULT_MCP_PROTOCOL_REVISION),
        ],
    )
    def test_get_protocol_revision(self, monkeypatch, rev_env, ver_env, expected):
        if rev_env is None:
            monkeypatch.delenv("UNIFI_MCP_PROTOCOL_REVISION", raising=False)
        else:
            monkeypatch.setenv("UNIFI_MCP_PROTOCOL_REVISION", rev_env)
        if ver_env is None:
            monkeypatch.delenv("UNIFI_MCP_PROTOCOL_VERSION", raising=False)
        else:
            monkeypatch.setenv("UNIFI_MCP_PROTOCOL_VERSION", ver_env)
        assert get_protocol_revision() == expected

    @pytest.mark.parametrize(
        ("rev", "expected"),
        [
            (FUTURE_MCP_PROTOCOL_REVISION, True),
            ("2026-06-18", False),
        ],
    )
    def test_is_known_protocol_target(self, rev, expected):
        assert FUTURE_MCP_PROTOCOL_REVISION == "2026-07-28"
        assert is_known_protocol_target(rev) is expected


class TestCreateMcpToolAdapter:
    """Test the tool decorator adapter factory."""

    @pytest.mark.parametrize("protocol_revision", ["2025-11-25", "v1", "2026-07-28", None])
    def test_returns_original_decorator(self, monkeypatch, protocol_revision):
        monkeypatch.setenv("UNIFI_MCP_PROTOCOL_REVISION", "2025-11-25")
        mock_decorator = MagicMock(name="fastmcp_tool_decorator")
        adapter = (
            create_mcp_tool_adapter(mock_decorator)
            if protocol_revision is None
            else create_mcp_tool_adapter(mock_decorator, protocol_revision=protocol_revision)
        )
        assert adapter is mock_decorator

    def test_unknown_revision_is_ignored_for_per_client_negotiation(self, caplog):
        mock_decorator = MagicMock()
        adapter = create_mcp_tool_adapter(mock_decorator, protocol_revision="2026-06-18")
        assert adapter is mock_decorator
        assert "negotiates the protocol per client" in caplog.text

    def test_v2_revision_alias_raises(self):
        mock_decorator = MagicMock()
        with pytest.raises(ValueError, match="Use date-based MCP protocol revisions"):
            create_mcp_tool_adapter(mock_decorator, protocol_revision="v2")
