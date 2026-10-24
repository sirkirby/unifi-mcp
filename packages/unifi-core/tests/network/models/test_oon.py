"""Unit tests for the Network OonPolicy CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.oon import (
    MUTABLE_FIELDS,
    OonPolicy,
    from_controller,
    to_controller_create,
    to_controller_update,
)

from .model_assertions import assert_fields


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in ("name", "enabled", "target_type", "targets", "secure", "qos", "route"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_contains_qos_enabled_and_route_enabled(self) -> None:
        # These were silent-drop bugs
        assert "qos_enabled" in MUTABLE_FIELDS
        assert "route_enabled" in MUTABLE_FIELDS


class TestFromController:
    def test_full_policy(self) -> None:
        raw = {
            "_id": "oon-1",
            "name": "Bedtime Policy",
            "enabled": True,
            "target_type": "CLIENTS",
            "targets": ["aa:bb:cc:dd:ee:ff"],
            "restriction_level": "high",
            "qos": {"enabled": True, "mode": "LIMIT"},
            "route": {"enabled": False, "mode": "OFF"},
            "secure": {"enabled": True},
        }
        p = from_controller(raw)
        assert p.id == "oon-1"
        assert p.name == "Bedtime Policy"
        assert p.enabled is True
        assert p.target_type == "CLIENTS"
        assert p.targets == ["aa:bb:cc:dd:ee:ff"]
        assert p.restriction_level == "high"
        assert p.qos_enabled is True
        assert p.route_enabled is False

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ({"_id": "abc", "name": "Test"}, {"id": "abc"}),
            ({"id": "xyz", "name": "Test"}, {"id": "xyz"}),
            ({"_id": "p1", "qos": {"enabled": True}}, {"qos_enabled": True}),
            ({"_id": "p1", "route": {"enabled": False}}, {"route_enabled": False}),
            ({"_id": "p1"}, {"qos": None, "qos_enabled": None}),
            ({"_id": "p1", "name": "Empty"}, {"targets": []}),
            ({"_id": "p1", "targets": ["mac-1", "mac-2"]}, {"applies_to": ["mac-1", "mac-2"]}),
            ({}, {"id": None, "name": None, "targets": []}),
        ],
        ids=[
            "id_coalesces_underscore_id",
            "id_coalesces_plain_id",
            "qos_enabled_extracted_from_qos_block",
            "route_enabled_extracted_from_route_block",
            "missing_qos_gives_none",
            "targets_defaults_to_empty_list",
            "applies_to_mirrors_targets",
            "handles_empty_dict",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)


class TestToControllerCreate:
    def test_full_model(self) -> None:
        model = OonPolicy(
            name="Test Policy",
            enabled=True,
            target_type="CLIENTS",
            targets=["aa:bb:cc:dd:ee:ff"],
            qos={"enabled": False},
        )
        payload = to_controller_create(model)
        assert payload["name"] == "Test Policy"
        assert payload["enabled"] is True
        assert payload["target_type"] == "CLIENTS"
        assert payload["targets"] == ["aa:bb:cc:dd:ee:ff"]
        assert payload["qos"] == {"enabled": False}


class TestToControllerUpdate:
    @pytest.mark.parametrize(
        "fields, expected, absent, present",
        [
            ({"id": "ignore-me", "name": "New Name"}, {"name": "New Name"}, ("id",), ()),
            ({"name": None, "enabled": True}, {"enabled": True}, ("name",), ()),
            ({"qos_enabled": True}, {"qos_enabled": True}, (), ()),
            ({"unknown": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown",), ()),
        ],
        ids=["filters_out_read_only_id", "drops_none_values", "passes_qos_enabled", "drops_unrecognised_keys"],
    )
    def test_to_controller_update_payload(self, fields, expected, absent, present) -> None:
        result = to_controller_update(fields)
        assert_fields(result, expected)
        for key in absent:
            assert key not in result
        for key in present:
            assert key in result

    def test_passes_route_enabled(self) -> None:
        result = to_controller_update({"route_enabled": False})
        assert result["route_enabled"] is False
        result2 = to_controller_update({"route_enabled": True})
        assert result2["route_enabled"] is True

    def test_toggle_payload(self) -> None:
        result = to_controller_update({"enabled": True})
        assert result == {"enabled": True}
