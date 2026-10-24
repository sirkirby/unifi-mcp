"""Tests for the gateway (USG) settings shared model."""

import pytest
from unifi_core.network.models.gateway_settings import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    from_controller,
    to_controller_update,
)

from .model_assertions import assert_fields

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
    "echo_server": "8.8.8.8",
    "unbind_wan_monitors": False,
}


class TestFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (SAMPLE_USG, {"id": "aaaaaaaaaaaaaaaaaaaaaaaa", "site_id": "bbbbbbbbbbbbbbbbbbbbbbbb", "key": "usg"}),
            (SAMPLE_USG, {"upnp_enabled": False, "upnp_wan_interface": "WAN", "mss_clamp": "auto"}),
            (SAMPLE_USG, {"tcp_established_timeout": 7440, "icmp_timeout": 30, "timeout_setting_preference": "auto"}),
            (SAMPLE_USG, {"echo_server": "8.8.8.8"}),
            (SAMPLE_USG, {"ftp_module": True, "sip_module": True, "offload_sch": True}),
            ({"_id": "x", "key": "usg"}, {"upnp_enabled": None, "dns_verification": None}),
            ({**SAMPLE_USG, "geo_ip_filtering_countries": "US,CA"}, {"geo_ip_filtering_countries": "US,CA"}),
        ],
        ids=[
            "identity_and_key",
            "nat_upnp_fields",
            "conntrack_timeouts_are_ints",
            "echo_server_is_preserved",
            "module_and_offload_flags",
            "missing_keys_default_none",
            "geo_ip_countries_string_passthrough",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)

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

    def test_geo_ip_countries_list_normalized_to_csv(self):
        """Some firmware returns geo_ip_filtering_countries as an array; it must be
        coerced to the canonical CSV string rather than failing str validation."""
        m = from_controller({**SAMPLE_USG, "geo_ip_filtering_countries": ["US", "CA", "GB"]})
        assert m.geo_ip_filtering_countries == "US,CA,GB"


class TestFieldSets:
    def test_mutable_count_is_38(self):
        assert len(MUTABLE_FIELDS) == 38

    def test_readonly_fields(self):
        assert READ_ONLY_FIELDS == frozenset({"id", "site_id", "key"})


class TestToControllerUpdate:
    def test_filters_unknown_and_readonly(self):
        out = to_controller_update({"upnp_enabled": True, "id": "x", "key": "usg", "bogus": 1})
        assert out == {"upnp_enabled": True}

    def test_nested_dict_passes_through(self):
        partial = {"dns_verification": {"primary_dns_server": "9.9.9.9"}}
        out = to_controller_update(partial)
        assert out == partial

    def test_echo_server_passes_through(self):
        assert to_controller_update({"echo_server": "1.1.1.1"}) == {"echo_server": "1.1.1.1"}

    @pytest.mark.parametrize("value", (42, True, ["1.1.1.1"]))
    def test_echo_server_rejects_non_string_values(self, value):
        with pytest.raises(ValueError):
            to_controller_update({"echo_server": value})
