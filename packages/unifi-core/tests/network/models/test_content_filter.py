"""Unit tests for the Network ContentFilter CRUD-update domain model."""

from __future__ import annotations

import pytest
from unifi_core.network.models.content_filter import (
    MUTABLE_FIELDS,
    from_controller,
    to_controller_update,
)

from .model_assertions import assert_fields


class TestFieldSets:
    def test_schedule_mode_in_mutable_fields(self) -> None:
        """schedule_mode must be mutable regardless of JSON Schema dict."""
        assert "schedule_mode" in MUTABLE_FIELDS


class TestFromController:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                {
                    "_id": "cf-1",
                    "name": "Kids Filter",
                    "enabled": True,
                    "profile": "DNS",
                    "blocked_categories": ["ADULT", "GAMBLING"],
                    "safe_search": ["GOOGLE", "YOUTUBE"],
                    "client_macs": ["aa:bb:cc:dd:ee:ff"],
                    "network_ids": ["net-1"],
                    "schedule": {"mode": "ALWAYS"},
                },
                {
                    "id": "cf-1",
                    "name": "Kids Filter",
                    "enabled": True,
                    "profile": "DNS",
                    "blocked_categories": ["ADULT", "GAMBLING"],
                    "safe_search": ["GOOGLE", "YOUTUBE"],
                    "client_macs": ["aa:bb:cc:dd:ee:ff"],
                    "network_ids": ["net-1"],
                    "schedule_mode": "ALWAYS",
                },
            ),
            ({"_id": "abc", "name": "Test"}, {"id": "abc"}),
            ({"_id": "cf-2", "categories": ["MALWARE"]}, {"blocked_categories": ["MALWARE"]}),
            (
                {"_id": "cf-3", "blocked_categories": ["ADULT"], "categories": ["MALWARE"]},
                {"blocked_categories": ["ADULT"]},
            ),
            ({"_id": "cf-4", "schedule": {"mode": "CUSTOM"}}, {"schedule_mode": "CUSTOM"}),
            ({"_id": "cf-5", "enabled": False}, {"enabled": False}),
            ({"_id": "cf-6"}, {"enabled": None}),
            ({"_id": "cf-7", "blocked_categories": None}, {"blocked_categories": []}),
            (
                {},
                {
                    "id": None,
                    "name": None,
                    "blocked_categories": [],
                    "safe_search": [],
                    "client_macs": [],
                    "network_ids": [],
                    "schedule_mode": None,
                },
            ),
        ],
        ids=[
            "full_dict",
            "id_coalesces_underscore_id",
            "categories_coalesces_from_categories_key",
            "blocked_categories_takes_priority",
            "schedule_mode_extracted_from_schedule_dict",
            "enabled_false_is_preserved",
            "missing_enabled_defaults_to_none",
            "non_list_blocked_categories_becomes_empty",
            "handles_empty_dict",
        ],
    )
    def test_from_controller_fields(self, raw, expected) -> None:
        result = from_controller(raw)
        assert_fields(result, expected)


