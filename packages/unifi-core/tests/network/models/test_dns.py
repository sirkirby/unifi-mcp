"""Unit tests for the Network DnsRecord CRUD domain model."""

from __future__ import annotations

from unifi_core.network.models.dns import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    DnsRecord,
    from_controller,
    to_controller_create,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in ("key", "value", "record_type", "enabled", "ttl", "port", "priority", "weight"):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_id(self) -> None:
        assert "id" not in MUTABLE_FIELDS

    def test_read_only_fields_contains_id(self) -> None:
        assert "id" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(DnsRecord.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "_id": "dns-1",
            "key": "myhost.example.com",
            "value": "192.168.1.100",
            "record_type": "A",
            "enabled": True,
            "ttl": 300,
            "port": 0,
            "priority": 0,
            "weight": 0,
        }
        r = from_controller(raw)
        assert r.id == "dns-1"
        assert r.key == "myhost.example.com"
        assert r.value == "192.168.1.100"
        assert r.record_type == "A"
        assert r.enabled is True
        assert r.ttl == 300

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "key": "test.local", "value": "1.2.3.4", "record_type": "A"}
        r = from_controller(raw)
        assert r.id == "abc"

    def test_key_coalesces_hostname(self) -> None:
        raw = {"_id": "r1", "hostname": "test.local", "value": "1.2.3.4", "record_type": "A"}
        r = from_controller(raw)
        assert r.key == "test.local"

    def test_value_coalesces_ip(self) -> None:
        raw = {"_id": "r2", "key": "test.local", "ip": "1.2.3.4", "record_type": "A"}
        r = from_controller(raw)
        assert r.value == "1.2.3.4"

    def test_record_type_coalesces_type(self) -> None:
        raw = {"_id": "r3", "key": "test.local", "value": "1.2.3.4", "type": "A"}
        r = from_controller(raw)
        assert r.record_type == "A"

    def test_enabled_false_preserved(self) -> None:
        raw = {"_id": "r4", "enabled": False}
        r = from_controller(raw)
        assert r.enabled is False

    def test_missing_enabled_defaults_to_none(self) -> None:
        raw = {"_id": "r5"}
        r = from_controller(raw)
        assert r.enabled is None

    def test_srv_fields_populated(self) -> None:
        raw = {
            "_id": "r6",
            "key": "srv.local",
            "value": "target.local",
            "record_type": "SRV",
            "port": 8080,
            "priority": 10,
            "weight": 20,
        }
        r = from_controller(raw)
        assert r.port == 8080
        assert r.priority == 10
        assert r.weight == 20

    def test_handles_empty_dict(self) -> None:
        r = from_controller({})
        assert r.id is None
        assert r.key is None
        assert r.value is None
        assert r.record_type is None

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

    def test_none_fields_excluded(self) -> None:
        model = DnsRecord(key="test.local", value="1.2.3.4", record_type="A")
        payload = to_controller_create(model)
        assert "port" not in payload
        assert "priority" not in payload
        assert "weight" not in payload
        assert "enabled" not in payload

    def test_read_only_id_excluded(self) -> None:
        model = DnsRecord(id="should-not-appear", key="test.local", value="1.2.3.4", record_type="A")
        payload = to_controller_create(model)
        assert "id" not in payload


class TestToControllerUpdate:
    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "key": "new.local"})
        assert "id" not in result
        assert result["key"] == "new.local"

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"key": None, "value": "1.2.3.4"})
        assert "key" not in result
        assert result["value"] == "1.2.3.4"

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

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "key": "test.local"})
        assert "unknown" not in result
        assert result["key"] == "test.local"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only"})
        assert result == {}

    def test_ttl_zero_preserved(self) -> None:
        """TTL=0 is a valid value that means 'use default'."""
        result = to_controller_update({"ttl": 0})
        # 0 is falsy but not None — however our implementation drops falsy==None
        # The ttl=0 case: 0 is not None, so it should pass through
        # (current impl: v is not None — 0 is not None, so preserved)
        assert result.get("ttl") == 0
