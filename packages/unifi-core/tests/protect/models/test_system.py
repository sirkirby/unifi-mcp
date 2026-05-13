"""Unit tests for the Protect ProtectSystemInfo, ProtectHealth, FirmwareStatus,
Viewer, and ViewerList read-only models."""

from __future__ import annotations

from datetime import datetime, timezone

from unifi_core.protect.models.system import (
    FirmwareStatus,
    MUTABLE_FIELDS,
    ProtectHealth,
    ProtectSystemInfo,
    READ_ONLY_FIELDS,
    Viewer,
    ViewerList,
    firmware_status_from_controller,
    health_from_controller,
    system_info_from_controller,
    viewer_from_controller,
    viewer_list_from_controller,
)


class TestModelFields:
    def test_mutable_fields_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset()

    def test_read_only_fields_contains_all_system_info_fields(self) -> None:
        for field_name in ProtectSystemInfo.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_contains_all_health_fields(self) -> None:
        for field_name in ProtectHealth.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_contains_all_firmware_status_fields(self) -> None:
        for field_name in FirmwareStatus.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_contains_all_viewer_fields(self) -> None:
        for field_name in Viewer.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_contains_all_viewer_list_fields(self) -> None:
        for field_name in ViewerList.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_is_union_of_all_five_models(self) -> None:
        expected = (
            frozenset(ProtectSystemInfo.model_fields.keys())
            | frozenset(ProtectHealth.model_fields.keys())
            | frozenset(FirmwareStatus.model_fields.keys())
            | frozenset(Viewer.model_fields.keys())
            | frozenset(ViewerList.model_fields.keys())
        )
        assert READ_ONLY_FIELDS == expected


class TestSystemInfoFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "nvr-001",
            "name": "Test NVR",
            "model": "UDR",
            "firmware_version": "4.0.10",
            "version": "4.0.10",
            "host": "192.168.1.1",
            "mac": "AA:BB:CC:DD:EE:FF",
            "uptime_seconds": 172800,
            "up_since": "2026-05-11T12:00:00+00:00",
            "is_updating": False,
            "storage": {"utilization_pct": 50.0},
            "camera_count": 3,
            "light_count": 1,
            "sensor_count": 2,
            "viewer_count": 1,
            "chime_count": 0,
        }
        info = system_info_from_controller(raw)
        assert isinstance(info, ProtectSystemInfo)
        assert info.id == "nvr-001"
        assert info.name == "Test NVR"
        assert info.model == "UDR"
        assert info.firmware_version == "4.0.10"
        assert info.version == "4.0.10"
        assert info.host == "192.168.1.1"
        assert info.mac == "AA:BB:CC:DD:EE:FF"
        assert info.uptime_seconds == 172800
        assert info.up_since == "2026-05-11T12:00:00+00:00"
        assert info.is_updating is False
        assert info.storage == {"utilization_pct": 50.0}
        assert info.camera_count == 3
        assert info.light_count == 1
        assert info.sensor_count == 2
        assert info.viewer_count == 1
        assert info.chime_count == 0

    def test_missing_fields_default_to_none(self) -> None:
        info = system_info_from_controller({"id": "nvr-002"})
        assert info.id == "nvr-002"
        assert info.name is None
        assert info.storage is None
        assert info.camera_count is None

    def test_empty_dict(self) -> None:
        info = system_info_from_controller({})
        assert isinstance(info, ProtectSystemInfo)
        assert info.id is None

    def test_up_since_datetime_stringified(self) -> None:
        dt = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
        info = system_info_from_controller({"up_since": dt})
        assert info.up_since == dt.isoformat()

    def test_up_since_string_passthrough(self) -> None:
        info = system_info_from_controller({"up_since": "2026-05-11T12:00:00+00:00"})
        assert info.up_since == "2026-05-11T12:00:00+00:00"

    def test_storage_dict_passthrough(self) -> None:
        storage = {"utilization_pct": 42.0, "recording_space_total_bytes": 1000}
        info = system_info_from_controller({"storage": storage})
        assert info.storage == storage

    def test_storage_non_dict_coalesces_to_none(self) -> None:
        info = system_info_from_controller({"storage": "unexpected_string"})
        assert info.storage is None

    def test_storage_none_coalesces_to_none(self) -> None:
        info = system_info_from_controller({"storage": None})
        assert info.storage is None

    def test_model_dump_excludes_none(self) -> None:
        raw = {"id": "nvr-001", "name": "Test NVR", "camera_count": 2}
        info = system_info_from_controller(raw)
        dumped = info.model_dump(exclude_none=True)
        assert "id" in dumped
        assert "name" in dumped
        assert "camera_count" in dumped
        assert "storage" not in dumped
        assert "firmware_version" not in dumped


