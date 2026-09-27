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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "function", "method", "kwargs"),
    [
        ("switch", "get_switch_ports", "get_switch_ports", {}),
        ("switch", "get_port_stats", "get_port_stats", {}),
        ("switch", "get_lldp_neighbors", "get_lldp_neighbors", {}),
        ("switch", "get_switch_capabilities", "get_switch_capabilities", {}),
        (
            "switch",
            "set_switch_port_profile",
            "set_port_overrides",
            {"port_overrides": [{"port_idx": 1}], "confirm": True},
        ),
        ("switch", "power_cycle_port", "power_cycle_port", {"port_idx": 1, "confirm": True}),
        (
            "switch",
            "configure_port_mirror",
            "set_port_overrides",
            {"port_overrides": [{"port_idx": 1, "op_mode": "mirror", "mirror_port_idx": 2}], "confirm": True},
        ),
        (
            "switch",
            "configure_port_aggregation",
            "set_port_overrides",
            {
                "port_overrides": [{"port_idx": 1, "op_mode": "aggregate", "aggregate_members": [1, 2], "lag_idx": 1}],
                "confirm": True,
            },
        ),
        ("switch", "update_switch_stp", "update_device_config", {"confirm": True}),
        ("switch", "set_jumbo_frames", "update_device_config", {"enabled": True, "confirm": True}),
        ("stats", "get_client_dpi_traffic", "get_client_dpi_traffic", {}),
        ("stats", "get_client_wifi_details", "get_client_wifi_details", {}),
        ("stats", "get_client_sessions", "get_client_sessions", {}),
    ],
)
async def test_mac_tool_failures_keep_private_values_out_of_diagnostics(
    module: str, function: str, method: str, kwargs: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """Raw manager exceptions must not reintroduce MACs or controller secrets."""
    import logging

    target = importlib.import_module(f"unifi_network_mcp.tools.{module}")
    canary = "private-controller-canary"
    manager = MagicMock()
    failing = AsyncMock(side_effect=RuntimeError(f"{MAC} {canary}"))
    setattr(manager, method, failing)
    with patch.object(target, f"{module}_manager", manager), caplog.at_level(logging.DEBUG):
        result = await getattr(target, function)(mac_address=MAC, **kwargs)
    failing.assert_awaited_once()
    assert result["success"] is False
    assert "Failed to" in result["error"] and "RuntimeError" in result["error"]
    for value in (MAC, canary):
        assert value not in caplog.text
        assert value not in result["error"]
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_recent_event_filter_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from unifi_network_mcp.tools.events import unifi_recent_events

    manager = MagicMock()
    manager.get_recent_from_buffer.return_value = []
    with (
        patch("unifi_network_mcp.tools.events._get_event_manager", return_value=manager),
        caplog.at_level(logging.INFO),
    ):
        result = await unifi_recent_events(mac_address=MAC, event_type="private-filter-canary")
    assert result["success"] is True
    assert MAC not in caplog.text
    assert "private-filter-canary" not in caplog.text
