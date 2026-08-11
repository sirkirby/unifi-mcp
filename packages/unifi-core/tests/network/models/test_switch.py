"""Unit tests for the Network PortProfile CRUD domain model."""

from __future__ import annotations

from unifi_core.network.models.switch import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    PortProfile,
    build_create_payload,
    from_controller,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in (
            "name",
            "forward",
            "native_networkconf_id",
            "tagged_networkconf_ids",
            "voice_networkconf_id",
            "isolation",
            "poe_mode",
            "stp_port_mode",
            "dot1x_ctrl",
        ):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "attr_no_delete"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_id_and_attr_no_delete(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "attr_no_delete" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(PortProfile.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


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

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "name": "Test"}
        pp = from_controller(raw)
        assert pp.id == "abc"

    def test_tagged_networkconf_ids_defaults_to_empty(self) -> None:
        raw = {"_id": "pp-1"}
        pp = from_controller(raw)
        assert pp.tagged_networkconf_ids == []

    def test_non_list_tagged_ids_becomes_empty(self) -> None:
        raw = {"_id": "pp-1", "tagged_networkconf_ids": None}
        pp = from_controller(raw)
        assert pp.tagged_networkconf_ids == []

    def test_handles_empty_dict(self) -> None:
        pp = from_controller({})
        assert pp.id is None
        assert pp.name is None
        assert pp.tagged_networkconf_ids == []


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

    def test_read_only_fields_excluded(self) -> None:
        model = PortProfile(id="should-not-appear", attr_no_delete=True, name="Test")
        payload = to_controller_create(model)
        assert "id" not in payload
        assert "attr_no_delete" not in payload


class TestToControllerUpdate:
    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "forward": "all"})
        assert "name" not in result
        assert result["forward"] == "all"

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only", "attr_no_delete": True})
        assert result == {}


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
