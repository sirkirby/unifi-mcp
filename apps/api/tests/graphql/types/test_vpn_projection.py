"""The REST/GraphQL VPN path is safe by *projection*: VpnClient/VpnServer expose
only an allowlisted field set, so secret-bearing controller fields (config blobs,
private keys) can never reach the API output regardless of redaction (issue #351).
"""

from __future__ import annotations

from unifi_api.graphql.types.network.vpn import VpnClient, VpnServer

# Sentinel values that must never appear in the projected output.
_SECRET_SENTINELS = (
    "PrivateKey = TEST_FAKE",
    "BEGIN OpenVPN Static key",
    "TEST_FAKE_PRIVATE_KEY",
)


def test_vpn_client_projection_drops_secret_and_blob_fields() -> None:
    raw = {
        "_id": "vc-1",
        "name": "Home-VPN",
        "vpn_type": "wireguard-client",
        "enabled": True,
        "wireguard_client_peer_endpoint": "203.0.113.1:51820",
        # Secret-bearing fields the projection must not surface:
        "wireguard_client_configuration_file": "[Interface]\nPrivateKey = TEST_FAKE_PRIVATE_KEY_aaaa=\n",
        "wireguard_client_private_key": "TEST_FAKE_PRIVATE_KEY_bbbb=",
        "openvpn_configuration": "<tls-crypt>\n-----BEGIN OpenVPN Static key V1-----\n",
        "x_openvpn_password": "TEST_FAKE_PASSWORD",
    }

    projected = VpnClient.from_manager_output(raw).to_dict()

    for secret_key in (
        "wireguard_client_configuration_file",
        "wireguard_client_private_key",
        "openvpn_configuration",
        "x_openvpn_password",
    ):
        assert secret_key not in projected
    blob = " ".join(str(v) for v in projected.values())
    assert not any(s in blob for s in _SECRET_SENTINELS)


def test_vpn_server_projection_drops_private_key() -> None:
    raw = {
        "_id": "vs-1",
        "name": "Main-Server",
        "vpn_type": "wireguard-server",
        "enabled": True,
        "x_wireguard_private_key": "TEST_FAKE_PRIVATE_KEY_cccc=",
        "wireguard_public_key": "fake-public",
    }

    projected = VpnServer.from_manager_output(raw).to_dict()

    assert "x_wireguard_private_key" not in projected
    blob = " ".join(str(v) for v in projected.values())
    assert "TEST_FAKE_PRIVATE_KEY" not in blob
