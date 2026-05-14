"""Unit tests for the Network QosRule CRUD domain model."""

from __future__ import annotations

from unifi_core.network.models.qos import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    QosRule,
    from_controller,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in (
            "name",
            "enabled",
            "interface",
            "direction",
            "bandwidth_limit_kbps",
            "dscp_value",
            "rate_max_down",
            "rate_max_up",
            "priority",
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
        all_fields = frozenset(QosRule.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_rule(self) -> None:
        raw = {
            "_id": "qos-1",
            "site_id": "site-a",
            "name": "VoIP Upload",
            "enabled": True,
            "interface": "WAN",
            "direction": "upload",
            "bandwidth_limit_kbps": 2000,
            "target_subnet": "192.168.1.0/24",
            "dscp_value": 46,
            "rate_max_up": 2000,
            "priority": 1,
        }
        r = from_controller(raw)
        assert r.id == "qos-1"
        assert r.site_id == "site-a"
        assert r.name == "VoIP Upload"
        assert r.enabled is True
        assert r.interface == "WAN"
        assert r.direction == "upload"
        assert r.bandwidth_limit_kbps == 2000
        assert r.target_subnet == "192.168.1.0/24"
        assert r.dscp_value == 46
        assert r.rate_max_up == 2000
        assert r.priority == 1

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "name": "Test"}
        r = from_controller(raw)
        assert r.id == "abc"

    def test_id_coalesces_plain_id(self) -> None:
        raw = {"id": "xyz", "name": "Test"}
        r = from_controller(raw)
        assert r.id == "xyz"

    def test_handles_empty_dict(self) -> None:
        r = from_controller({})
        assert r.id is None
        assert r.name is None
        assert r.enabled is None

    def test_target_ip_address_captured(self) -> None:
        raw = {"_id": "q1", "target_ip_address": "192.168.1.50"}
        r = from_controller(raw)
        assert r.target_ip_address == "192.168.1.50"


class TestToControllerCreate:
    def test_full_model(self) -> None:
        model = QosRule(
            name="Zoom Limit",
            interface="WAN",
            direction="upload",
            bandwidth_limit_kbps=5000,
            enabled=True,
        )
        payload = to_controller_create(model)
        assert payload["name"] == "Zoom Limit"
        assert payload["interface"] == "WAN"
        assert payload["direction"] == "upload"
        assert payload["bandwidth_limit_kbps"] == 5000
        assert payload["enabled"] is True

    def test_read_only_fields_excluded(self) -> None:
        model = QosRule(id="should-not-appear", site_id="site", name="Test")
        payload = to_controller_create(model)
        assert "id" not in payload
        assert "site_id" not in payload

    def test_none_optional_fields_excluded(self) -> None:
        model = QosRule(name="Minimal")
        payload = to_controller_create(model)
        assert "target_ip_address" not in payload
        assert "target_subnet" not in payload


class TestToControllerUpdate:
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

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only", "site_id": "also"})
        assert result == {}

    def test_dscp_passthrough(self) -> None:
        result = to_controller_update({"dscp_value": 46})
        assert result["dscp_value"] == 46
