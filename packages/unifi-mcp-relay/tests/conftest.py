"""Shared fixtures for unifi-mcp-relay tests."""

import pytest

from unifi_mcp_relay.config import RelayConfig
from unifi_mcp_relay.protocol import ToolInfo


@pytest.fixture
def sample_tools():
    return [
        ToolInfo(
            name="unifi_list_devices",
            description="List all UniFi network devices",
            input_schema={"type": "object", "properties": {"compact": {"type": "boolean"}}},
            annotations={"readOnlyHint": True, "openWorldHint": False},
            server_origin="unifi-network-mcp",
        ),
        ToolInfo(
            name="unifi_reboot_device",
            description="Reboot a device",
            input_schema={"type": "object", "properties": {"mac": {"type": "string"}}, "required": ["mac"]},
            annotations={"readOnlyHint": False, "destructiveHint": True},
            server_origin="unifi-network-mcp",
        ),
    ]
