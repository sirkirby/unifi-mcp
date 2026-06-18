"""Tests for VPN MCP tool response redaction.

Fixtures mirror the *real* UniFi ``networkconf`` field names (issue #351) with
synthetic values — never live secret material. The controller stores VPN
secrets two ways: discrete role-infixed keys (WireGuard "manual" mode) and a
whole config blob (WireGuard "file" mode and OpenVPN).
"""

from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.redaction import REDACTED

# WireGuard "file" mode: the secret rides inside a config-blob string.
_WG_FILE_CLIENT = {
    "_id": "wg-file",
    "name": "WG File",
    "vpn_type": "wireguard-client",
    "wireguard_client_mode": "file",
    "wireguard_client_configuration_filename": "wg-test.conf",
    "wireguard_client_configuration_file": (
        "[Interface]\nPrivateKey = TEST_FAKE_PRIVATE_KEY_aaaaaaaaaaaaaaaaaaaaaa=\n"
        "Address = 10.0.0.2/32\n\n[Peer]\nPublicKey = TEST_FAKE_PUBLIC_KEY_bbbbbbbbbbbbbb=\n"
        "Endpoint = 203.0.113.1:51820\n"
    ),
}

# WireGuard "manual" mode: discrete role-infixed secret fields.
_WG_MANUAL_CLIENT = {
    "_id": "wg-manual",
    "name": "WG Manual",
    "vpn_type": "wireguard-client",
    "wireguard_client_mode": "manual",
    "wireguard_client_private_key": "TEST_FAKE_PRIVATE_KEY_cccccccccccccccc=",
    "wireguard_client_preshared_key": "TEST_FAKE_PSK_dddddddddddddddddddddd=",
    "wireguard_client_public_key": "TEST_FAKE_PUBLIC_KEY_eeeeeeeeeeeeee=",
}

# OpenVPN: whole .ovpn blob (embeds tls-crypt static key, certs) + discrete password.
_OPENVPN_CLIENT = {
    "_id": "ovpn",
    "name": "OpenVPN",
    "vpn_type": "openvpn-client",
    "openvpn_configuration_status": "VALID",
    "openvpn_configuration_filename": "test.ovpn",
    "openvpn_configuration": (
        "client\ndev tun\n<tls-crypt>\n-----BEGIN OpenVPN Static key V1-----\n"
        "deadbeefdeadbeefdeadbeefdeadbeef\n-----END OpenVPN Static key V1-----\n</tls-crypt>\n"
    ),
    "x_openvpn_password": "TEST_FAKE_PASSWORD",
}


@pytest.mark.asyncio
async def test_list_vpn_clients_redacts_by_default_and_uses_policy_opt_out(monkeypatch) -> None:
    clients = [_WG_FILE_CLIENT, _WG_MANUAL_CLIENT, _OPENVPN_CLIENT]
    with patch("unifi_network_mcp.tools.vpn.vpn_manager") as mock_mgr:
        mock_mgr.get_vpn_clients = AsyncMock(return_value=clients)
        mock_mgr._connection.site = "default"

        from unifi_network_mcp.tools.vpn import list_vpn_clients

        default = await list_vpn_clients()
        monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", "false")
        raw = await list_vpn_clients()

    wg_file, wg_manual, ovpn = default["vpn_clients"]

    # WireGuard file-mode config blob (the issue #351 leak) is fully suppressed.
    assert wg_file["wireguard_client_configuration_file"] == REDACTED
    # Non-secret sibling metadata stays visible.
    assert wg_file["wireguard_client_configuration_filename"] == "wg-test.conf"
    assert wg_file["wireguard_client_mode"] == "file"

    # WireGuard manual-mode discrete secret fields are redacted; public key isn't.
    assert wg_manual["wireguard_client_private_key"] == REDACTED
    assert wg_manual["wireguard_client_preshared_key"] == REDACTED
    assert wg_manual["wireguard_client_public_key"] != REDACTED

    # OpenVPN config blob + password redacted; status/filename stay visible.
    assert ovpn["openvpn_configuration"] == REDACTED
    assert ovpn["x_openvpn_password"] == REDACTED
    assert ovpn["openvpn_configuration_status"] == "VALID"
    assert ovpn["openvpn_configuration_filename"] == "test.ovpn"

    # Operator policy opt-out returns everything raw.
    raw_wg_file, raw_wg_manual, raw_ovpn = raw["vpn_clients"]
    assert "PrivateKey" in raw_wg_file["wireguard_client_configuration_file"]
    assert raw_wg_manual["wireguard_client_private_key"].startswith("TEST_FAKE_PRIVATE_KEY")
    assert "BEGIN OpenVPN Static key" in raw_ovpn["openvpn_configuration"]


@pytest.mark.asyncio
async def test_get_vpn_client_details_redacts_config_blob_by_default(monkeypatch) -> None:
    with patch("unifi_network_mcp.tools.vpn.vpn_manager") as mock_mgr:
        mock_mgr.get_vpn_client_details = AsyncMock(return_value=dict(_WG_FILE_CLIENT))
        mock_mgr._connection.site = "default"

        from unifi_network_mcp.tools.vpn import get_vpn_client_details

        default = await get_vpn_client_details("wg-file")
        monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", "false")
        raw = await get_vpn_client_details("wg-file")

    assert default["details"]["wireguard_client_configuration_file"] == REDACTED
    assert "PrivateKey" in raw["details"]["wireguard_client_configuration_file"]


# WireGuard server (real networkconf field names): discrete x_-prefixed key.
_WG_SERVER = {
    "_id": "srv",
    "name": "WG Server",
    "vpn_type": "wireguard-server",
    "x_wireguard_private_key": "TEST_FAKE_SERVER_PRIVATE_KEY_ffffffffff=",
    "wireguard_public_key": "TEST_FAKE_SERVER_PUBLIC_KEY_gggggggggg=",
}


@pytest.mark.asyncio
async def test_list_vpn_servers_redacts_private_key_keeps_public(monkeypatch) -> None:
    with patch("unifi_network_mcp.tools.vpn.vpn_manager") as mock_mgr:
        mock_mgr.get_vpn_servers = AsyncMock(return_value=[dict(_WG_SERVER)])
        mock_mgr._connection.site = "default"

        from unifi_network_mcp.tools.vpn import list_vpn_servers

        default = await list_vpn_servers()
        monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", "false")
        raw = await list_vpn_servers()

    server = default["vpn_servers"][0]
    assert server["x_wireguard_private_key"] == REDACTED
    # The public key is not secret and must stay visible.
    assert server["wireguard_public_key"] != REDACTED
    assert raw["vpn_servers"][0]["x_wireguard_private_key"].startswith("TEST_FAKE_SERVER_PRIVATE_KEY")
