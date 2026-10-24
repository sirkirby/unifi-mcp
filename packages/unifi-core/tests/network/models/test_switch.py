"""Unit tests for the Network PortProfile CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.switch import (
    MUTABLE_FIELDS,
    PortProfile,
    build_create_payload,
    from_controller,
    to_controller_create,
    to_controller_update,
)

from .model_assertions import assert_fields


class TestFromController:
    def test_full_profile(self) -> None:
        raw = {
            "_id": "pp-1",
            "name": "IoT Access",
            "forward": "native",
            "native_networkconf_id": "net-10",
            "tagged_networkconf_ids": ["net-20", "net-30"],
            "voice_networkconf_id": "net-voice",
            "poe_mode": "auto",
            "isolation": False,
            "stp_port_mode": True,
            "dot1x_ctrl": "force_authorized",
            "attr_no_delete": False,
        }
        pp = from_controller(raw)
        assert pp.id == "pp-1"
        assert pp.name == "IoT Access"
        assert pp.forward == "native"
        assert pp.native_networkconf_id == "net-10"
        assert pp.tagged_networkconf_ids == ["net-20", "net-30"]
        assert pp.voice_networkconf_id == "net-voice"
        assert pp.poe_mode == "auto"
        assert pp.isolation is False
        assert pp.stp_port_mode is True
        assert pp.dot1x_ctrl == "force_authorized"
        assert pp.attr_no_delete is False

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ({"_id": "abc", "name": "Test"}, {"id": "abc"}),
            ({"_id": "pp-1"}, {"tagged_networkconf_ids": []}),
            ({"_id": "pp-1", "tagged_networkconf_ids": None}, {"tagged_networkconf_ids": []}),
            ({}, {"id": None, "name": None, "tagged_networkconf_ids": []}),
        ],
        ids=[
            "id_coalesces_underscore_id",
            "tagged_networkconf_ids_defaults_to_empty",
            "non_list_tagged_ids_becomes_empty",
            "handles_empty_dict",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)


class TestToControllerCreate:
    def test_full_model(self) -> None:
        model = PortProfile(
            name="IoT",
            forward="native",
            native_networkconf_id="net-20",
            poe_mode="auto",
        )
        payload = to_controller_create(model)
        assert payload["name"] == "IoT"
        assert payload["forward"] == "native"
        assert payload["native_networkconf_id"] == "net-20"
        assert payload["poe_mode"] == "auto"


class TestAccessPortFields:
    """Fields required to express an access port, plus the UI's Port Mode trio.

    ``tagged_vlan_mgmt`` is the control that actually decides whether a port
    trunks. Without it the model can only send ``forward: 'native'`` alongside
    an inherited ``allow_all``, which the controller resolves by rewriting
    ``forward`` to agree with the tagged setting — so no combination of the
    previously-exposed fields produced an access port on the native LAN.

    The UI's single "Port Mode: Infrastructure | Edge" control maps to three
    stored fields, so they are exposed individually rather than behind a
    synthetic field the controller does not have.
    """

    ACCESS_PORT_FIELDS = (
        "tagged_vlan_mgmt",
        "excluded_networkconf_ids",
        "stp_edge_state",
        "stp_bpdu_guard_enabled",
        "stp_uplink",
    )

    def test_access_port_fields_are_mutable(self) -> None:
        for field in self.ACCESS_PORT_FIELDS:
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_from_controller_reads_access_port_fields(self) -> None:
        profile = from_controller(
            {
                "_id": "pp-1",
                "name": "Access - Trusted",
                "forward": "native",
                "tagged_vlan_mgmt": "block_all",
                "excluded_networkconf_ids": ["net-9"],
                "stp_edge_state": "enabled",
                "stp_bpdu_guard_enabled": True,
                "stp_uplink": False,
            }
        )
        assert profile.tagged_vlan_mgmt == "block_all"
        assert profile.excluded_networkconf_ids == ["net-9"]
        assert profile.stp_edge_state == "enabled"
        assert profile.stp_bpdu_guard_enabled is True
        assert profile.stp_uplink is False

    def test_tagged_vlan_mgmt_survives_update_filter(self) -> None:
        result = to_controller_update({"tagged_vlan_mgmt": "block_all"})
        assert result == {"tagged_vlan_mgmt": "block_all"}

    def test_stp_uplink_false_is_preserved(self) -> None:
        """False is meaningful for an edge port — only None is dropped."""
        result = to_controller_update({"stp_uplink": False, "stp_bpdu_guard_enabled": False})
        assert result["stp_uplink"] is False
        assert result["stp_bpdu_guard_enabled"] is False

    def test_excluded_networkconf_ids_empty_list_survives(self) -> None:
        result = to_controller_update({"excluded_networkconf_ids": []})
        assert result == {"excluded_networkconf_ids": []}

    def test_access_port_round_trip_through_create(self) -> None:
        model = PortProfile(
            name="Access - Trusted",
            forward="native",
            tagged_vlan_mgmt="block_all",
            stp_edge_state="enabled",
            stp_bpdu_guard_enabled=True,
            stp_uplink=False,
        )
        payload = to_controller_create(model)
        assert payload["tagged_vlan_mgmt"] == "block_all"
        assert payload["stp_edge_state"] == "enabled"
        assert payload["stp_bpdu_guard_enabled"] is True
        assert payload["stp_uplink"] is False


class TestBuildCreatePayload:
    """Shared by the MCP tool and the /v1/actions translator, so both send the
    same defaults — notably poe_mode, which the controller otherwise defaults
    to PoE-off."""

    def test_defaults_are_always_sent(self) -> None:
        payload = build_create_payload(name="P", forward="native")
        assert payload["poe_mode"] == "auto"
        assert payload["stp_port_mode"] is True
        assert payload["isolation"] is False

    def test_unsupplied_optional_fields_are_omitted(self) -> None:
        payload = build_create_payload(name="P", forward="native")
        for key in ("tagged_vlan_mgmt", "excluded_networkconf_ids", "stp_edge_state", "stp_uplink"):
            assert key not in payload

    def test_access_port_fields_pass_through(self) -> None:
        payload = build_create_payload(
            name="Access",
            forward="native",
            tagged_vlan_mgmt="block_all",
            stp_uplink=False,
            tagged_networkconf_ids=[],
        )
        assert payload["tagged_vlan_mgmt"] == "block_all"
        assert payload["stp_uplink"] is False
        assert payload["tagged_networkconf_ids"] == []


class TestStormControlFields:
    STORMCTRL_FIELDS = (
        "stormctrl_bcast_enabled",
        "stormctrl_bcast_rate",
        "stormctrl_mcast_enabled",
        "stormctrl_mcast_rate",
        "stormctrl_ucast_enabled",
        "stormctrl_ucast_rate",
    )

    def test_storm_control_fields_are_mutable(self) -> None:
        for field in self.STORMCTRL_FIELDS:
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_from_controller_reads_storm_control_fields(self) -> None:
        profile = from_controller(
            {
                "_id": "pp-1",
                "name": "Storm",
                "stormctrl_bcast_enabled": True,
                "stormctrl_bcast_rate": 1000,
                "stormctrl_mcast_enabled": False,
                "stormctrl_mcast_rate": 1500,
                "stormctrl_ucast_enabled": True,
                "stormctrl_ucast_rate": 2000,
            }
        )
        assert profile.stormctrl_bcast_enabled is True
        assert profile.stormctrl_bcast_rate == 1000
        assert profile.stormctrl_mcast_enabled is False
        assert profile.stormctrl_mcast_rate == 1500
        assert profile.stormctrl_ucast_enabled is True
        assert profile.stormctrl_ucast_rate == 2000

    def test_update_filter_preserves_storm_control(self) -> None:
        result = to_controller_update({"stormctrl_bcast_enabled": False, "stormctrl_bcast_rate": 1000})
        assert result["stormctrl_bcast_enabled"] is False
        assert result["stormctrl_bcast_rate"] == 1000

    def test_create_payload_includes_storm_control_when_supplied(self) -> None:
        payload = build_create_payload(
            name="Storm",
            forward="native",
            stormctrl_bcast_enabled=True,
            stormctrl_bcast_rate=1000,
        )
        assert payload["stormctrl_bcast_enabled"] is True
        assert payload["stormctrl_bcast_rate"] == 1000

    def test_create_payload_omits_storm_control_when_unsupplied(self) -> None:
        payload = build_create_payload(name="P", forward="native")
        for field in self.STORMCTRL_FIELDS:
            assert field not in payload

    @pytest.mark.parametrize("field", ("stormctrl_bcast_rate", "stormctrl_mcast_rate", "stormctrl_ucast_rate"))
    @pytest.mark.parametrize("value", (-1, 14_880_001, True, 1.5, "100"))
    def test_update_rejects_invalid_storm_control_rates(self, field: str, value: object) -> None:
        with pytest.raises(ValueError):
            to_controller_update({field: value})

    @pytest.mark.parametrize("value", (0, 14_880_000))
    def test_update_accepts_storm_control_rate_boundaries(self, value: int) -> None:
        assert to_controller_update({"stormctrl_bcast_rate": value}) == {"stormctrl_bcast_rate": value}
