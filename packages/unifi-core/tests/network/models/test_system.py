"""Unit tests for the Network SnmpSettings + AutoBackupSettings CRUD models."""

from __future__ import annotations

import pytest

from unifi_core.network.models.system import (
    AUTOBACKUPSETTINGS_MUTABLE_FIELDS,
    AUTOBACKUPSETTINGS_READ_ONLY_FIELDS,
    SNMPSETTINGS_MUTABLE_FIELDS,
    SNMPSETTINGS_READ_ONLY_FIELDS,
    AutoBackupSettings,
    SnmpSettings,
    autobackup_from_controller,
    autobackup_to_controller_update,
    snmp_from_controller,
    snmp_to_controller_update,
)


class TestSnmpSettingsFieldSets:
    def test_mutable_fields_contains_enabled_and_community(self) -> None:
        assert "enabled" in SNMPSETTINGS_MUTABLE_FIELDS
        assert "community" in SNMPSETTINGS_MUTABLE_FIELDS

    def test_mutable_fields_excludes_port_and_version(self) -> None:
        assert "port" not in SNMPSETTINGS_MUTABLE_FIELDS
        assert "version" not in SNMPSETTINGS_MUTABLE_FIELDS

    def test_read_only_fields_contains_port_and_version(self) -> None:
        assert "port" in SNMPSETTINGS_READ_ONLY_FIELDS
        assert "version" in SNMPSETTINGS_READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = SNMPSETTINGS_MUTABLE_FIELDS & SNMPSETTINGS_READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_cover_all_model_fields(self) -> None:
        all_fields = frozenset(SnmpSettings.model_fields.keys())
        assert SNMPSETTINGS_MUTABLE_FIELDS | SNMPSETTINGS_READ_ONLY_FIELDS == all_fields


class TestAutoBackupSettingsFieldSets:
    def test_mutable_fields_contains_all_autobackup_keys(self) -> None:
        for field in (
            "autobackup_enabled", "autobackup_cron_expr", "autobackup_days",
            "autobackup_max_files", "autobackup_timezone", "autobackup_cloud_enabled",
        ):
            assert field in AUTOBACKUPSETTINGS_MUTABLE_FIELDS, f"Expected {field!r} in AUTOBACKUPSETTINGS_MUTABLE_FIELDS"

    def test_all_autobackup_fields_are_mutable(self) -> None:
        assert AUTOBACKUPSETTINGS_READ_ONLY_FIELDS == frozenset()

    def test_cover_all_model_fields(self) -> None:
        all_fields = frozenset(AutoBackupSettings.model_fields.keys())
        assert AUTOBACKUPSETTINGS_MUTABLE_FIELDS | AUTOBACKUPSETTINGS_READ_ONLY_FIELDS == all_fields


class TestSnmpFromController:
    def test_full_snmp_settings(self) -> None:
        raw = {
            "enabled": True,
            "community": "public",
            "port": 161,
            "version": "v2c",
        }
        settings = snmp_from_controller(raw)
        assert settings.enabled is True
        assert settings.community == "public"
        assert settings.port == 161
        assert settings.version == "v2c"

    def test_unwraps_list(self) -> None:
        raw = [{"enabled": False, "community": "private"}]
        settings = snmp_from_controller(raw)
        assert settings.enabled is False
        assert settings.community == "private"

    def test_empty_list_returns_default(self) -> None:
        settings = snmp_from_controller([])
        assert settings.enabled is None

    def test_handles_dict_input(self) -> None:
        settings = snmp_from_controller({"enabled": True})
        assert settings.enabled is True


class TestSnmpToControllerUpdate:
    def test_allows_mutable_fields(self) -> None:
        result = snmp_to_controller_update({"enabled": True, "community": "private"})
        assert result == {"enabled": True, "community": "private"}

    def test_drops_read_only_fields(self) -> None:
        result = snmp_to_controller_update({"port": 161, "version": "v2", "enabled": True})
        assert "port" not in result
        assert "version" not in result
        assert result["enabled"] is True

    def test_drops_none_values(self) -> None:
        result = snmp_to_controller_update({"enabled": None, "community": "public"})
        assert "enabled" not in result
        assert result["community"] == "public"

    def test_drops_unrecognised_keys(self) -> None:
        result = snmp_to_controller_update({"unknown": "value", "enabled": True})
        assert "unknown" not in result
        assert result["enabled"] is True


class TestAutoBackupFromController:
    def test_full_autobackup_settings(self) -> None:
        raw = {
            "autobackup_enabled": True,
            "autobackup_cron_expr": "30 2 * * *",
            "autobackup_days": 7,
            "autobackup_max_files": 3,
            "autobackup_timezone": "America/Denver",
            "autobackup_cloud_enabled": False,
        }
        settings = autobackup_from_controller(raw)
        assert settings.autobackup_enabled is True
        assert settings.autobackup_cron_expr == "30 2 * * *"
        assert settings.autobackup_days == 7
        assert settings.autobackup_max_files == 3
        assert settings.autobackup_timezone == "America/Denver"
        assert settings.autobackup_cloud_enabled is False

    def test_handles_empty_dict(self) -> None:
        settings = autobackup_from_controller({})
        assert settings.autobackup_enabled is None
        assert settings.autobackup_cron_expr is None

    def test_handles_non_dict(self) -> None:
        settings = autobackup_from_controller(None)
        assert settings.autobackup_enabled is None


class TestAutoBackupToControllerUpdate:
    def test_allows_all_mutable_fields(self) -> None:
        fields = {
            "autobackup_enabled": True,
            "autobackup_cron_expr": "0 3 * * *",
            "autobackup_days": 30,
            "autobackup_max_files": 5,
            "autobackup_timezone": "UTC",
            "autobackup_cloud_enabled": True,
        }
        result = autobackup_to_controller_update(fields)
        assert result == fields

    def test_drops_none_values(self) -> None:
        result = autobackup_to_controller_update({"autobackup_enabled": None, "autobackup_days": 7})
        assert "autobackup_enabled" not in result
        assert result["autobackup_days"] == 7

    def test_drops_unrecognised_keys(self) -> None:
        result = autobackup_to_controller_update({"unknown": "value", "autobackup_enabled": True})
        assert "unknown" not in result
        assert result["autobackup_enabled"] is True

    def test_preserves_false_boolean(self) -> None:
        result = autobackup_to_controller_update({"autobackup_cloud_enabled": False})
        # False should NOT be dropped (only None is dropped)
        assert "autobackup_cloud_enabled" in result
        assert result["autobackup_cloud_enabled"] is False
