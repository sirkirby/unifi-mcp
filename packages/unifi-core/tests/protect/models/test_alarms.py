"""Unit tests for the Protect AlarmStatus, AlarmProfile, and AlarmProfileList read-only models."""

from __future__ import annotations

from datetime import datetime, timezone

from unifi_core.protect.models.alarms import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    AlarmProfile,
    AlarmProfileList,
    AlarmStatus,
    profile_from_controller,
    profile_list_from_controller,
    status_from_controller,
)


class TestAlarmModelFields:
    def test_mutable_fields_empty(self) -> None:
        assert MUTABLE_FIELDS == frozenset()

    def test_read_only_fields_contains_all_alarm_status_fields(self) -> None:
        for field_name in AlarmStatus.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_contains_all_alarm_profile_fields(self) -> None:
        for field_name in AlarmProfile.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_contains_all_alarm_profile_list_fields(self) -> None:
        for field_name in AlarmProfileList.model_fields:
            assert field_name in READ_ONLY_FIELDS

    def test_read_only_fields_is_union_of_all_three_models(self) -> None:
        expected = (
            frozenset(AlarmStatus.model_fields.keys())
            | frozenset(AlarmProfile.model_fields.keys())
            | frozenset(AlarmProfileList.model_fields.keys())
        )
        assert READ_ONLY_FIELDS == expected


class TestStatusFromController:
    def test_full_dict(self) -> None:
        raw = {
            "armed": True,
            "status": "armed",
            "active_profile_id": "profile-001",
            "active_profile_name": "Home",
            "armed_at": "2026-05-13T08:00:00+00:00",
            "will_be_armed_at": None,
            "breach_detected_at": None,
            "breach_event_count": 0,
            "profile_count": 3,
        }
        status = status_from_controller(raw)
        assert isinstance(status, AlarmStatus)
        assert status.armed is True
        assert status.status == "armed"
        assert status.active_profile_id == "profile-001"
        assert status.active_profile_name == "Home"
        assert status.armed_at == "2026-05-13T08:00:00+00:00"
        assert status.will_be_armed_at is None
        assert status.breach_detected_at is None
        assert status.breach_event_count == 0
        assert status.profile_count == 3

    def test_partial_dict(self) -> None:
        raw = {"armed": False, "status": "disarmed"}
        status = status_from_controller(raw)
        assert status.armed is False
        assert status.status == "disarmed"
        assert status.active_profile_id is None
        assert status.active_profile_name is None
        assert status.armed_at is None
        assert status.will_be_armed_at is None
        assert status.breach_detected_at is None
        assert status.breach_event_count is None
        assert status.profile_count is None

    def test_empty_dict(self) -> None:
        status = status_from_controller({})
        assert isinstance(status, AlarmStatus)
        assert status.armed is None
        assert status.status is None

    def test_datetime_armed_at_stringified(self) -> None:
        dt = datetime(2026, 5, 13, 8, 0, 0, tzinfo=timezone.utc)
        status = status_from_controller({"armed": True, "armed_at": dt})
        assert status.armed_at == dt.isoformat()

    def test_datetime_will_be_armed_at_stringified(self) -> None:
        dt = datetime(2026, 5, 13, 8, 0, 30, tzinfo=timezone.utc)
        status = status_from_controller({"will_be_armed_at": dt})
        assert status.will_be_armed_at == dt.isoformat()

    def test_datetime_breach_detected_at_stringified(self) -> None:
        dt = datetime(2026, 5, 13, 9, 15, 0, tzinfo=timezone.utc)
        status = status_from_controller({"breach_detected_at": dt})
        assert status.breach_detected_at == dt.isoformat()

    def test_string_datetime_passthrough(self) -> None:
        raw = {"armed_at": "2026-05-13T08:00:00+00:00"}
        status = status_from_controller(raw)
        assert status.armed_at == "2026-05-13T08:00:00+00:00"

    def test_model_dump_excludes_none(self) -> None:
        raw = {"armed": True, "status": "armed", "profile_count": 2}
        status = status_from_controller(raw)
        dumped = status.model_dump(exclude_none=True)
        assert "armed" in dumped
        assert "status" in dumped
        assert "profile_count" in dumped
        assert "active_profile_id" not in dumped
        assert "armed_at" not in dumped

    def test_breach_with_full_info(self) -> None:
        dt = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        raw = {
            "armed": True,
            "status": "breach",
            "breach_detected_at": dt,
            "breach_event_count": 5,
        }
        status = status_from_controller(raw)
        assert status.armed is True
        assert status.status == "breach"
        assert status.breach_detected_at == dt.isoformat()
        assert status.breach_event_count == 5