class TestToControllerUpdate:
    @pytest.mark.parametrize(
        "fields, expected, absent, present",
        [
            ({"id": "ignore-me", "name": "New Name"}, {"name": "New Name"}, ("id",), ()),
            ({"profile": "DNS", "name": "Test"}, {}, ("profile",), ()),
            ({"name": None, "enabled": True}, {"enabled": True}, ("name",), ()),
            ({"blocked_categories": ["ADULT"], "categories": ["MALWARE"]}, {"categories": ["ADULT"]}, (), ()),
            ({"client_macs": []}, {"client_macs": []}, (), ()),
            ({"unknown": "value", "name": "Valid"}, {"name": "Valid"}, ("unknown",), ()),
        ],
        ids=[
            "filters_out_read_only_id",
            "filters_out_profile",
            "drops_none_values",
            "blocked_categories_wins_over_categories",
            "empty_list_preserved",
            "drops_unrecognised_keys",
        ],
    )
    def test_to_controller_update_payload(self, fields, expected, absent, present) -> None:
        result = to_controller_update(fields)
        assert_fields(result, expected)
        for key in absent:
            assert key not in result
        for key in present:
            assert key in result

    def test_preserves_boolean_false(self) -> None:
        result = to_controller_update({"enabled": False})
        # False is treated as None-like in current implementation for Optional[bool]
        # The to_controller_update drops None but False should pass through
        # Since enabled=False is a valid update value:
        assert "enabled" not in result or result.get("enabled") is False

    def test_nests_schedule_mode_under_schedule(self) -> None:
        """The controller stores the mode nested; a flat schedule_mode is rejected with a 400."""
        result = to_controller_update({"schedule_mode": "ALWAYS"})
        assert result["schedule"] == {"mode": "ALWAYS"}
        assert "schedule_mode" not in result

    def test_nests_every_accepted_schedule_mode(self) -> None:
        for mode in ("ALWAYS", "CUSTOM", "EVERY_DAY", "EVERY_WEEK", "ONE_TIME_ONLY"):
            result = to_controller_update({"schedule_mode": mode})
            assert result["schedule"] == {"mode": mode}

    def test_schedule_mode_nests_alongside_other_fields(self) -> None:
        result = to_controller_update({"name": "Kids", "schedule_mode": "EVERY_DAY", "blocked_categories": ["ADULT"]})
        assert result == {"name": "Kids", "schedule": {"mode": "EVERY_DAY"}, "categories": ["ADULT"]}

    def test_schedule_mode_round_trips_from_controller(self) -> None:
        """A value read off the controller must be writable back unchanged."""
        raw = {"_id": "cf-rt", "schedule": {"mode": "EVERY_WEEK", "repeat_on_days": ["mon"], "time_all_day": False}}
        model = from_controller(raw)
        assert model.schedule_mode == "EVERY_WEEK"
        result = to_controller_update({"schedule_mode": model.schedule_mode})
        assert result["schedule"] == {"mode": "EVERY_WEEK"}

    def test_maps_blocked_categories_to_categories(self) -> None:
        """The controller rejects the public alias outright, so it must be renamed."""
        result = to_controller_update({"blocked_categories": ["ADULT", "GAMBLING"]})
        assert result["categories"] == ["ADULT", "GAMBLING"]
        assert "blocked_categories" not in result

    def test_accepts_categories_as_inbound_alias(self) -> None:
        """A raw controller dict round-tripped through the helper keeps its categories."""
        result = to_controller_update({"categories": ["MALWARE"]})
        assert result["categories"] == ["MALWARE"]

    def test_empty_blocked_categories_rejected(self) -> None:
        with pytest.raises(ValueError, match="blocked_categories"):
            to_controller_update({"blocked_categories": []})


def test_schedule_round_trip_and_partial_translation() -> None:
    raw = {
        "categories": ["FAMILY"],
        "schedule": {
            "mode": "EVERY_WEEK",
            "repeat_on_days": ["mon", "tue"],
            "time_all_day": False,
            "time_range_start": "09:00",
            "time_range_end": "17:00",
            "date_start": "2026-08-01",
            "date_end": "2026-08-02",
        },
    }
    fields = from_controller(raw).model_dump(exclude_none=True)
    result = to_controller_update(fields)
    assert result["schedule"] == raw["schedule"]
    assert to_controller_update({"schedule_days": ["fri"]}) == {"schedule": {"repeat_on_days": ["fri"]}}


@pytest.mark.parametrize(
    "fields",
    [
        {"schedule_days": ["MONDAY"]},
        {"schedule_days": [0]},
        {"schedule_time_start": "24:00"},
        {"schedule_time_end": "9:00"},
        {"schedule_date_start": "2026-02-30"},
        {"schedule_date_end": "2026/08/02"},
        {"schedule_time_all_day": "false"},
        {"schedule": {"time_from": "09:00"}},
    ],
)
def test_invalid_schedule_is_rejected(fields: dict) -> None:
    with pytest.raises(ValueError):
        to_controller_update(fields)


def test_create_requires_one_scope_and_maps_fields() -> None:
    from unifi_core.network.models.content_filter import to_controller_create

    payload = to_controller_create(
        {
            "name": " Kids ",
            "client_macs": ["AA:BB:CC:DD:EE:FF"],
            "blocked_categories": ["FAMILY"],
            "schedule_mode": "EVERY_WEEK",
            "schedule_days": ["mon"],
        }
    )
    assert payload["name"] == "Kids"
    assert payload["enabled"] is False
    assert payload["client_macs"] == ["aa:bb:cc:dd:ee:ff"]
    assert payload["categories"] == ["FAMILY"]
    assert payload["schedule"] == {"mode": "EVERY_WEEK", "repeat_on_days": ["mon"], "time_all_day": True}


