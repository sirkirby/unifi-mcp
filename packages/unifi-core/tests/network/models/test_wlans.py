"""Unit tests for the Network Wlan CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.wlans import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    Wlan,
    apply_update_dependencies,
    from_controller,
    to_controller_create,
    to_controller_update,
    validate_create,
    validate_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_core_fields(self) -> None:
        for field in (
            "name",
            "security",
            "x_passphrase",
            "enabled",
            "hide_ssid",
            "guest_policy",
            "network_id",
            "vlan_id",
            "usergroup_id",
            "schedule_enabled",
            "schedule_reversed",
            "schedule",
            "schedule_with_duration",
            "ap_group_ids",
            "ap_group_mode",
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
        all_fields = frozenset(Wlan.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_wlan(self) -> None:
        raw = {
            "_id": "wlan-1",
            "site_id": "site-a",
            "name": "HomeWiFi",
            "security": "wpa2-psk",
            "x_passphrase": "secret123",
            "enabled": True,
            "hide_ssid": False,
            "networkconf_id": "net-1",
            "vlan": 10,
            "usergroup_id": "_default_",
            "ap_group_ids": ["apg-1"],
            "mac_filter_enabled": False,
        }
        wlan = from_controller(raw)
        assert wlan.id == "wlan-1"
        assert wlan.site_id == "site-a"
        assert wlan.name == "HomeWiFi"
        assert wlan.security == "wpa2-psk"
        assert wlan.x_passphrase == "secret123"
        assert wlan.enabled is True
        assert wlan.hide_ssid is False
        assert wlan.network_id == "net-1"
        assert wlan.vlan_id == 10
        assert wlan.usergroup_id == "_default_"
        assert wlan.ap_group_ids == ["apg-1"]
        assert wlan.mac_filter_enabled is False

    def test_network_id_fallback(self) -> None:
        raw = {"_id": "wlan-2", "network_id": "net-2"}
        wlan = from_controller(raw)
        assert wlan.network_id == "net-2"

    def test_networkconf_id_takes_priority(self) -> None:
        raw = {"_id": "wlan-3", "networkconf_id": "primary", "network_id": "fallback"}
        wlan = from_controller(raw)
        assert wlan.network_id == "primary"

    def test_handles_empty_dict(self) -> None:
        wlan = from_controller({})
        assert wlan.id is None
        assert wlan.name is None
        assert wlan.enabled is None

    def test_wlan_from_controller_carries_passphrase_verbatim(self) -> None:
        # The domain model is lossless: redaction is a response-boundary
        # concern (MCP tool / serializer / GraphQL type), not the model's job.
        model = from_controller({"_id": "w1", "name": "SSID", "x_passphrase": "wifi-secret"})

        assert model.x_passphrase == "wifi-secret"


class TestStrictValidation:
    def test_update_rejects_mixed_unknown_field(self) -> None:
        with pytest.raises(ValueError, match="Unknown WLAN field"):
            validate_update({"enabled": False, "unknown": True})

    def test_create_rejects_unknown_and_missing_passphrase(self) -> None:
        with pytest.raises(ValueError, match="Unknown WLAN field"):
            validate_create({"name": "SSID", "security": "open", "unknown": True})
        with pytest.raises(ValueError, match="x_passphrase"):
            validate_create({"name": "SSID", "security": "wpa2-psk"})

    def test_rejects_ssid_longer_than_32_bytes(self) -> None:
        # 802.11 SSID limit; the controller rejects longer names with a
        # detail-less api.err.InvalidValue, so validation fails loudly first.
        long_name = "s" * 33
        with pytest.raises(ValueError, match="32 bytes"):
            validate_create({"name": long_name, "security": "open"})
        with pytest.raises(ValueError, match="32 bytes"):
            validate_update({"name": long_name})
        multibyte = "é" * 17  # 17 chars but 34 UTF-8 bytes
        with pytest.raises(ValueError, match="32 bytes"):
            validate_update({"name": multibyte})
        assert validate_update({"name": "s" * 32}) == {"name": "s" * 32}

    def test_update_expands_minrate_dependencies_before_translation(self) -> None:
        assert apply_update_dependencies({"minrate_ng_data_rate_kbps": 6000}) == {
            "minrate_ng_data_rate_kbps": 6000,
            "minrate_setting_preference": "manual",
            "minrate_ng_enabled": True,
        }
        assert validate_update({"minrate_ng_data_rate_kbps": 6000}) == {
            "minrate_ng_data_rate_kbps": 6000,
            "minrate_setting_preference": "manual",
            "minrate_ng_enabled": True,
        }


class TestWlanScheduleFields:
    def test_from_controller_reads_schedule_fields(self) -> None:
        windows = [
            {
                "duration_minutes": 360,
                "name": "Weeknight outage",
                "start_days_of_week": ["mon", "tue", "wed", "thu", "fri"],
                "start_hour": 1,
                "start_minute": 0,
            }
        ]
        wlan = from_controller(
            {
                "_id": "wlan-scheduled",
                "schedule_enabled": True,
                "schedule_reversed": True,
                "schedule": ["mon-fri|0100-0700"],
                "schedule_with_duration": windows,
            }
        )

        assert wlan.schedule_enabled is True
        assert wlan.schedule_reversed is True
        assert wlan.schedule == ["mon-fri|0100-0700"]
        assert [window.model_dump(exclude_none=True) for window in wlan.schedule_with_duration or []] == windows

    def test_validate_update_accepts_duration_windows(self) -> None:
        update = {
            "schedule_enabled": True,
            "schedule_reversed": True,
            "schedule_with_duration": [
                {
                    "duration_minutes": 360,
                    "name": "Weeknight outage",
                    "start_days_of_week": ["mon", "tue", "wed", "thu", "fri"],
                    "start_hour": 1,
                    "start_minute": 0,
                },
                {
                    "duration_minutes": 300,
                    "start_days_of_week": ["sat", "sun"],
                    "start_hour": 2,
                    "start_minute": 0,
                },
            ],
        }

        assert validate_update(update) == update

    @pytest.mark.parametrize(
        "window",
        [
            {
                "duration_minutes": 0,
                "start_days_of_week": ["mon"],
                "start_hour": 1,
                "start_minute": 0,
            },
            {
                "duration_minutes": 60,
                "start_days_of_week": ["monday"],
                "start_hour": 1,
                "start_minute": 0,
            },
            {
                "duration_minutes": 60,
                "start_days_of_week": ["mon"],
                "start_hour": 24,
                "start_minute": 0,
            },
            {
                "duration_minutes": 60,
                "start_days_of_week": ["mon"],
                "start_hour": 1,
                "start_minute": 60,
            },
            {
                "duration_minutes": 60,
                "start_days_of_week": ["mon"],
                "start_hour": 1,
                "start_minute": 0,
                "unknown": True,
            },
        ],
    )
    def test_validate_update_rejects_invalid_duration_windows(self, window: dict) -> None:
        with pytest.raises(ValueError, match="Invalid WLAN update data"):
            validate_update({"schedule_with_duration": [window]})

    def test_empty_schedule_lists_are_preserved_for_clearing(self) -> None:
        assert validate_update({"schedule": [], "schedule_with_duration": []}) == {
            "schedule": [],
            "schedule_with_duration": [],
        }

    def test_validate_create_preserves_schedule_fields(self) -> None:
        windows = [
            {
                "duration_minutes": 300,
                "start_days_of_week": ["sat", "sun"],
                "start_hour": 2,
                "start_minute": 0,
            }
        ]
        payload = validate_create(
            {
                "name": "ScheduledSSID",
                "security": "open",
                "schedule_enabled": True,
                "schedule_reversed": True,
                "schedule_with_duration": windows,
            }
        )

        assert payload["schedule_enabled"] is True
        assert payload["schedule_reversed"] is True
        assert payload["schedule_with_duration"] == windows


class TestToControllerCreate:
    def test_maps_network_id_to_networkconf_id(self) -> None:
        model = Wlan(name="Test", security="open", network_id="net-1")
        payload = to_controller_create(model)
        assert payload["networkconf_id"] == "net-1"
        assert "network_id" not in payload

    def test_maps_vlan_id_to_vlan(self) -> None:
        model = Wlan(name="Test", security="open", vlan_id=20)
        payload = to_controller_create(model)
        assert payload["vlan"] == 20
        assert "vlan_id" not in payload

    def test_excludes_id_and_site_id(self) -> None:
        model = Wlan(id="should-not-appear", site_id="site", name="Test")
        payload = to_controller_create(model)
        assert "id" not in payload
        assert "site_id" not in payload

    def test_includes_passphrase(self) -> None:
        model = Wlan(name="Secure", security="wpa2-psk", x_passphrase="mysecret")
        payload = to_controller_create(model)
        assert payload["x_passphrase"] == "mysecret"

    def test_create_and_update_preserve_caller_passphrase(self) -> None:
        model = Wlan(name="SSID", security="wpapsk", x_passphrase="wifi-secret")

        assert to_controller_create(model)["x_passphrase"] == "wifi-secret"
        assert to_controller_update({"x_passphrase": "new-secret"})["x_passphrase"] == "new-secret"

    def test_omits_none_fields(self) -> None:
        model = Wlan(name="Minimal", security="open")
        payload = to_controller_create(model)
        assert "hide_ssid" not in payload
        assert "guest_policy" not in payload


class TestToControllerUpdate:
    def test_maps_network_id_to_networkconf_id(self) -> None:
        result = to_controller_update({"network_id": "net-2"})
        assert "networkconf_id" in result
        assert result["networkconf_id"] == "net-2"
        assert "network_id" not in result

    def test_maps_vlan_id_to_vlan(self) -> None:
        result = to_controller_update({"vlan_id": 30})
        assert result["vlan"] == 30
        assert "vlan_id" not in result

    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "enabled": True})
        assert "name" not in result
        assert result["enabled"] is True

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"

    def test_toggle_payload(self) -> None:
        result = to_controller_update({"enabled": False})
        assert result == {"enabled": False}

    def test_networkconf_id_alias_maps_to_networkconf_id(self) -> None:
        """Callers may pass the controller field name networkconf_id directly."""
        result = to_controller_update({"networkconf_id": "net-3"})
        assert result.get("networkconf_id") == "net-3"
        assert "network_id" not in result

    def test_networkconf_id_alias_combined_with_other_fields(self) -> None:
        result = to_controller_update({"networkconf_id": "net-3", "enabled": True})
        assert result.get("networkconf_id") == "net-3"
        assert result.get("enabled") is True

    def test_network_id_takes_precedence_when_both_passed(self) -> None:
        """Explicit model field name wins over the controller alias regardless of insertion order."""
        result = to_controller_update({"networkconf_id": "alias", "network_id": "explicit"})
        assert result.get("networkconf_id") == "explicit"
        assert "network_id" not in result


class TestRoamingFields:
    """802.11k RRM + the per-band roaming assistant.

    These reach the controller under their own names (no aliasing), so the
    coverage that matters is that they survive ``to_controller_update``'s
    MUTABLE_FIELDS filter — before this they were dropped, which left
    ``validated_data`` empty and surfaced to callers as the misleading
    "Update data is effectively empty or invalid."
    """

    def test_roaming_fields_are_mutable(self) -> None:
        for field in (
            "rrm_enabled",
            "roaming_assistant_na_enabled",
            "roaming_assistant_na_rssi",
            "roaming_assistant_6e_enabled",
            "roaming_assistant_6e_rssi",
        ):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_from_controller_reads_roaming_fields(self) -> None:
        wlan = from_controller(
            {
                "_id": "wlan-roam",
                "rrm_enabled": False,
                "roaming_assistant_na_enabled": True,
                "roaming_assistant_na_rssi": -77,
                "roaming_assistant_6e_enabled": True,
                "roaming_assistant_6e_rssi": -88,
            }
        )
        assert wlan.rrm_enabled is False
        assert wlan.roaming_assistant_na_enabled is True
        assert wlan.roaming_assistant_na_rssi == -77
        assert wlan.roaming_assistant_6e_enabled is True
        assert wlan.roaming_assistant_6e_rssi == -88

    def test_rrm_enabled_survives_update_filter(self) -> None:
        assert to_controller_update({"rrm_enabled": True}) == {"rrm_enabled": True}

    def test_rrm_enabled_false_is_preserved(self) -> None:
        """False is a meaningful value here — only None is dropped."""
        assert to_controller_update({"rrm_enabled": False}) == {"rrm_enabled": False}

    def test_roaming_assistant_rssi_survives_update_filter(self) -> None:
        result = to_controller_update({"roaming_assistant_6e_rssi": -70})
        assert result == {"roaming_assistant_6e_rssi": -70}

    def test_roaming_assistant_threshold_and_toggle_together(self) -> None:
        result = to_controller_update({"roaming_assistant_na_enabled": True, "roaming_assistant_na_rssi": -75})
        assert result == {
            "roaming_assistant_na_enabled": True,
            "roaming_assistant_na_rssi": -75,
        }

    def test_roaming_fields_round_trip_through_create(self) -> None:
        model = Wlan(name="SSID", security="open", rrm_enabled=True, roaming_assistant_6e_rssi=-70)
        payload = to_controller_create(model)
        assert payload["rrm_enabled"] is True
        assert payload["roaming_assistant_6e_rssi"] == -70


class TestMulticastEnhance:
    """Multicast Enhancement is aliased: the controller field is ``mcastenhance_enabled``.

    The public field name stays ``multicast_enhance_enabled``. Before this the
    model both read and wrote the public name, so the read always yielded
    ``None`` and the write went out under a key the controller ignores — which
    also made the post-write verification report the field as unpersisted on
    every attempt, regardless of the value sent.
    """

    def test_from_controller_reads_controller_key(self) -> None:
        wlan = from_controller({"_id": "wlan-mc", "mcastenhance_enabled": True})
        assert wlan.multicast_enhance_enabled is True

    def test_from_controller_reads_false(self) -> None:
        wlan = from_controller({"_id": "wlan-mc", "mcastenhance_enabled": False})
        assert wlan.multicast_enhance_enabled is False

    def test_update_maps_to_controller_key(self) -> None:
        assert to_controller_update({"multicast_enhance_enabled": True}) == {"mcastenhance_enabled": True}

    def test_update_maps_false_to_controller_key(self) -> None:
        assert to_controller_update({"multicast_enhance_enabled": False}) == {"mcastenhance_enabled": False}

    def test_create_maps_to_controller_key(self) -> None:
        model = Wlan(name="SSID", security="open", multicast_enhance_enabled=True)
        payload = to_controller_create(model)
        assert payload["mcastenhance_enabled"] is True
        assert "multicast_enhance_enabled" not in payload

    def test_controller_key_alias_accepted_on_update(self) -> None:
        """Callers may pass the controller field name directly, as with networkconf_id."""
        assert to_controller_update({"mcastenhance_enabled": True}) == {"mcastenhance_enabled": True}

    def test_validate_update_accepts_either_name(self) -> None:
        """The public validator reaches the controller key from both spellings."""
        assert validate_update({"multicast_enhance_enabled": True}) == {"mcastenhance_enabled": True}
        assert validate_update({"mcastenhance_enabled": False}) == {"mcastenhance_enabled": False}

    def test_validate_create_maps_to_controller_key(self) -> None:
        payload = validate_create({"name": "SSID", "security": "open", "multicast_enhance_enabled": True})
        assert payload["mcastenhance_enabled"] is True
        assert "multicast_enhance_enabled" not in payload


class TestSettingPreference:
    """The SSID's Advanced mode (UI: Auto | Manual), exposed read-only.

    While it is "auto" the controller manages a set of advanced settings itself
    and omits them from the WLAN object; switching to "manual" makes them
    appear. The field was absent from the canonical model, so the mode governing
    them was not available through typed REST and GraphQL responses.

    It is deliberately NOT mutable. Changing it makes the controller rebuild the
    WLAN object — observed regenerating ``external_id`` and normalising away
    stale keys — and which settings the mode covers is controller-version
    specific, so a write path here would be a footgun rather than a feature.
    """

    def test_setting_preference_is_read_only(self) -> None:
        assert "setting_preference" in READ_ONLY_FIELDS
        assert "setting_preference" not in MUTABLE_FIELDS

    def test_from_controller_reads_setting_preference(self) -> None:
        assert from_controller({"_id": "w", "setting_preference": "auto"}).setting_preference == "auto"
        assert from_controller({"_id": "w", "setting_preference": "manual"}).setting_preference == "manual"

    def test_absent_setting_preference_is_none(self) -> None:
        assert from_controller({"_id": "w"}).setting_preference is None

    def test_validate_update_rejects_setting_preference(self) -> None:
        with pytest.raises(ValueError, match="read-only"):
            validate_update({"setting_preference": "manual", "enabled": True})

    def test_validate_create_rejects_setting_preference(self) -> None:
        with pytest.raises(ValueError, match="read-only"):
            validate_create(
                {
                    "name": "SSID",
                    "security": "open",
                    "setting_preference": "manual",
                }
            )
