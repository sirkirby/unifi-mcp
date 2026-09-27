"""Unit tests for the Network PortForward CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.port_forwards import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    PortForward,
    from_controller,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in (
            "name",
            "enabled",
            "fwd_protocol",
            "dst_port",
            "destination_ip",
            "fwd_port",
            "fwd_ip",
            "src",
            "log",
        ):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "site_id"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_id_and_site_id(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "site_id" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(PortForward.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_rule_with_proto(self) -> None:
        raw = {
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
        }
        pf = from_controller(raw)
        assert pf.id == "pf-1"
        assert pf.site_id == "site-a"
        assert pf.name == "Web Server"
        assert pf.enabled is True
        assert pf.fwd_protocol == "tcp"
        assert pf.dst_port == "80"
        assert pf.destination_ip == "198.51.100.69"
        assert pf.fwd_port == "8080"
        assert pf.fwd_ip == "192.168.1.100"
        assert pf.log is False

    def test_fwd_ip_from_fwd_field(self) -> None:
        raw = {"_id": "pf-1", "fwd": "10.0.0.5"}
        pf = from_controller(raw)
        assert pf.fwd_ip == "10.0.0.5"

    def test_fwd_ip_from_fwd_ip_field(self) -> None:
        raw = {"_id": "pf-1", "fwd_ip": "10.0.0.5"}
        pf = from_controller(raw)
        assert pf.fwd_ip == "10.0.0.5"

    def test_protocol_coalesces_fwd_protocol_then_proto(self) -> None:
        raw = {"_id": "pf-1", "fwd_protocol": "udp"}
        pf = from_controller(raw)
        assert pf.fwd_protocol == "udp"

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "name": "Test"}
        pf = from_controller(raw)
        assert pf.id == "abc"

    def test_handles_empty_dict(self) -> None:
        pf = from_controller({})
        assert pf.id is None
        assert pf.name is None
        assert pf.fwd_ip is None


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

    def test_read_only_fields_excluded(self) -> None:
        model = PortForward(id="should-not-appear", site_id="site", name="Test")
        payload = to_controller_create(model)
        assert "id" not in payload
        assert "site_id" not in payload


class TestToControllerUpdate:
    @pytest.mark.parametrize(
        "value, expected", [("198.51.100.70", "198.51.100.70"), ("any", "any"), (None, "any"), ("", "any")]
    )
    def test_destination_update_and_clear(self, value: str | None, expected: str) -> None:
        assert to_controller_update({"destination_ip": value}) == {"destination_ip": expected}
        assert "destination_ip" not in to_controller_update({"enabled": False})

    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "enabled": True})
        assert "name" not in result
        assert result["enabled"] is True

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

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only"})
        assert result == {}
