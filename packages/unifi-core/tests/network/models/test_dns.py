"""Unit tests for the Network DnsRecord CRUD domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.dns import (
    DnsRecord,
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
                    "_id": "dns-1",
                    "key": "myhost.example.com",
                    "value": "192.168.1.100",
                    "record_type": "A",
                    "enabled": True,
                    "ttl": 300,
                    "port": 0,
                    "priority": 0,
                    "weight": 0,
                },
                {
                    "id": "dns-1",
                    "key": "myhost.example.com",
                    "value": "192.168.1.100",
                    "record_type": "A",
                    "enabled": True,
                    "ttl": 300,
                },
            ),
            ({"_id": "abc", "key": "test.local", "value": "1.2.3.4", "record_type": "A"}, {"id": "abc"}),
            ({"_id": "r1", "hostname": "test.local", "value": "1.2.3.4", "record_type": "A"}, {"key": "test.local"}),
            ({"_id": "r2", "key": "test.local", "ip": "1.2.3.4", "record_type": "A"}, {"value": "1.2.3.4"}),
            ({"_id": "r3", "key": "test.local", "value": "1.2.3.4", "type": "A"}, {"record_type": "A"}),
            ({"_id": "r4", "enabled": False}, {"enabled": False}),
            ({"_id": "r5"}, {"enabled": None}),
            (
                {
                    "_id": "r6",
                    "key": "srv.local",
                    "value": "target.local",
                    "record_type": "SRV",
                    "port": 8080,
                    "priority": 10,
                    "weight": 20,
                },
                {"port": 8080, "priority": 10, "weight": 20},
            ),
            ({}, {"id": None, "key": None, "value": None, "record_type": None}),
        ],
        ids=[
            "full_dict",
            "id_coalesces_underscore_id",
            "key_coalesces_hostname",
            "value_coalesces_ip",
            "record_type_coalesces_type",
            "enabled_false_preserved",
            "missing_enabled_defaults_to_none",
            "srv_fields_populated",
            "handles_empty_dict",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)

    def test_ttl_bounds_not_enforced_on_read(self) -> None:
        """TTL=0 is valid (means use default)."""
        raw = {"_id": "r7", "ttl": 0}
        r = from_controller(raw)
        assert r.ttl == 0


class TestToControllerCreate:
    def test_full_model(self) -> None:
        model = DnsRecord(key="test.local", value="1.2.3.4", record_type="A", enabled=True, ttl=300)
        payload = to_controller_create(model)
        assert payload["key"] == "test.local"
        assert payload["value"] == "1.2.3.4"
        assert payload["record_type"] == "A"
        assert payload["enabled"] is True
        assert payload["ttl"] == 300


class TestToControllerUpdate:
    def test_passes_all_mutable_fields(self) -> None:
        fields = {
            "key": "x.local",
            "value": "1.2.3.4",
            "record_type": "A",
            "enabled": True,
            "ttl": 60,
            "port": 80,
            "priority": 5,
            "weight": 10,
        }
        result = to_controller_update(fields)
        assert result == fields

    def test_ttl_zero_preserved(self) -> None:
        """TTL=0 is a valid value that means 'use default'."""
        result = to_controller_update({"ttl": 0})
        # 0 is falsy but not None — however our implementation drops falsy==None
        # The ttl=0 case: 0 is not None, so it should pass through
        # (current impl: v is not None — 0 is not None, so preserved)
        assert result.get("ttl") == 0
