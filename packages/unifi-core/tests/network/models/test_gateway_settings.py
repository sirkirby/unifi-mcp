"""Tests for the gateway (USG) settings shared model."""

from unifi_core.network.models.gateway_settings import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    from_controller,
    to_controller_update,
)

SAMPLE_USG = {
    "_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
    "site_id": "bbbbbbbbbbbbbbbbbbbbbbbb",
    "key": "usg",
    "geo_ip_filtering_enabled": False,
    "geo_ip_filtering_block": "block",
    "geo_ip_filtering_countries": "",
    "geo_ip_filtering_traffic_direction": "both",
    "syn_cookies": True,
    "broadcast_ping": False,
    "receive_redirects": False,
    "send_redirects": True,
    "dns_verification": {
        "setting_preference": "auto",
        "primary_dns_server": "1.1.1.1",
        "domain": "ui.com",
        "secondary_dns_server": "8.8.8.8",
    },
    "upnp_enabled": False,
    "upnp_nat_pmp_enabled": False,
    "upnp_secure_mode": False,
    "upnp_wan_interface": "WAN",
    "mss_clamp": "auto",
    "ftp_module": True,
    "gre_module": True,
    "h323_module": True,
    "pptp_module": True,
    "sip_module": True,
    "tftp_module": True,
    "offload_accounting": True,
    "offload_l2_blocking": True,
    "offload_sch": True,
    "icmp_timeout": 30,
    "other_timeout": 600,
    "udp_stream_timeout": 180,
    "udp_other_timeout": 30,
    "tcp_established_timeout": 7440,
    "tcp_close_timeout": 10,
    "tcp_close_wait_timeout": 60,
    "tcp_fin_wait_timeout": 120,
    "tcp_last_ack_timeout": 30,
    "tcp_syn_recv_timeout": 60,
    "tcp_syn_sent_timeout": 120,
    "tcp_time_wait_timeout": 120,
    "timeout_setting_preference": "auto",
    "unbind_wan_monitors": False,
}


class TestFromController:
    def test_identity_and_key(self):
        m = from_controller(SAMPLE_USG)
        assert m.id == "aaaaaaaaaaaaaaaaaaaaaaaa"
        assert m.site_id == "bbbbbbbbbbbbbbbbbbbbbbbb"
        assert m.key == "usg"

    def test_security_fields(self):
        m = from_controller(SAMPLE_USG)
        assert m.geo_ip_filtering_enabled is False
        assert m.geo_ip_filtering_block == "block"
        assert m.geo_ip_filtering_traffic_direction == "both"
        assert m.syn_cookies is True
        assert m.send_redirects is True

    def test_nested_dns_verification_preserved(self):
        m = from_controller(SAMPLE_USG)
        assert isinstance(m.dns_verification, dict)
        assert m.dns_verification["primary_dns_server"] == "1.1.1.1"
        assert m.dns_verification["secondary_dns_server"] == "8.8.8.8"
        assert m.dns_verification["domain"] == "ui.com"

    def test_nat_upnp_fields(self):
        m = from_controller(SAMPLE_USG)
        assert m.upnp_enabled is False
        assert m.upnp_wan_interface == "WAN"
        assert m.mss_clamp == "auto"

    def test_conntrack_timeouts_are_ints(self):
        m = from_controller(SAMPLE_USG)
        assert m.tcp_established_timeout == 7440
        assert m.icmp_timeout == 30
        assert m.timeout_setting_preference == "auto"

    def test_module_and_offload_flags(self):
        m = from_controller(SAMPLE_USG)
        assert m.ftp_module is True
        assert m.sip_module is True
        assert m.offload_sch is True

    def test_missing_keys_default_none(self):
        m = from_controller({"_id": "x", "key": "usg"})
        assert m.upnp_enabled is None
        assert m.dns_verification is None


class TestFieldSets:
    def test_mutable_excludes_readonly(self):
        assert "id" not in MUTABLE_FIELDS
        assert "site_id" not in MUTABLE_FIELDS
        assert "key" not in MUTABLE_FIELDS

    def test_mutable_count_is_37(self):
        assert len(MUTABLE_FIELDS) == 37

    def test_readonly_fields(self):
        assert READ_ONLY_FIELDS == frozenset({"id", "site_id", "key"})

    def test_representative_mutable_fields(self):
        for f in (
            "upnp_enabled",
            "geo_ip_filtering_enabled",
            "tcp_established_timeout",
            "dns_verification",
            "unbind_wan_monitors",
        ):
            assert f in MUTABLE_FIELDS


class TestToControllerUpdate:
    def test_filters_unknown_and_readonly(self):
        out = to_controller_update({"upnp_enabled": True, "id": "x", "key": "usg", "bogus": 1})
        assert out == {"upnp_enabled": True}

    def test_drops_none_keeps_false(self):
        out = to_controller_update({"syn_cookies": False, "broadcast_ping": None})
        assert out == {"syn_cookies": False}

    def test_nested_dict_passes_through(self):
        partial = {"dns_verification": {"primary_dns_server": "9.9.9.9"}}
        out = to_controller_update(partial)
        assert out == partial
