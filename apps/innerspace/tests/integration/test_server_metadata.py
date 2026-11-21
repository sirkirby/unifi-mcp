"""MCP server metadata exposed during initialization."""

from __future__ import annotations

from unifi_mcp_shared.testing import assert_server_initialization_metadata


def test_server_initialization_metadata() -> None:
    from unifi_innerspace_mcp.runtime import server

    assert_server_initialization_metadata(server, package_name="unifi-innerspace-mcp")
