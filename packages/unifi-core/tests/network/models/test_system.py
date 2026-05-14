"""Unit tests for the Network system models (Scope-A + Scope-B)."""

from __future__ import annotations

from unifi_core.network.models.system import (
    ALARM_MUTABLE_FIELDS,
    ALARM_READ_ONLY_FIELDS,
    AUTOBACKUPSETTINGS_MUTABLE_FIELDS,
    AUTOBACKUPSETTINGS_READ_ONLY_FIELDS,
    BACKUP_MUTABLE_FIELDS,
    BACKUP_READ_ONLY_FIELDS,
    EVENTTYPES_MUTABLE_FIELDS,
    EVENTTYPES_READ_ONLY_FIELDS,
    NETWORKHEALTH_MUTABLE_FIELDS,
    NETWORKHEALTH_READ_ONLY_FIELDS,
    SITESETTINGS_MUTABLE_FIELDS,
    SITESETTINGS_READ_ONLY_FIELDS,
    SNMPSETTINGS_MUTABLE_FIELDS,
    SNMPSETTINGS_READ_ONLY_FIELDS,
    SPEEDTESTRESULT_MUTABLE_FIELDS,
    SPEEDTESTRESULT_READ_ONLY_FIELDS,
    SYSTEMINFO_MUTABLE_FIELDS,
    SYSTEMINFO_READ_ONLY_FIELDS,
    TOPCLIENT_MUTABLE_FIELDS,
    TOPCLIENT_READ_ONLY_FIELDS,
    Alarm,
    AutoBackupSettings,
    Backup,
    EventTypes,
    NetworkHealth,
    SiteSettings,
    SnmpSettings,
    SpeedtestResult,
    SystemInfo,
    TopClient,
    alarm_from_controller,
    autobackup_from_controller,
    autobackup_to_controller_update,
    backup_from_controller,
    event_types_from_controller,
    network_health_from_controller,
    site_settings_from_controller,
    snmp_from_controller,
    snmp_to_controller_update,
    speedtest_result_from_controller,
    system_info_from_controller,
    top_client_from_controller,
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
            "autobackup_enabled",
            "autobackup_cron_expr",
            "autobackup_days",
            "autobackup_max_files",
            "autobackup_timezone",
            "autobackup_cloud_enabled",
        ):
            assert field in AUTOBACKUPSETTINGS_MUTABLE_FIELDS, (
                f"Expected {field!r} in AUTOBACKUPSETTINGS_MUTABLE_FIELDS"
            )

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


# ===========================================================================
# Scope-B read-only model tests
# ===========================================================================


class TestScopeBFieldSets:
    """All Scope-B models are read-only: MUTABLE_FIELDS empty, READ_ONLY_FIELDS full."""

    def _check_read_only(self, cls, mutable_fs, ro_fs) -> None:
        assert mutable_fs == frozenset()
        assert ro_fs == frozenset(cls.model_fields.keys())
        assert mutable_fs & ro_fs == frozenset()

    def test_system_info(self) -> None:
        self._check_read_only(SystemInfo, SYSTEMINFO_MUTABLE_FIELDS, SYSTEMINFO_READ_ONLY_FIELDS)

    def test_network_health(self) -> None:
        self._check_read_only(NetworkHealth, NETWORKHEALTH_MUTABLE_FIELDS, NETWORKHEALTH_READ_ONLY_FIELDS)

    def test_alarm(self) -> None:
        self._check_read_only(Alarm, ALARM_MUTABLE_FIELDS, ALARM_READ_ONLY_FIELDS)

    def test_backup(self) -> None:
        self._check_read_only(Backup, BACKUP_MUTABLE_FIELDS, BACKUP_READ_ONLY_FIELDS)

    def test_site_settings(self) -> None:
        self._check_read_only(SiteSettings, SITESETTINGS_MUTABLE_FIELDS, SITESETTINGS_READ_ONLY_FIELDS)

    def test_event_types(self) -> None:
        self._check_read_only(EventTypes, EVENTTYPES_MUTABLE_FIELDS, EVENTTYPES_READ_ONLY_FIELDS)

    def test_top_client(self) -> None:
        self._check_read_only(TopClient, TOPCLIENT_MUTABLE_FIELDS, TOPCLIENT_READ_ONLY_FIELDS)

    def test_speedtest_result(self) -> None:
        self._check_read_only(SpeedtestResult, SPEEDTESTRESULT_MUTABLE_FIELDS, SPEEDTESTRESULT_READ_ONLY_FIELDS)


