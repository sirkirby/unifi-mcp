"""Unit tests for the Network QosRule CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.qos import (
    QosRule,
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
                },
                {
                    "id": "qos-1",
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
                },
            ),
            ({"_id": "abc", "name": "Test"}, {"id": "abc"}),
            ({"id": "xyz", "name": "Test"}, {"id": "xyz"}),
            ({}, {"id": None, "name": None, "enabled": None}),
            ({"_id": "q1", "target_ip_address": "192.168.1.50"}, {"target_ip_address": "192.168.1.50"}),
        ],
        ids=[
            "full_rule",
            "id_coalesces_underscore_id",
            "id_coalesces_plain_id",
            "handles_empty_dict",
            "target_ip_address_captured",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)


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


class TestToControllerUpdate:
    @pytest.mark.parametrize(
        "fields, expected, absent, present",
        [
            ({"id": "ignore-me", "name": "New Name"}, {"name": "New Name"}, ("id",), ()),
            ({"name": None, "enabled": True}, {"enabled": True}, ("name",), ()),
            ({"unknown": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown",), ()),
            ({"dscp_value": 46}, {"dscp_value": 46}, (), ()),
        ],
        ids=["filters_out_read_only_id", "drops_none_values", "drops_unrecognised_keys", "dscp_passthrough"],
    )
    def test_to_controller_update_payload(self, fields, expected, absent, present) -> None:
        result = to_controller_update(fields)
        assert_fields(result, expected)
        for key in absent:
            assert key not in result
        for key in present:
            assert key in result

    def test_toggle_payload(self) -> None:
        result = to_controller_update({"enabled": True})
        assert result == {"enabled": True}
