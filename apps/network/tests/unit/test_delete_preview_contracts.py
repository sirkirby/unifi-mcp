"""Regression tests for delete-tool preview response contracts."""

import importlib
import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.redaction import REDACTED

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


DELETE_PREVIEW_CASES = [
    (
        "unifi_network_mcp.tools.client_groups",
        "delete_client_group",
        {"group_id": "group-1"},
        "client_group",
        "group-1",
        {"group_id": "group-1"},
    ),
    (
        "unifi_network_mcp.tools.content_filtering",
        "delete_content_filter",
        {"filter_id": "filter-1"},
        "content_filter",
        "filter-1",
        {"filter_id": "filter-1"},
    ),
    (
        "unifi_network_mcp.tools.dns",
        "delete_dns_record",
        {"record_id": "dns-1"},
        "dns_record",
        "dns-1",
        {"record_id": "dns-1"},
    ),
    (
        "unifi_network_mcp.tools.dynamic_dns",
        "delete_dynamic_dns",
        {"entry_id": "ddns-1"},
        "dynamic_dns",
        "ddns-1",
        {"entry_id": "ddns-1"},
    ),
    (
        "unifi_network_mcp.tools.firewall",
        "delete_firewall_group",
        {"group_id": "firewall-group-1"},
        "firewall_group",
        "firewall-group-1",
        {"group_id": "firewall-group-1"},
    ),
    (
        "unifi_network_mcp.tools.firewall",
        "delete_firewall_policy",
        {"policy_id": "policy-1"},
        "firewall_policy",
        "policy-1",
        {"policy_id": "policy-1"},
    ),
    (
        "unifi_network_mcp.tools.oon",
        "delete_oon_policy",
        {"policy_id": "oon-1"},
        "oon_policy",
        "oon-1",
        {"policy_id": "oon-1"},
    ),
    (
        "unifi_network_mcp.tools.switch",
        "delete_port_profile",
        {"profile_id": "profile-1"},
        "port_profile",
        "profile-1",
        {"profile_id": "profile-1"},
    ),
    (
        "unifi_network_mcp.tools.system",
        "delete_backup",
        {"filename": "backup.unf"},
        "backup",
        "backup.unf",
        {"filename": "backup.unf"},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "function_name", "arguments", "resource_type", "resource_id", "resource_data"),
    DELETE_PREVIEW_CASES,
)
async def test_delete_tool_preview_contract(
    module_name,
    function_name,
    arguments,
    resource_type,
    resource_id,
    resource_data,
):
    module = importlib.import_module(module_name)
    delete_tool = getattr(module, function_name)

    result = await delete_tool(**arguments, confirm=False)

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["action"] == "delete"
    assert result["resource_type"] == resource_type
    assert result["resource_id"] == resource_id
    assert result["preview"]["will_delete"] == resource_data
    assert result["message"].startswith(f"Will delete {resource_type}")


@pytest.mark.asyncio
async def test_delete_ap_group_preview_contract():
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_manager:
        mock_manager.get_ap_group_details = AsyncMock(return_value={"name": "Upstairs APs"})
        from unifi_network_mcp.tools.network import delete_ap_group

        result = await delete_ap_group(group_id="ap-group-1", confirm=False)

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["action"] == "delete"
    assert result["resource_type"] == "ap_group"
    assert result["resource_id"] == "ap-group-1"
    assert result["preview"]["will_delete"] == {
        "group_id": "ap-group-1",
        "name": "Upstairs APs",
    }
    assert result["message"] == "Will delete ap_group 'Upstairs APs'. Set confirm=true to execute."


@pytest.mark.asyncio
async def test_delete_wlan_preview_contract_redacts_passphrase():
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_manager:
        mock_manager.get_wlan_details = AsyncMock(
            return_value={
                "name": "Guest WiFi",
                "enabled": True,
                "security": "wpapsk",
                "x_passphrase": "do-not-return-this",
            }
        )
        from unifi_network_mcp.tools.network import delete_wlan

        result = await delete_wlan(wlan_id="wlan-1", confirm=False)

    assert result["success"] is True
    assert result["requires_confirmation"] is True
    assert result["action"] == "delete"
    assert result["resource_type"] == "wlan"
    assert result["resource_id"] == "wlan-1"
    assert result["preview"]["will_delete"] == {
        "wlan_id": "wlan-1",
        "name": "Guest WiFi",
        "enabled": True,
        "security": "wpapsk",
        "x_passphrase": REDACTED,
    }
    assert result["message"] == "Will delete wlan 'Guest WiFi'. Set confirm=true to execute."