class TestSystemInfoFromController:
    def test_full_payload(self) -> None:
        raw = {
            "name": "My Controller",
            "version": "7.2.95",
            "hostname": "unifi.local",
            "uptime": 86400,
            "num_devices": 5,
            "num_clients": 12,
        }
        si = system_info_from_controller(raw)
        assert si.name == "My Controller"
        assert si.version == "7.2.95"
        assert si.hostname == "unifi.local"
        assert si.uptime == 86400
        assert si.num_devices == 5
        assert si.num_clients == 12

    def test_controller_name_fallback(self) -> None:
        raw = {"controller_name": "Fallback", "build": "1.2.3"}
        si = system_info_from_controller(raw)
        assert si.name == "Fallback"
        assert si.version == "1.2.3"

    def test_empty_dict_returns_defaults(self) -> None:
        si = system_info_from_controller({})
        assert si.name is None
        assert si.version is None

    def test_non_dict_returns_defaults(self) -> None:
        si = system_info_from_controller(None)
        assert si.name is None


class TestNetworkHealthFromController:
    def test_full_subsystem(self) -> None:
        raw = {
            "subsystem": "wan",
            "status": "ok",
            "num_user": 3,
            "num_guest": 0,
            "num_iot": 1,
            "rx_bytes-r": 1024,
            "tx_bytes-r": 2048,
        }
        nh = network_health_from_controller(raw)
        assert nh.subsystem == "wan"
        assert nh.status == "ok"
        assert nh.num_user == 3
        assert nh.num_guest == 0
        assert nh.num_iot == 1
        assert nh.rx_bytes == 1024
        assert nh.tx_bytes == 2048

    def test_rx_tx_fallback_keys(self) -> None:
        raw = {"rx_bytes": 500, "tx_bytes": 700}
        nh = network_health_from_controller(raw)
        assert nh.rx_bytes == 500
        assert nh.tx_bytes == 700

    def test_empty_dict_returns_defaults(self) -> None:
        nh = network_health_from_controller({})
        assert nh.subsystem is None
        assert nh.rx_bytes is None

    def test_non_dict_returns_defaults(self) -> None:
        nh = network_health_from_controller(None)
        assert nh.status is None


class TestAlarmFromController:
    def test_full_alarm(self) -> None:
        raw = {
            "_id": "alarm-1",
            "key": "EVT_SW_PoeOverload",
            "msg": "PoE overload on port 3",
            "archived": False,
            "time": 1700000000,
        }
        alarm = alarm_from_controller(raw)
        assert alarm.id == "alarm-1"
        assert alarm.key == "EVT_SW_PoeOverload"
        assert alarm.msg == "PoE overload on port 3"
        assert alarm.archived is False
        assert alarm.time == 1700000000

    def test_id_coalesces_plain_id(self) -> None:
        raw = {"id": "alarm-2"}
        alarm = alarm_from_controller(raw)
        assert alarm.id == "alarm-2"

    def test_key_fallback_to_event_type(self) -> None:
        raw = {"event_type": "EVT_LU_Disconnected"}
        alarm = alarm_from_controller(raw)
        assert alarm.key == "EVT_LU_Disconnected"

    def test_msg_fallback_to_message(self) -> None:
        raw = {"message": "Some message"}
        alarm = alarm_from_controller(raw)
        assert alarm.msg == "Some message"

    def test_archived_defaults_false(self) -> None:
        alarm = alarm_from_controller({})
        assert alarm.archived is False

    def test_non_dict_returns_defaults(self) -> None:
        alarm = alarm_from_controller(None)
        assert alarm.id is None
        assert alarm.archived is False


class TestBackupFromController:
    def test_full_backup(self) -> None:
        raw = {
            "_id": "bk-1",
            "filename": "autobackup_5.73.62.0_20231001_1200.unf",
            "size": 1048576,
            "time": 1696154400,
        }
        bk = backup_from_controller(raw)
        assert bk.id == "bk-1"
        assert bk.filename == "autobackup_5.73.62.0_20231001_1200.unf"
        assert bk.size == 1048576
        assert bk.created_at == 1696154400

    def test_filename_fallback_to_name(self) -> None:
        raw = {"name": "backup.unf"}
        bk = backup_from_controller(raw)
        assert bk.filename == "backup.unf"

    def test_created_at_fallback_keys(self) -> None:
        raw = {"created_at": 9999, "filename": "f.unf"}
        bk = backup_from_controller(raw)
        assert bk.created_at == 9999

    def test_empty_dict_returns_defaults(self) -> None:
        bk = backup_from_controller({})
        assert bk.id is None
        assert bk.filename is None

    def test_non_dict_returns_defaults(self) -> None:
        bk = backup_from_controller(None)
        assert bk.id is None