class TestProfileFromController:
    def test_full_dict(self) -> None:
        raw = {
            "id": "profile-001",
            "name": "Home",
            "record_everything": True,
            "activation_delay_ms": 30000,
            "schedule_count": 2,
            "automation_count": 1,
        }
        profile = profile_from_controller(raw)
        assert isinstance(profile, AlarmProfile)
        assert profile.id == "profile-001"
        assert profile.name == "Home"
        assert profile.record_everything is True
        assert profile.activation_delay_ms == 30000
        assert profile.schedule_count == 2
        assert profile.automation_count == 1

    def test_partial_dict(self) -> None:
        raw = {"id": "profile-002", "name": "Away"}
        profile = profile_from_controller(raw)
        assert profile.id == "profile-002"
        assert profile.name == "Away"
        assert profile.record_everything is None
        assert profile.activation_delay_ms is None
        assert profile.schedule_count is None
        assert profile.automation_count is None

    def test_empty_dict(self) -> None:
        profile = profile_from_controller({})
        assert isinstance(profile, AlarmProfile)
        assert profile.id is None
        assert profile.name is None

    def test_model_dump_excludes_none(self) -> None:
        raw = {"id": "profile-003", "name": "Night", "schedule_count": 0}
        profile = profile_from_controller(raw)
        dumped = profile.model_dump(exclude_none=True)
        assert "id" in dumped
        assert "name" in dumped
        assert "schedule_count" in dumped
        assert "record_everything" not in dumped
        assert "activation_delay_ms" not in dumped


class TestProfileListFromController:
    def test_full_wrapper_dict(self) -> None:
        raw = {
            "profiles": [
                {"id": "profile-001", "name": "Home"},
                {"id": "profile-002", "name": "Away"},
            ],
            "count": 2,
        }
        profile_list = profile_list_from_controller(raw)
        assert isinstance(profile_list, AlarmProfileList)
        assert len(profile_list.profiles) == 2
        assert profile_list.count == 2

    def test_empty_profiles_list(self) -> None:
        raw = {"profiles": [], "count": 0}
        profile_list = profile_list_from_controller(raw)
        assert profile_list.profiles == []
        assert profile_list.count == 0

    def test_list_passthrough(self) -> None:
        """A bare list (not wrapped dict) should be passed through as profiles."""
        raw = {"profiles": [{"id": "p-001"}, {"id": "p-002"}, {"id": "p-003"}], "count": 3}
        profile_list = profile_list_from_controller(raw)
        assert isinstance(profile_list.profiles, list)
        assert len(profile_list.profiles) == 3

    def test_non_list_profiles_coalesces_to_none(self) -> None:
        """Non-list value for profiles should coalesce to None."""
        raw = {"profiles": "unexpected_string", "count": 0}
        profile_list = profile_list_from_controller(raw)
        assert profile_list.profiles is None

    def test_none_profiles_coalesces_to_none(self) -> None:
        raw = {"profiles": None, "count": 0}
        profile_list = profile_list_from_controller(raw)
        assert profile_list.profiles is None

    def test_dict_profiles_coalesces_to_none(self) -> None:
        """A dict value for profiles (not a list) should coalesce to None."""
        raw = {"profiles": {"unexpected": "dict"}, "count": 1}
        profile_list = profile_list_from_controller(raw)
        assert profile_list.profiles is None

    def test_empty_dict(self) -> None:
        profile_list = profile_list_from_controller({})
        assert isinstance(profile_list, AlarmProfileList)
        assert profile_list.profiles is None
        assert profile_list.count is None

    def test_model_dump_excludes_none(self) -> None:
        raw = {"profiles": [{"id": "p-001"}], "count": 1}
        profile_list = profile_list_from_controller(raw)
        dumped = profile_list.model_dump(exclude_none=True)
        assert "profiles" in dumped
        assert "count" in dumped

    def test_model_dump_with_none_profiles_excludes_profiles(self) -> None:
        raw = {"count": 0}
        profile_list = profile_list_from_controller(raw)
        dumped = profile_list.model_dump(exclude_none=True)
        assert "profiles" not in dumped
        assert "count" in dumped
