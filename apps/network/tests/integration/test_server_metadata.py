"""MCP server metadata exposed during initialization."""

from __future__ import annotations

import os

from unifi_mcp_shared.testing import assert_server_initialization_metadata

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


def test_server_initialization_metadata() -> None:
    from unifi_network_mcp.runtime import server

    assert_server_initialization_metadata(server, package_name="unifi-network-mcp")
