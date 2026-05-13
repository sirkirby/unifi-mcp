"""Unit tests for the Access AccessSystemInfo and AccessHealth read-only domain models."""

from __future__ import annotations

import pytest

from unifi_core.access.models.system import (
    AccessSystemInfo,
    AccessHealth,
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    system_info_from_controller,
    health_from_controller,
)


class TestFieldSets:
    def test_mutable_fields_is_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset(), "System models are read-only; MUTABLE_FIELDS must be empty"

    def test_read_only_covers_system_info_fields(self) -> None:
        for field in ("name", "version", "hostname", "uptime"):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_read_only_covers_health_fields(self) -> None:
        for field in ("status", "num_doors", "num_devices", "num_offline_devices"):
            assert field in READ_ONLY_FIELDS, f"Expected {field!r} in READ_ONLY_FIELDS"

    def test_read_only_is_union_of_both_class_fields(self) -> None:
        expected = frozenset(AccessSystemInfo.model_fields.keys()) | frozenset(AccessHealth.model_fields.keys())
        assert READ_ONLY_FIELDS == expected

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"


class TestSystemInfoFromController:
    def test_full_dict(self) -> None:
        raw = {
            "name": "UniFi Access",
            "version": "2.13.4",
            "hostname": "access.example.com",
            "uptime": 86400,
        }
        info = system_info_from_controller(raw)
        assert info.name == "UniFi Access"
        assert info.version == "2.13.4"
        assert info.hostname == "access.example.com"
        assert info.uptime == 86400

    def test_missing_fields_are_none(self) -> None:
        info = system_info_from_controller({})
        assert info.name is None
        assert info.version is None
        assert info.hostname is None
        assert info.uptime is None

    def test_name_fallback_to_source(self) -> None:
        """Falls back to 'source' when 'name' is absent."""
        info = system_info_from_controller({"source": "access-proxy", "version": "2.0.0"})
        assert info.name == "access-proxy"
        assert info.version == "2.0.0"

    def test_hostname_fallback_to_host(self) -> None:
        """Falls back to 'host' when 'hostname' is absent."""
        info = system_info_from_controller({"host": "192.168.1.50"})
        assert info.hostname == "192.168.1.50"

    def test_partial_dict(self) -> None:
        info = system_info_from_controller({"name": "UA", "uptime": 3600})
        assert info.name == "UA"
        assert info.uptime == 3600
        assert info.version is None
        assert info.hostname is None

    def test_from_object(self) -> None:
        """system_info_from_controller works with an attribute-bearing object."""
        class Obj:
            name = "UniFi Access"
            version = "1.0.0"
            hostname = "access.local"
            uptime = 1000
            source = None
            host = None

        info = system_info_from_controller(Obj())
        assert info.name == "UniFi Access"
        assert info.version == "1.0.0"
        assert info.hostname == "access.local"
        assert info.uptime == 1000

    def test_model_dump_exclude_none_omits_missing(self) -> None:
        info = system_info_from_controller({"name": "Access", "version": "3.0.0"})
        dumped = info.model_dump(exclude_none=True)
        assert "name" in dumped
        assert "version" in dumped
        assert "hostname" not in dumped
        assert "uptime" not in dumped


class TestHealthFromController:
    def test_full_dict_with_explicit_status(self) -> None:
        raw = {
            "status": "healthy",
            "num_doors": 5,
            "num_devices": 10,
            "num_offline_devices": 1,
        }
        health = health_from_controller(raw)
        assert health.status == "healthy"
        assert health.num_doors == 5
        assert health.num_devices == 10
        assert health.num_offline_devices == 1

    def test_missing_fields_are_none_except_status(self) -> None:
        """status has default 'unknown', other fields default to None."""
        health = health_from_controller({})
        assert health.status == "unknown"
        assert health.num_doors is None
        assert health.num_devices is None
        assert health.num_offline_devices is None

    def test_status_derived_from_both_flags_healthy(self) -> None:
        raw = {"api_client_healthy": True, "proxy_healthy": True}
        health = health_from_controller(raw)
        assert health.status == "healthy"

    def test_status_derived_from_one_flag_degraded(self) -> None:
        raw = {"api_client_healthy": True, "proxy_healthy": False}
        health = health_from_controller(raw)
        assert health.status == "degraded"

    def test_status_derived_from_both_flags_unhealthy(self) -> None:
        raw = {"api_client_healthy": False, "proxy_healthy": False}
        health = health_from_controller(raw)
        assert health.status == "unhealthy"

    def test_status_derived_from_is_connected_true(self) -> None:
        raw = {"is_connected": True}
        health = health_from_controller(raw)
        assert health.status == "healthy"

    def test_status_derived_from_is_connected_false(self) -> None:
        raw = {"is_connected": False}
        health = health_from_controller(raw)
        assert health.status == "unknown"

    def test_explicit_status_wins_over_flags(self) -> None:
        """Explicit 'status' key takes precedence over computed flag logic."""
        raw = {"status": "degraded", "api_client_healthy": True, "proxy_healthy": True}
        health = health_from_controller(raw)
        assert health.status == "degraded"

    def test_partial_dict(self) -> None:
        raw = {"status": "healthy", "num_doors": 3}
        health = health_from_controller(raw)
        assert health.status == "healthy"
        assert health.num_doors == 3
        assert health.num_devices is None
        assert health.num_offline_devices is None

    def test_from_object(self) -> None:
        """health_from_controller works with an attribute-bearing object."""
        class Obj:
            status = "healthy"
            num_doors = 4
            num_devices = 8
            num_offline_devices = 0
            api_client_healthy = None
            proxy_healthy = None
            is_connected = None

        health = health_from_controller(Obj())
        assert health.status == "healthy"
        assert health.num_doors == 4
        assert health.num_devices == 8
        assert health.num_offline_devices == 0

    def test_model_dump_exclude_none_omits_missing(self) -> None:
        health = health_from_controller({"status": "healthy", "num_doors": 2})
        dumped = health.model_dump(exclude_none=True)
        assert "status" in dumped
        assert "num_doors" in dumped
        assert "num_devices" not in dumped
        assert "num_offline_devices" not in dumped
