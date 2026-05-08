"""Integration test: StrictKwargFastMCP wiring in unifi-network-mcp runtime.

Confirms the runtime's server is a StrictKwargFastMCP instance and that
call_tool with an unknown kwarg raises a structured ToolError BEFORE any
tool body runs (no live controller required).
"""

from __future__ import annotations

import os

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


@pytest.mark.asyncio
async def test_strict_dispatch_rejects_unknown_kwarg() -> None:
    """server.call_tool with a bogus kwarg surfaces a structured ToolError."""
    from unifi_network_mcp.runtime import server

    assert isinstance(server, StrictKwargFastMCP), (
        "runtime.server must be StrictKwargFastMCP for transport-layer kwarg validation"
    )

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "unifi_list_firewall_zones",
            {"BOGUS_PROBE_KEY": "x"},
        )

    msg = str(excinfo.value)
    assert "unifi_list_firewall_zones" in msg
    assert "BOGUS_PROBE_KEY" in msg
    assert "Valid arguments" in msg