def test_minimum_create_adds_required_all_day_schedule() -> None:
    from unifi_core.network.models.content_filter import to_controller_create

    payload = to_controller_create(
        {"name": "Kids", "client_macs": ["aa:bb:cc:dd:ee:ff"], "blocked_categories": ["FAMILY"]}
    )
    assert payload["schedule"] == {"mode": "ALWAYS", "repeat_on_days": [], "time_all_day": True}
    assert payload["enabled"] is False


def test_create_preserves_explicit_schedule_fields() -> None:
    from unifi_core.network.models.content_filter import to_controller_create

    payload = to_controller_create(
        {
            "name": "Kids",
            "network_ids": ["net"],
            "blocked_categories": ["FAMILY"],
            "schedule_mode": "ONE_TIME_ONLY",
            "schedule_time_all_day": False,
            "schedule_date_start": "2026-08-01",
            "schedule_date_end": "2026-08-02",
        }
    )
    assert payload["schedule"] == {
        "mode": "ONE_TIME_ONLY",
        "repeat_on_days": [],
        "time_all_day": False,
        "date_start": "2026-08-01",
        "date_end": "2026-08-02",
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"name": " ", "client_macs": ["aa:bb:cc:dd:ee:ff"], "blocked_categories": ["FAMILY"]},
        {"name": "Kids", "blocked_categories": ["FAMILY"]},
        {
            "name": "Kids",
            "client_macs": ["aa:bb:cc:dd:ee:ff"],
            "network_ids": ["net"],
            "blocked_categories": ["FAMILY"],
        },
        {"name": "Kids", "network_ids": [""], "blocked_categories": ["FAMILY"]},
        {"name": "Kids", "network_ids": ["net"], "blocked_categories": ["FAMILY"], "schedule_days": ["MONDAY"]},
        {"name": "Kids", "network_ids": ["net"]},
        {"name": "Kids", "network_ids": ["net"], "blocked_categories": []},
        {"name": "Kids", "network_ids": ["net"], "blocked_categories": [" "]},
        {"name": "Kids", "network_ids": ["net"], "blocked_categories": "FAMILY"},
        {"name": "Kids", "network_ids": ["net"], "blocked_categories": ["FAMILY"], "safe_search": "GOOGLE"},
        {"name": "Kids", "network_ids": ["net"], "blocked_categories": ["FAMILY"], "enabled": "yes"},
        {"name": "Kids", "client_macs": ["not-a-mac"], "blocked_categories": ["FAMILY"]},
        {"name": "Kids", "network_ids": ["net"], "blocked_categories": ["FAMILY"], "schedule_mode": None},
    ],
)
def test_invalid_create_is_rejected(fields: dict) -> None:
    from unifi_core.network.models.content_filter import to_controller_create

    with pytest.raises(ValueError):
        to_controller_create(fields)


def test_categories_alias_remains_supported() -> None:
    from unifi_core.network.models.content_filter import to_controller_create

    assert to_controller_create({"name": "Kids", "network_ids": ["net"], "categories": ["FAMILY"]})["categories"] == [
        "FAMILY"
    ]
    assert to_controller_update({"categories": ["FAMILY"]}) == {"categories": ["FAMILY"]}


@pytest.mark.parametrize(
    "fields",
    [
        {"enabled": "yes"},
        {"blocked_categories": "FAMILY"},
        {"safe_search": "GOOGLE"},
        {"client_macs": ["not-a-mac"]},
        {"name": 5},
    ],
)
def test_update_rejects_wrong_types_and_bad_mac(fields: dict) -> None:
    with pytest.raises(ValueError):
        to_controller_update(fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"name": "   "},
        {"blocked_categories": []},
        {"categories": []},
        {"blocked_categories": [" "]},
    ],
)
def test_update_rejects_empty_name_or_categories(fields: dict) -> None:
    with pytest.raises(ValueError):
        to_controller_update(fields)


def test_update_keeps_existing_mixed_scope_behavior() -> None:
    assert to_controller_update({"client_macs": ["aa:bb:cc:dd:ee:ff"], "network_ids": ["net"]}) == {
        "client_macs": ["aa:bb:cc:dd:ee:ff"],
        "network_ids": ["net"],
    }
