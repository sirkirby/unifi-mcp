"""Unit tests for the Network PortForward CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.port_forwards import (
    PortForward,
    from_controller,
    to_controller_create,
    to_controller_update,
)

from .model_assertions import assert_fields


class TestFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {
                    "_id": "pf-1",
                    "site_id": "site-a",
                    "name": "Web Server",
                    "enabled": True,
                    "proto": "tcp",
                    "dst_port": "80",
                    "destination_ip": "198.51.100.69",
                    "fwd_port": "8080",
                    "fwd": "192.168.1.100",
                    "src": "0.0.0.0/0",
                    "log": False,
                },
                {
                    "id": "pf-1",
                    "site_id": "site-a",
                    "name": "Web Server",
                    "enabled": True,
                    "fwd_protocol": "tcp",
                    "dst_port": "80",
                    "destination_ip": "198.51.100.69",
                    "fwd_port": "8080",
                    "fwd_ip": "192.168.1.100",
                    "log": False,
                },
            ),
            ({"_id": "pf-1", "fwd": "10.0.0.5"}, {"fwd_ip": "10.0.0.5"}),
            ({"_id": "pf-1", "fwd_ip": "10.0.0.5"}, {"fwd_ip": "10.0.0.5"}),
            ({"_id": "pf-1", "fwd_protocol": "udp"}, {"fwd_protocol": "udp"}),
            ({"_id": "abc", "name": "Test"}, {"id": "abc"}),
            ({}, {"id": None, "name": None, "fwd_ip": None}),
        ],
        ids=[
            "full_rule_with_proto",
            "fwd_ip_from_fwd_field",
            "fwd_ip_from_fwd_ip_field",
            "protocol_coalesces_fwd_protocol_then_proto",
            "id_coalesces_underscore_id",
            "handles_empty_dict",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)


class TestToControllerCreate:
    def test_destination_binding_is_optional(self) -> None:
        assert "destination_ip" not in to_controller_create(PortForward(name="Web"))
        assert to_controller_create(PortForward(destination_ip="198.51.100.69"))["destination_ip"] == "198.51.100.69"

    @pytest.mark.parametrize("source", ["203.0.113.8", "203.0.113.0/28"])
    def test_source_restriction_enables_controller_flag(self, source: str) -> None:
        payload = to_controller_create(PortForward(src=source))
        assert payload["src"] == source
        assert payload["src_limiting_enabled"] is True

    @pytest.mark.parametrize("source", [None, "", "any"])
    def test_unrestricted_create_disables_controller_flag(self, source: str | None) -> None:
        payload = to_controller_create(PortForward(src=source))
        assert payload["src_limiting_enabled"] is False
        if source is not None:
            assert payload["src"] == "any"

    def test_maps_fwd_protocol_to_proto(self) -> None:
        model = PortForward(
            name="SSH",
            fwd_protocol="tcp",
            dst_port="22",
            fwd_port="22",
            fwd_ip="192.168.1.10",
        )
        payload = to_controller_create(model)
        assert payload["proto"] == "tcp"
        assert "fwd_protocol" not in payload
        assert payload["fwd"] == "192.168.1.10"
        assert "fwd_ip" not in payload

    @pytest.mark.parametrize("protocol", ["tcp", "udp", "tcp_udp"])
    def test_create_sends_canonical_proto(self, protocol: str) -> None:
        model = PortForward(
            name="SSH",
            fwd_protocol=protocol,
            dst_port="22",
            fwd_port="22",
            fwd_ip="192.168.1.10",
        )
        payload = to_controller_create(model)
        assert payload["proto"] == protocol
        assert "fwd_protocol" not in payload


class TestToControllerUpdate:
    @pytest.mark.parametrize(
        "value, expected", [("198.51.100.70", "198.51.100.70"), ("any", "any"), (None, "any"), ("", "any")]
    )
    def test_destination_update_and_clear(self, value: str | None, expected: str) -> None:
        assert to_controller_update({"destination_ip": value}) == {"destination_ip": expected}
        assert "destination_ip" not in to_controller_update({"enabled": False})

    def test_toggle_payload(self) -> None:
        result = to_controller_update({"enabled": True})
        assert result == {"enabled": True}

    def test_maps_forward_ip_to_controller_field(self) -> None:
        result = to_controller_update({"fwd_ip": "192.168.1.20"})
        assert result == {"fwd": "192.168.1.20"}

    @pytest.mark.parametrize("protocol", ["tcp", "udp", "tcp_udp"])
    def test_maps_protocol_to_controller_field(self, protocol: str) -> None:
        result = to_controller_update({"fwd_protocol": protocol})
        assert result == {"proto": protocol}

    def test_translates_none_for_source_removal(self) -> None:
        result = to_controller_update({"src": None})
        assert result == {"src": "any", "src_limiting_enabled": False}

    def test_empty_source_disables_controller_flag(self) -> None:
        assert to_controller_update({"src": ""}) == {"src": "any", "src_limiting_enabled": False}

    def test_any_source_disables_controller_flag(self) -> None:
        assert to_controller_update({"src": "any"}) == {"src": "any", "src_limiting_enabled": False}

    def test_source_update_enables_controller_flag(self) -> None:
        assert to_controller_update({"src": "203.0.113.0/28"}) == {
            "src": "203.0.113.0/28",
            "src_limiting_enabled": True,
        }