class TestHealthFromController:
    def test_full_dict(self) -> None:
        raw = {
            "cpu": {"average_load": 0.42, "temperature_c": 55.0},
            "memory": {"total_bytes": 4_000_000_000, "free_bytes": 1_000_000_000},
            "storage": {"size_bytes": 1_000_000_000, "used_bytes": 500_000_000},
            "is_updating": False,
            "uptime_seconds": 172800,
        }
        health = health_from_controller(raw)
        assert isinstance(health, ProtectHealth)
        assert health.cpu == {"average_load": 0.42, "temperature_c": 55.0}
        assert health.memory == {"total_bytes": 4_000_000_000, "free_bytes": 1_000_000_000}
        assert health.storage == {"size_bytes": 1_000_000_000, "used_bytes": 500_000_000}
        assert health.is_updating is False
        assert health.uptime_seconds == 172800

    def test_missing_fields_default_to_none(self) -> None:
        health = health_from_controller({"is_updating": True})
        assert health.is_updating is True
        assert health.cpu is None
        assert health.memory is None
        assert health.storage is None
        assert health.uptime_seconds is None

    def test_empty_dict(self) -> None:
        health = health_from_controller({})
        assert isinstance(health, ProtectHealth)
        assert health.cpu is None

    def test_cpu_dict_passthrough(self) -> None:
        cpu = {"average_load": 0.1, "temperature_c": 45.0}
        health = health_from_controller({"cpu": cpu})
        assert health.cpu == cpu

    def test_cpu_non_dict_coalesces_to_none(self) -> None:
        health = health_from_controller({"cpu": "string_value"})
        assert health.cpu is None

    def test_memory_list_passthrough(self) -> None:
        # list is also a valid JSON passthrough
        health = health_from_controller({"memory": [{"key": "val"}]})
        assert health.memory == [{"key": "val"}]

    def test_memory_non_dict_non_list_coalesces_to_none(self) -> None:
        health = health_from_controller({"memory": 12345})
        assert health.memory is None

    def test_model_dump_excludes_none(self) -> None:
        raw = {"cpu": {"average_load": 0.2}, "is_updating": False}
        health = health_from_controller(raw)
        dumped = health.model_dump(exclude_none=True)
        assert "cpu" in dumped
        assert "is_updating" in dumped
        assert "memory" not in dumped
        assert "storage" not in dumped


class TestFirmwareStatusFromController:
    def test_full_dict(self) -> None:
        raw = {
            "nvr": {"id": "nvr-001", "current_firmware": "4.0.10"},
            "devices": [{"id": "cam-001", "update_available": False}],
            "total_devices": 1,
            "devices_with_updates": 0,
        }
        status = firmware_status_from_controller(raw)
        assert isinstance(status, FirmwareStatus)
        assert status.nvr == {"id": "nvr-001", "current_firmware": "4.0.10"}
        assert status.devices == [{"id": "cam-001", "update_available": False}]
        assert status.total_devices == 1
        assert status.devices_with_updates == 0

    def test_missing_fields_default_to_none(self) -> None:
        status = firmware_status_from_controller({"total_devices": 5})
        assert status.total_devices == 5
        assert status.nvr is None
        assert status.devices is None
        assert status.devices_with_updates is None

    def test_empty_dict(self) -> None:
        status = firmware_status_from_controller({})
        assert isinstance(status, FirmwareStatus)
        assert status.nvr is None
        assert status.devices is None

    def test_nvr_dict_passthrough(self) -> None:
        nvr = {"id": "nvr-001", "update_available": True}
        status = firmware_status_from_controller({"nvr": nvr})
        assert status.nvr == nvr

    def test_devices_list_passthrough(self) -> None:
        devices = [{"id": "cam-001"}, {"id": "cam-002"}]
        status = firmware_status_from_controller({"devices": devices})
        assert status.devices == devices

    def test_nvr_non_dict_coalesces_to_none(self) -> None:
        status = firmware_status_from_controller({"nvr": "unexpected"})
        assert status.nvr is None

    def test_devices_non_list_non_dict_coalesces_to_none(self) -> None:
        status = firmware_status_from_controller({"devices": 42})
        assert status.devices is None

    def test_model_dump_excludes_none(self) -> None:
        raw = {"total_devices": 2, "devices_with_updates": 1}
        status = firmware_status_from_controller(raw)
        dumped = status.model_dump(exclude_none=True)
        assert "total_devices" in dumped
        assert "devices_with_updates" in dumped
        assert "nvr" not in dumped
        assert "devices" not in dumped


class TestViewerFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "viewer-001",
            "name": "Office Viewer",
            "type": "UP Viewport",
            "mac": "11:22:33:44:55:66",
            "host": "192.168.1.50",
            "firmware_version": "2.0.1",
            "is_connected": True,
            "is_updating": False,
            "uptime_seconds": 86400,
            "state": "CONNECTED",
            "software_version": "2.0.1",
            "liveview_id": "lv-001",
        }
        viewer = viewer_from_controller(raw)
        assert isinstance(viewer, Viewer)
        assert viewer.id == "viewer-001"
        assert viewer.name == "Office Viewer"
        assert viewer.type == "UP Viewport"
        assert viewer.mac == "11:22:33:44:55:66"
        assert viewer.host == "192.168.1.50"
        assert viewer.firmware_version == "2.0.1"
        assert viewer.is_connected is True
        assert viewer.is_updating is False
        assert viewer.uptime_seconds == 86400
        assert viewer.state == "CONNECTED"
        assert viewer.software_version == "2.0.1"
        assert viewer.liveview_id == "lv-001"

    def test_missing_fields_default_to_none(self) -> None:
        viewer = viewer_from_controller({"id": "viewer-002"})
        assert viewer.id == "viewer-002"
        assert viewer.name is None
        assert viewer.is_connected is None
        assert viewer.liveview_id is None

    def test_empty_dict(self) -> None:
        viewer = viewer_from_controller({})
        assert isinstance(viewer, Viewer)
        assert viewer.id is None

    def test_model_dump_excludes_none(self) -> None:
        raw = {"id": "viewer-003", "name": "Lobby", "state": "CONNECTED"}
        viewer = viewer_from_controller(raw)
        dumped = viewer.model_dump(exclude_none=True)
        assert "id" in dumped
        assert "name" in dumped
        assert "state" in dumped
        assert "firmware_version" not in dumped
        assert "liveview_id" not in dumped


class TestViewerListFromController:
    def test_full_wrapper_dict(self) -> None:
        raw = {
            "viewers": [
                {"id": "viewer-001", "name": "Office"},
                {"id": "viewer-002", "name": "Lobby"},
            ],
            "count": 2,
        }
        vl = viewer_list_from_controller(raw)
        assert isinstance(vl, ViewerList)
        assert len(vl.viewers) == 2
        assert vl.count == 2

    def test_bare_list_coerced_to_wrapper(self) -> None:
        raw = [{"id": "viewer-001"}, {"id": "viewer-002"}, {"id": "viewer-003"}]
        vl = viewer_list_from_controller(raw)
        assert isinstance(vl, ViewerList)
        assert isinstance(vl.viewers, list)
        assert len(vl.viewers) == 3
        assert vl.count == 3

    def test_empty_viewers_list(self) -> None:
        raw = {"viewers": [], "count": 0}
        vl = viewer_list_from_controller(raw)
        assert vl.viewers == []
        assert vl.count == 0

    def test_viewers_non_list_coalesces_to_none(self) -> None:
        raw = {"viewers": "unexpected_string", "count": 0}
        vl = viewer_list_from_controller(raw)
        assert vl.viewers is None

    def test_viewers_dict_coalesces_to_none(self) -> None:
        raw = {"viewers": {"unexpected": "dict"}, "count": 1}
        vl = viewer_list_from_controller(raw)
        assert vl.viewers is None

    def test_viewers_none_coalesces_to_none(self) -> None:
        raw = {"viewers": None, "count": 0}
        vl = viewer_list_from_controller(raw)
        assert vl.viewers is None

    def test_empty_dict(self) -> None:
        vl = viewer_list_from_controller({})
        assert isinstance(vl, ViewerList)
        assert vl.viewers is None
        assert vl.count is None

    def test_model_dump_excludes_none(self) -> None:
        raw = {"viewers": [{"id": "v1"}], "count": 1}
        vl = viewer_list_from_controller(raw)
        dumped = vl.model_dump(exclude_none=True)
        assert "viewers" in dumped
        assert "count" in dumped

    def test_model_dump_with_none_viewers_excludes_viewers(self) -> None:
        raw = {"count": 0}
        vl = viewer_list_from_controller(raw)
        dumped = vl.model_dump(exclude_none=True)
        assert "viewers" not in dumped
        assert "count" in dumped
