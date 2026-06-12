"""Tests for VPN MCP tool response redaction."""

from unittest.mock import AsyncMock, patch

import pytest
from unifi_core.redaction import REDACTED


@pytest.mark.asyncio
async def test_list_vpn_clients_redacts_by_default_and_allows_opt_out() -> None:
    secret_client = {"_id": "vpn1", "name": "VPN", "wireguard_private_key": "private", "preshared_key": "psk"}
    with patch("unifi_network_mcp.tools.vpn.vpn_manager") as mock_mgr:
        mock_mgr.get_vpn_clients = AsyncMock(return_value=[secret_client])
        mock_mgr._connection.site = "default"

        from unifi_network_mcp.tools.vpn import list_vpn_clients

        default = await list_vpn_clients()
        raw = await list_vpn_clients(include_sensitive=True)

    assert default["vpn_clients"][0]["wireguard_private_key"] == REDACTED
    assert default["vpn_clients"][0]["preshared_key"] == REDACTED
    assert raw["vpn_clients"][0]["wireguard_private_key"] == "private"
    assert raw["vpn_clients"][0]["preshared_key"] == "psk"


@pytest.mark.asyncio
async def test_get_vpn_server_details_redacts_by_default_and_allows_opt_out() -> None:
    secret_server = {"_id": "vpn1", "name": "VPN", "wireguard_private_key": "private", "preshared_key": "psk"}
    with patch("unifi_network_mcp.tools.vpn.vpn_manager") as mock_mgr:
        mock_mgr.get_vpn_server_details = AsyncMock(return_value=secret_server)
        mock_mgr._connection.site = "default"

        from unifi_network_mcp.tools.vpn import get_vpn_server_details

        default = await get_vpn_server_details("vpn1")
        raw = await get_vpn_server_details("vpn1", include_sensitive=True)

    assert default["details"]["wireguard_private_key"] == REDACTED
    assert default["details"]["preshared_key"] == REDACTED
    assert raw["details"]["wireguard_private_key"] == "private"
    assert raw["details"]["preshared_key"] == "psk"
