"""Public subject-MAC names delegate to existing Core manager signatures."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MAC = "aa:bb:cc:dd:ee:ff"
DEVICE_TOOLS = (
    "unifi_configure_port_aggregation",
    "unifi_configure_port_mirror",
    "unifi_force_provision_device",
    "unifi_get_lldp_neighbors",
    "unifi_get_port_stats",
    "unifi_get_switch_capabilities",
    "unifi_get_switch_ports",
    "unifi_locate_device",
    "unifi_power_cycle_port",
    "unifi_set_device_led",
    "unifi_set_jumbo_frames",
    "unifi_set_switch_port_profile",
    "unifi_toggle_device",
    "unifi_update_switch_stp",
)
CLIENT_TOOLS = ("unifi_get_client_dpi_traffic", "unifi_get_client_sessions", "unifi_get_client_wifi_details")
FUNCTIONS = {
    "unifi_configure_port_aggregation": ("switch", "configure_port_aggregation"),
    "unifi_configure_port_mirror": ("switch", "configure_port_mirror"),
    "unifi_force_provision_device": ("devices", "force_provision_device"),
    "unifi_get_lldp_neighbors": ("switch", "get_lldp_neighbors"),
    "unifi_get_port_stats": ("switch", "get_port_stats"),
    "unifi_get_switch_capabilities": ("switch", "get_switch_capabilities"),
    "unifi_get_switch_ports": ("switch", "get_switch_ports"),
    "unifi_locate_device": ("devices", "locate_device"),
    "unifi_power_cycle_port": ("switch", "power_cycle_port"),
    "unifi_set_device_led": ("devices", "set_device_led"),
    "unifi_set_jumbo_frames": ("switch", "set_jumbo_frames"),
    "unifi_set_switch_port_profile": ("switch", "set_switch_port_profile"),
    "unifi_toggle_device": ("devices", "toggle_device"),
    "unifi_update_switch_stp": ("switch", "update_switch_stp"),
    "unifi_get_client_dpi_traffic": ("stats", "get_client_dpi_traffic"),
    "unifi_get_client_sessions": ("stats", "get_client_sessions"),
    "unifi_get_client_wifi_details": ("stats", "get_client_wifi_details"),
    "unifi_recent_events": ("events", "unifi_recent_events"),
}


@pytest.mark.parametrize("tool", [*DEVICE_TOOLS, *CLIENT_TOOLS, "unifi_recent_events"])
def test_public_signature_has_only_mac_address(tool: str) -> None:
    module_name, function_name = FUNCTIONS[tool]
    function = getattr(importlib.import_module(f"unifi_network_mcp.tools.{module_name}"), function_name)
    params = inspect.signature(function).parameters
    assert "mac_address" in params
    assert not {"device_mac", "client_mac", "mac"} & params.keys()
    expected_default = None if tool in {"unifi_get_client_sessions", "unifi_recent_events"} else inspect.Parameter.empty
    assert params["mac_address"].default is expected_default


def test_ap_mac_keeps_its_distinct_rf_scan_role() -> None:
    from unifi_network_mcp.tools.devices import trigger_rf_scan

    params = inspect.signature(trigger_rf_scan).parameters
    assert "ap_mac" in params
    assert "mac_address" not in params


def test_no_network_tool_keeps_a_legacy_subject_mac_parameter() -> None:
    tools_dir = Path(__file__).resolve().parents[2] / "src" / "unifi_network_mcp" / "tools"
    found = []
    for path in tools_dir.glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if not any(isinstance(decorator, ast.Call) for decorator in node.decorator_list):
                continue
            legacy = {arg.arg for arg in node.args.args} & {"device_mac", "client_mac", "mac"}
            if legacy:
                found.append((path.name, node.name, sorted(legacy)))
    assert found == []


@pytest.mark.asyncio
async def test_switch_read_and_device_mutation_delegate_new_name() -> None:
    from unifi_network_mcp.tools.devices import locate_device
    from unifi_network_mcp.tools.switch import get_switch_ports

    with patch("unifi_network_mcp.tools.switch.switch_manager") as switch:
        switch.get_switch_ports = AsyncMock(return_value={"ports": []})
        result = await get_switch_ports(mac_address=MAC)
        assert result["success"] is True
        switch.get_switch_ports.assert_awaited_once_with(MAC)
    with patch("unifi_network_mcp.tools.devices.device_manager") as device:
        device.locate_device = AsyncMock(return_value=True)
        result = await locate_device(mac_address=MAC, enabled=True, confirm=True)
        assert result["success"] is True
        device.locate_device.assert_awaited_once_with(MAC, True)


@pytest.mark.asyncio
async def test_optional_client_and_event_filters_preserve_omission() -> None:
    from unifi_network_mcp.tools.events import unifi_recent_events
    from unifi_network_mcp.tools.stats import get_client_sessions

    with patch("unifi_network_mcp.tools.stats.stats_manager") as stats:
        stats._connection.site = "default"
        stats.get_client_sessions = AsyncMock(return_value=[])
        assert (await get_client_sessions())["success"] is True
        stats.get_client_sessions.assert_awaited_with(client_mac=None, duration_hours=24, limit=50)
        assert (await get_client_sessions(mac_address=MAC))["success"] is True
        stats.get_client_sessions.assert_awaited_with(client_mac=MAC, duration_hours=24, limit=50)
    manager = MagicMock()
    manager.get_recent_from_buffer.return_value = []
    with patch("unifi_network_mcp.tools.events._get_event_manager", return_value=manager):
        assert (await unifi_recent_events())["success"] is True
        manager.get_recent_from_buffer.assert_called_with(event_type=None, mac=None, limit=None)
        assert (await unifi_recent_events(mac_address=MAC))["success"] is True
        manager.get_recent_from_buffer.assert_called_with(event_type=None, mac=MAC, limit=None)
