"""Shared fixtures for unifi-mcp-relay tests."""

import sys
from pathlib import Path

# Scrub inherited controller settings and block outbound network access before
# anything imports the code under test; see testsupport/unifi_test_guard.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "testsupport"))
import unifi_test_guard  # noqa: E402

unifi_test_guard.protect_test_session()

from unifi_test_guard import fail_on_outbound_network_access, pytest_configure  # noqa: E402,F401

stub_automatic_controller_connects = unifi_test_guard.connect_stub()

import pytest  # noqa: E402
from unifi_mcp_relay.protocol import ToolInfo  # noqa: E402


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
