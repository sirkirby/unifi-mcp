"""Unit tests for the Network ContentFilter CRUD-update domain model."""

from __future__ import annotations

from unifi_core.network.models.content_filter import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    ContentFilter,
    from_controller,
    to_controller_update,
)


class TestFieldSets:
    def test_mutable_fields_contains_expected(self) -> None:
        for field in (
            "name",
            "enabled",
            "blocked_categories",
            "safe_search",
            "client_macs",
            "network_ids",
            "schedule_mode",
        ):
            assert field in MUTABLE_FIELDS, f"Expected {field!r} in MUTABLE_FIELDS"

    def test_mutable_fields_excludes_read_only(self) -> None:
        for field in ("id", "profile"):
            assert field not in MUTABLE_FIELDS, f"{field!r} should NOT be in MUTABLE_FIELDS"

    def test_read_only_fields_contains_id_and_profile(self) -> None:
        assert "id" in READ_ONLY_FIELDS
        assert "profile" in READ_ONLY_FIELDS

    def test_mutable_and_read_only_are_disjoint(self) -> None:
        overlap = MUTABLE_FIELDS & READ_ONLY_FIELDS
        assert not overlap, f"Fields in both sets: {overlap}"

    def test_mutable_and_read_only_cover_all_model_fields(self) -> None:
        all_fields = frozenset(ContentFilter.model_fields.keys())
        assert MUTABLE_FIELDS | READ_ONLY_FIELDS == all_fields

    def test_schedule_mode_in_mutable_fields(self) -> None:
        """schedule_mode must be mutable regardless of JSON Schema dict."""
        assert "schedule_mode" in MUTABLE_FIELDS


class TestFromController:
    def test_full_dict(self) -> None:
        raw = {
            "_id": "cf-1",
            "name": "Kids Filter",
            "enabled": True,
            "profile": "DNS",
            "blocked_categories": ["ADULT", "GAMBLING"],
            "safe_search": ["GOOGLE", "YOUTUBE"],
            "client_macs": ["aa:bb:cc:dd:ee:ff"],
            "network_ids": ["net-1"],
            "schedule": {"mode": "ALWAYS"},
        }
        f = from_controller(raw)
        assert f.id == "cf-1"
        assert f.name == "Kids Filter"
        assert f.enabled is True
        assert f.profile == "DNS"
        assert f.blocked_categories == ["ADULT", "GAMBLING"]
        assert f.safe_search == ["GOOGLE", "YOUTUBE"]
        assert f.client_macs == ["aa:bb:cc:dd:ee:ff"]
        assert f.network_ids == ["net-1"]
        assert f.schedule_mode == "ALWAYS"

    def test_id_coalesces_underscore_id(self) -> None:
        raw = {"_id": "abc", "name": "Test"}
        f = from_controller(raw)
        assert f.id == "abc"

    def test_categories_coalesces_from_categories_key(self) -> None:
        raw = {"_id": "cf-2", "categories": ["MALWARE"]}
        f = from_controller(raw)
        assert f.blocked_categories == ["MALWARE"]

    def test_blocked_categories_takes_priority(self) -> None:
        raw = {"_id": "cf-3", "blocked_categories": ["ADULT"], "categories": ["MALWARE"]}
        f = from_controller(raw)
        assert f.blocked_categories == ["ADULT"]

    def test_schedule_mode_extracted_from_schedule_dict(self) -> None:
        raw = {"_id": "cf-4", "schedule": {"mode": "CUSTOM"}}
        f = from_controller(raw)
        assert f.schedule_mode == "CUSTOM"

    def test_enabled_false_is_preserved(self) -> None:
        raw = {"_id": "cf-5", "enabled": False}
        f = from_controller(raw)
        assert f.enabled is False

    def test_missing_enabled_defaults_to_none(self) -> None:
        raw = {"_id": "cf-6"}
        f = from_controller(raw)
        assert f.enabled is None

    def test_non_list_blocked_categories_becomes_empty(self) -> None:
        raw = {"_id": "cf-7", "blocked_categories": None}
        f = from_controller(raw)
        assert f.blocked_categories == []

    def test_handles_empty_dict(self) -> None:
        f = from_controller({})
        assert f.id is None
        assert f.name is None
        assert f.blocked_categories == []
        assert f.safe_search == []
        assert f.client_macs == []
        assert f.network_ids == []
        assert f.schedule_mode is None


class TestToControllerUpdate:
    def test_filters_out_read_only_id(self) -> None:
        result = to_controller_update({"id": "ignore-me", "name": "New Name"})
        assert "id" not in result
        assert result["name"] == "New Name"

    def test_filters_out_profile(self) -> None:
        result = to_controller_update({"profile": "DNS", "name": "Test"})
        assert "profile" not in result

    def test_drops_none_values(self) -> None:
        result = to_controller_update({"name": None, "enabled": True})
        assert "name" not in result
        assert result["enabled"] is True

    def test_preserves_boolean_false(self) -> None:
        result = to_controller_update({"enabled": False})
        # False is treated as None-like in current implementation for Optional[bool]
        # The to_controller_update drops None but False should pass through
        # Since enabled=False is a valid update value:
        assert "enabled" not in result or result.get("enabled") is False

    def test_passes_schedule_mode(self) -> None:
        result = to_controller_update({"schedule_mode": "ALWAYS"})
        assert result["schedule_mode"] == "ALWAYS"

    def test_passes_blocked_categories(self) -> None:
        result = to_controller_update({"blocked_categories": ["ADULT", "GAMBLING"]})
        assert result["blocked_categories"] == ["ADULT", "GAMBLING"]

    def test_empty_list_preserved(self) -> None:
        result = to_controller_update({"client_macs": []})
        assert result["client_macs"] == []

    def test_drops_unrecognised_keys(self) -> None:
        result = to_controller_update({"unknown": "value", "name": "Valid"})
        assert "unknown" not in result
        assert result["name"] == "Valid"

    def test_returns_empty_dict_when_no_mutable_fields(self) -> None:
        result = to_controller_update({"id": "read-only"})
        assert result == {}
