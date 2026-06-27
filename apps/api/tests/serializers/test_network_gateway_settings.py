"""Gateway (USG) settings — Strawberry type round-trip projection.

Guards against a typo in any from_manager_output raw.get() key (which would
silently null the GraphQL/REST field; cross-layer symmetry checks the field
name, not the .get() key)."""

from unifi_api.graphql.types.network.gateway_settings import GatewaySettings


def test_gateway_settings_round_trip() -> None:
    class FakeSettings:
        raw = {
            "_id": "usg1",
            "key": "usg",
            "geo_ip_filtering_enabled": False,
            "geo_ip_filtering_block": "block",
            "geo_ip_filtering_traffic_direction": "both",
            "syn_cookies": True,
            "send_redirects": True,
            "dns_verification": {
                "setting_preference": "auto",
                "primary_dns_server": "1.1.1.1",
                "secondary_dns_server": "8.8.8.8",
            },
            "upnp_enabled": False,
            "upnp_wan_interface": "WAN",
            "mss_clamp": "auto",
            "ftp_module": True,
            "offload_sch": True,
            "tcp_established_timeout": 7440,
            "timeout_setting_preference": "auto",
            "unbind_wan_monitors": False,
        }

    out = GatewaySettings.from_manager_output(FakeSettings()).to_dict()
    assert out["id"] == "usg1"
    assert out["key"] == "usg"
    assert out["geo_ip_filtering_enabled"] is False
    assert out["geo_ip_filtering_traffic_direction"] == "both"
    assert out["syn_cookies"] is True
    assert out["send_redirects"] is True
    # nested object projects intact
    assert out["dns_verification"]["primary_dns_server"] == "1.1.1.1"
    assert out["dns_verification"]["secondary_dns_server"] == "8.8.8.8"
    assert out["upnp_enabled"] is False
    assert out["upnp_wan_interface"] == "WAN"
    assert out["mss_clamp"] == "auto"
    assert out["ftp_module"] is True
    assert out["offload_sch"] is True
    assert out["tcp_established_timeout"] == 7440
    assert out["timeout_setting_preference"] == "auto"
    assert out["unbind_wan_monitors"] is False


def test_gateway_settings_from_plain_dict_missing_keys() -> None:
    out = GatewaySettings.from_manager_output({"_id": "x", "key": "usg", "upnp_enabled": True}).to_dict()
    assert out["id"] == "x"
    assert out["upnp_enabled"] is True
    assert out["dns_verification"] is None
    assert out["tcp_established_timeout"] is None