class TestSiteSettingsFromController:
    def test_sections_based_payload(self) -> None:
        raw = {
            "sections": {
                "super_identity": {"_id": "site-1", "name": "Home", "role": "master"},
                "country": {"code": 840},
            }
        }
        ss = site_settings_from_controller(raw)
        assert ss.site_id == "site-1"
        assert ss.name == "Home"
        assert ss.role == "master"
        assert ss.country == 840

    def test_flat_payload_fallback(self) -> None:
        raw = {"_id": "site-2", "name": "Office", "country": "276"}
        ss = site_settings_from_controller(raw)
        assert ss.site_id == "site-2"
        assert ss.name == "Office"
        assert ss.country == 276

    def test_country_coerced_to_int(self) -> None:
        raw = {"country": "392"}
        ss = site_settings_from_controller(raw)
        assert ss.country == 392

    def test_invalid_country_becomes_none(self) -> None:
        raw = {"country": "not-a-number"}
        ss = site_settings_from_controller(raw)
        assert ss.country is None

    def test_empty_dict_returns_defaults(self) -> None:
        ss = site_settings_from_controller({})
        assert ss.site_id is None
        assert ss.country is None

    def test_non_dict_returns_defaults(self) -> None:
        ss = site_settings_from_controller(None)
        assert ss.site_id is None


class TestEventTypesFromController:
    def test_list_input(self) -> None:
        raw = [{"prefix": "EVT_SW_", "desc": "Switch events"}]
        et = event_types_from_controller(raw)
        assert et.event_types == [{"prefix": "EVT_SW_", "desc": "Switch events"}]

    def test_list_filters_non_dicts(self) -> None:
        raw = [{"prefix": "EVT_LU_"}, "not-a-dict", 42]
        et = event_types_from_controller(raw)
        assert et.event_types == [{"prefix": "EVT_LU_"}]

    def test_dict_with_event_types_key(self) -> None:
        raw = {"event_types": [{"prefix": "EVT_WU_"}]}
        et = event_types_from_controller(raw)
        assert et.event_types == [{"prefix": "EVT_WU_"}]

    def test_plain_dict_wraps_in_list(self) -> None:
        raw = {"prefix": "EVT_GW_"}
        et = event_types_from_controller(raw)
        assert et.event_types == [{"prefix": "EVT_GW_"}]

    def test_non_list_non_dict_returns_empty(self) -> None:
        et = event_types_from_controller(None)
        assert et.event_types == []


class TestTopClientFromController:
    def test_full_record(self) -> None:
        raw = {
            "mac": "aa:bb:cc:dd:ee:ff",
            "name": "My Laptop",
            "tx_bytes": 1000,
            "rx_bytes": 2000,
            "total_bytes": 3000,
        }
        tc = top_client_from_controller(raw)
        assert tc.mac == "aa:bb:cc:dd:ee:ff"
        assert tc.hostname == "My Laptop"
        assert tc.tx_bytes == 1000
        assert tc.rx_bytes == 2000
        assert tc.total_bytes == 3000

    def test_hostname_fallback(self) -> None:
        raw = {"hostname": "Phone", "mac": "11:22:33:44:55:66"}
        tc = top_client_from_controller(raw)
        assert tc.hostname == "Phone"

    def test_total_bytes_fallback_to_bytes(self) -> None:
        raw = {"bytes": 5000}
        tc = top_client_from_controller(raw)
        assert tc.total_bytes == 5000

    def test_empty_dict_returns_defaults(self) -> None:
        tc = top_client_from_controller({})
        assert tc.mac is None
        assert tc.total_bytes is None

    def test_non_dict_returns_defaults(self) -> None:
        tc = top_client_from_controller(None)
        assert tc.mac is None


class TestSpeedtestResultFromController:
    def test_full_record(self) -> None:
        raw = {
            "time": 1700000000,
            "xput_download": 250.5,
            "xput_upload": 120.3,
            "latency": 12.4,
        }
        sr = speedtest_result_from_controller(raw)
        assert sr.timestamp == 1700000000
        assert sr.download_mbps == 250.5
        assert sr.upload_mbps == 120.3
        assert sr.latency_ms == 12.4

    def test_timestamp_fallback(self) -> None:
        raw = {"timestamp": 1234567890}
        sr = speedtest_result_from_controller(raw)
        assert sr.timestamp == 1234567890

    def test_download_fallback_key(self) -> None:
        raw = {"download_mbps": 300.0}
        sr = speedtest_result_from_controller(raw)
        assert sr.download_mbps == 300.0

    def test_empty_dict_returns_defaults(self) -> None:
        sr = speedtest_result_from_controller({})
        assert sr.timestamp is None
        assert sr.download_mbps is None

    def test_non_dict_returns_defaults(self) -> None:
        sr = speedtest_result_from_controller(None)
        assert sr.timestamp is None
