"""Unit tests for the Protect alarm read-only models (status/profile/rule)."""

from __future__ import annotations

from datetime import datetime, timezone

from unifi_core.protect.models.alarms import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    AlarmProfile,
    AlarmProfileList,
    AlarmRule,
    AlarmRuleAction,
    AlarmRuleActionMetadata,
    AlarmRuleCondition,
    AlarmRuleCooldown,
    AlarmRuleList,
    AlarmRuleSource,
    AlarmStatus,
    profile_from_controller,
    profile_list_from_controller,
    rule_from_controller,
    rule_list_from_controller,
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

    def test_read_only_fields_is_union_of_all_models(self) -> None:
        expected = (
            frozenset(AlarmStatus.model_fields.keys())
            | frozenset(AlarmProfile.model_fields.keys())
            | frozenset(AlarmProfileList.model_fields.keys())
            | frozenset(AlarmRule.model_fields.keys())
            | frozenset(AlarmRuleList.model_fields.keys())
            | frozenset(AlarmRuleSource.model_fields.keys())
            | frozenset(AlarmRuleCondition.model_fields.keys())
            | frozenset(AlarmRuleAction.model_fields.keys())
            | frozenset(AlarmRuleActionMetadata.model_fields.keys())
            | frozenset(AlarmRuleCooldown.model_fields.keys())
        )
        assert READ_ONLY_FIELDS == expected

    def test_read_only_fields_contains_alarm_rule_fields(self) -> None:
        for field_name in AlarmRule.model_fields:
            assert field_name in READ_ONLY_FIELDS


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


# ---------------------------------------------------------------------------
# Alarm rule (Alarm Manager automations) model tests
# ---------------------------------------------------------------------------


# Representative fixture matching the Protect ``/proxy/protect/api/automations``
# payload schema. All values are synthetic.
_VEHICLE_ARRIVAL_RULE_FIXTURE = {
    "id": "rule-uuid-1234",
    "name": "Example Vehicle Arrival Rule",
    "enable": True,
    "isCreatedBySystem": False,
    "sources": [
        {"device": "AABBCC001122", "type": "include"},
    ],
    "conditions": [
        {
            "condition": {
                "source": "smartDetectLine",
                "type": "is",
                "value": "Arrival - down",
            }
        },
        {
            "condition": {
                "source": "license_plate_known",
                "type": "is",
                "value": "vehicle_LPR-ABC1234",
            }
        },
    ],
    "historyConditions": [],
    "schedules": [],
    "actions": [
        {
            "type": "HTTP_REQUEST",
            "order": -1,
            "metadata": {
                "url": "https://ha.example.test/api/webhook/test_vehicle_arriving",
                "method": "POST",
                "headers": [],
                "timeout": 30000,
                "useThumbnail": True,
            },
        },
    ],
    "cooldown": {"enable": False, "timeout": 600000},
}


class TestRuleFromController:
    def test_full_vehicle_fixture(self) -> None:
        rule = rule_from_controller(_VEHICLE_ARRIVAL_RULE_FIXTURE)
        assert isinstance(rule, AlarmRule)
        assert rule.id == "rule-uuid-1234"
        assert rule.name == "Example Vehicle Arrival Rule"
        assert rule.enable is True
        assert rule.is_created_by_system is False
        assert rule.history_conditions == []
        assert rule.schedules == []

    def test_sources_parsed_as_list_of_models(self) -> None:
        rule = rule_from_controller(_VEHICLE_ARRIVAL_RULE_FIXTURE)
        assert rule.sources is not None
        assert len(rule.sources) == 1
        assert isinstance(rule.sources[0], AlarmRuleSource)
        assert rule.sources[0].device == "AABBCC001122"
        assert rule.sources[0].type == "include"

    def test_conditions_parsed_as_list_of_wrappers_keeping_inner_opaque(self) -> None:
        rule = rule_from_controller(_VEHICLE_ARRIVAL_RULE_FIXTURE)
        assert rule.conditions is not None
        assert len(rule.conditions) == 2
        first = rule.conditions[0]
        assert isinstance(first, AlarmRuleCondition)
        # Inner condition body stays as a dict — we intentionally don't
        # enumerate every source/type combination.
        assert first.condition == {
            "source": "smartDetectLine",
            "type": "is",
            "value": "Arrival - down",
        }
        assert rule.conditions[1].condition == {
            "source": "license_plate_known",
            "type": "is",
            "value": "vehicle_LPR-ABC1234",
        }

    def test_actions_parsed_with_metadata_kept_opaque(self) -> None:
        rule = rule_from_controller(_VEHICLE_ARRIVAL_RULE_FIXTURE)
        assert rule.actions is not None
        assert len(rule.actions) == 1
        action = rule.actions[0]
        assert isinstance(action, AlarmRuleAction)
        assert action.type == "HTTP_REQUEST"
        assert action.order == -1
        # Metadata is kept as dict on the action; the typed
        # AlarmRuleActionMetadata is exported for callers who want to coerce
        # but we don't force coercion at parse time.
        assert isinstance(action.metadata, dict)
        assert action.metadata["url"] == ("https://ha.example.test/api/webhook/test_vehicle_arriving")
        assert action.metadata["method"] == "POST"
        assert action.metadata["useThumbnail"] is True

    def test_cooldown_parsed(self) -> None:
        rule = rule_from_controller(_VEHICLE_ARRIVAL_RULE_FIXTURE)
        assert isinstance(rule.cooldown, AlarmRuleCooldown)
        assert rule.cooldown.enable is False
        assert rule.cooldown.timeout == 600000

    def test_empty_dict_coalesces_to_none(self) -> None:
        rule = rule_from_controller({})
        assert isinstance(rule, AlarmRule)
        assert rule.id is None
        assert rule.name is None
        assert rule.enable is None
        assert rule.sources is None
        assert rule.conditions is None
        assert rule.actions is None
        assert rule.cooldown is None

    def test_partial_dict_only_id_and_name(self) -> None:
        rule = rule_from_controller({"id": "r-1", "name": "Test"})
        assert rule.id == "r-1"
        assert rule.name == "Test"
        assert rule.enable is None
        assert rule.sources is None
        assert rule.conditions is None

    def test_non_list_sources_coalesces_to_none(self) -> None:
        rule = rule_from_controller({"id": "r-1", "sources": "not a list"})
        assert rule.sources is None

    def test_non_list_conditions_coalesces_to_none(self) -> None:
        rule = rule_from_controller({"id": "r-1", "conditions": {"oops": "dict"}})
        assert rule.conditions is None

    def test_non_dict_cooldown_coalesces_to_none(self) -> None:
        rule = rule_from_controller({"id": "r-1", "cooldown": "off"})
        assert rule.cooldown is None

    def test_condition_with_non_dict_inner_keeps_outer_but_drops_inner(self) -> None:
        raw = {"id": "r-1", "conditions": [{"condition": "not a dict"}]}
        rule = rule_from_controller(raw)
        assert rule.conditions is not None
        assert len(rule.conditions) == 1
        assert rule.conditions[0].condition is None

    def test_unknown_action_type_passthrough(self) -> None:
        """A new/unknown action type should not break parsing."""
        raw = {
            "id": "r-1",
            "actions": [{"type": "FUTURE_ACTION_KIND", "metadata": {"x": 1}}],
        }
        rule = rule_from_controller(raw)
        assert rule.actions is not None
        assert rule.actions[0].type == "FUTURE_ACTION_KIND"
        assert rule.actions[0].metadata == {"x": 1}

    def test_model_dump_excludes_none(self) -> None:
        rule = rule_from_controller({"id": "r-1", "name": "Test", "enable": True})
        dumped = rule.model_dump(exclude_none=True)
        assert dumped["id"] == "r-1"
        assert dumped["name"] == "Test"
        assert dumped["enable"] is True
        assert "sources" not in dumped
        assert "conditions" not in dumped
        assert "actions" not in dumped
        assert "cooldown" not in dumped


class TestRuleListFromController:
    def test_full_wrapper_dict(self) -> None:
        raw = {
            "rules": [
                {"id": "r-1", "name": "Arrival"},
                {"id": "r-2", "name": "Departure"},
            ],
            "count": 2,
        }
        rule_list = rule_list_from_controller(raw)
        assert isinstance(rule_list, AlarmRuleList)
        assert rule_list.count == 2
        assert len(rule_list.rules) == 2

    def test_empty_rules_list(self) -> None:
        rule_list = rule_list_from_controller({"rules": [], "count": 0})
        assert rule_list.rules == []
        assert rule_list.count == 0

    def test_non_list_rules_coalesces_to_none(self) -> None:
        rule_list = rule_list_from_controller({"rules": "oops", "count": 0})
        assert rule_list.rules is None

    def test_none_rules_coalesces_to_none(self) -> None:
        rule_list = rule_list_from_controller({"rules": None, "count": 0})
        assert rule_list.rules is None

    def test_dict_rules_coalesces_to_none(self) -> None:
        rule_list = rule_list_from_controller({"rules": {"x": 1}, "count": 1})
        assert rule_list.rules is None

    def test_empty_dict(self) -> None:
        rule_list = rule_list_from_controller({})
        assert isinstance(rule_list, AlarmRuleList)
        assert rule_list.rules is None
        assert rule_list.count is None

    def test_model_dump_excludes_none(self) -> None:
        rule_list = rule_list_from_controller({"rules": [{"id": "r-1"}], "count": 1})
        dumped = rule_list.model_dump(exclude_none=True)
        assert "rules" in dumped
        assert "count" in dumped


# ----------------------------------------------------------------------------
# rule_to_controller: snake_case → camelCase normalization for POST/PATCH body
# ----------------------------------------------------------------------------
#
# Background: the read tools (list_rules / get_rule) normalize controller
# payloads to snake_case via ``rule_from_controller``. The Protect controller's
# POST /automations endpoint is strict camelCase, so a naive read → mutate →
# create round-trip fails with 400 "Failed to parse request-body" on the
# ``is_created_by_system`` / ``history_conditions`` fields. ``rule_to_controller``
# is the inverse: it translates the handful of fields that differ in case
# back to camelCase so the round-trip works, leaving everything else untouched.


class TestRuleToController:
    def test_translates_top_level_snake_to_camel(self) -> None:
        from unifi_core.protect.models.alarms import rule_to_controller

        body = {
            "name": "R1",
            "enable": True,
            "is_created_by_system": False,
            "history_conditions": [],
            "schedules": [],
        }
        out = rule_to_controller(body)
        assert "is_created_by_system" not in out
        assert "history_conditions" not in out
        assert out["isCreatedBySystem"] is False
        assert out["historyConditions"] == []
        # Passthrough fields are untouched
        assert out["name"] == "R1"
        assert out["enable"] is True
        assert out["schedules"] == []

    def test_translates_nested_action_metadata_use_thumbnail(self) -> None:
        from unifi_core.protect.models.alarms import rule_to_controller

        body = {
            "actions": [
                {
                    "type": "HTTP_REQUEST",
                    "order": -1,
                    "metadata": {
                        "url": "https://example.test/wh",
                        "method": "POST",
                        "use_thumbnail": True,
                    },
                }
            ],
        }
        out = rule_to_controller(body)
        meta = out["actions"][0]["metadata"]
        assert "use_thumbnail" not in meta
        assert meta["useThumbnail"] is True
        # Other metadata fields preserved
        assert meta["url"] == "https://example.test/wh"
        assert meta["method"] == "POST"

    def test_camelcase_input_passthrough_unchanged(self) -> None:
        from unifi_core.protect.models.alarms import rule_to_controller

        body = {
            "name": "R2",
            "isCreatedBySystem": True,
            "historyConditions": ["something"],
            "actions": [{"type": "HTTP_REQUEST", "metadata": {"useThumbnail": False}}],
        }
        out = rule_to_controller(body)
        assert out["isCreatedBySystem"] is True
        assert out["historyConditions"] == ["something"]
        assert out["actions"][0]["metadata"]["useThumbnail"] is False
        # No accidental snake_case sibling fields
        assert "is_created_by_system" not in out
        assert "history_conditions" not in out
        assert "use_thumbnail" not in out["actions"][0]["metadata"]

    def test_both_snake_and_camel_prefers_camel(self) -> None:
        """If the caller (perversely) provides both forms, the explicit
        camelCase value wins so we never accidentally clobber an
        intentional value with a stale snake_case sibling."""
        from unifi_core.protect.models.alarms import rule_to_controller

        body = {
            "is_created_by_system": True,
            "isCreatedBySystem": False,
        }
        out = rule_to_controller(body)
        assert out["isCreatedBySystem"] is False
        assert "is_created_by_system" not in out

    def test_nested_both_snake_and_camel_prefers_camel(self) -> None:
        """Nested action metadata must mirror the top-level two-pass rule:
        an explicit camelCase value wins over its snake_case sibling
        regardless of dict insertion order (a single-pass comprehension
        would clobber by order)."""
        from unifi_core.protect.models.alarms import rule_to_controller

        # snake first, then camel
        body = {"actions": [{"metadata": {"use_thumbnail": True, "useThumbnail": False}}]}
        meta = rule_to_controller(body)["actions"][0]["metadata"]
        assert meta["useThumbnail"] is False
        assert "use_thumbnail" not in meta

        # camel first, then snake — must still resolve to camel
        body = {"actions": [{"metadata": {"useThumbnail": False, "use_thumbnail": True}}]}
        meta = rule_to_controller(body)["actions"][0]["metadata"]
        assert meta["useThumbnail"] is False
        assert "use_thumbnail" not in meta

    def test_nested_snake_only_translated(self) -> None:
        """A lone snake_case metadata key is translated to camelCase."""
        from unifi_core.protect.models.alarms import rule_to_controller

        body = {"actions": [{"metadata": {"use_thumbnail": True}}]}
        meta = rule_to_controller(body)["actions"][0]["metadata"]
        assert meta["useThumbnail"] is True
        assert "use_thumbnail" not in meta

    def test_unknown_fields_passthrough(self) -> None:
        """Future Protect fields we don't enumerate must round-trip untouched."""
        from unifi_core.protect.models.alarms import rule_to_controller

        body = {"future_field": "x", "futureCamelField": "y"}
        out = rule_to_controller(body)
        assert out["future_field"] == "x"
        assert out["futureCamelField"] == "y"

    def test_empty_dict_returns_empty_dict(self) -> None:
        from unifi_core.protect.models.alarms import rule_to_controller

        assert rule_to_controller({}) == {}

    def test_non_dict_input_passthrough(self) -> None:
        """Defensive: non-dict input is returned as-is so callers see
        a clear downstream error instead of an opaque AttributeError."""
        from unifi_core.protect.models.alarms import rule_to_controller

        assert rule_to_controller("not a dict") == "not a dict"  # type: ignore[arg-type]
        assert rule_to_controller(None) is None  # type: ignore[arg-type]

    def test_action_with_non_dict_metadata_unchanged(self) -> None:
        from unifi_core.protect.models.alarms import rule_to_controller

        body = {"actions": [{"type": "SEND_NOTIFICATION", "metadata": None}]}
        out = rule_to_controller(body)
        assert out["actions"][0]["metadata"] is None

    def test_actions_non_list_passthrough(self) -> None:
        from unifi_core.protect.models.alarms import rule_to_controller

        body = {"actions": "not-a-list"}
        out = rule_to_controller(body)
        assert out["actions"] == "not-a-list"  # let downstream validation catch it

    def test_round_trip_from_controller_to_controller(self) -> None:
        """The canonical fix path: read via from_controller (snake_case),
        mutate, send via to_controller (camelCase). Must yield a body the
        live Protect POST endpoint accepts."""
        from unifi_core.protect.models.alarms import rule_from_controller, rule_to_controller

        # Simulate what list_rules / get_rule returns (snake_case-normalized)
        as_read = rule_from_controller(
            {
                "id": "r-1",
                "name": "Existing",
                "enable": True,
                "isCreatedBySystem": False,
                "sources": [{"device": "AABBCCDDEEFF", "type": "include"}],
                "conditions": [{"condition": {"source": "vehicle", "type": "is"}}],
                "historyConditions": [],
                "schedules": [],
                "actions": [
                    {
                        "type": "HTTP_REQUEST",
                        "order": -1,
                        "metadata": {
                            "url": "https://example.test/wh",
                            "method": "POST",
                            "useThumbnail": True,
                        },
                    }
                ],
                "cooldown": {"enable": False, "timeout": 600000},
            }
        ).model_dump(exclude_none=True)

        # Caller mutates a couple of fields (e.g. clone-and-rename)
        as_read["name"] = "Clone"
        as_read.pop("id", None)

        # Translate for POST
        for_post = rule_to_controller(as_read)
        assert "is_created_by_system" not in for_post
        assert "history_conditions" not in for_post
        assert for_post["isCreatedBySystem"] is False
        assert for_post["historyConditions"] == []
        assert for_post["actions"][0]["metadata"]["useThumbnail"] is True
        assert "use_thumbnail" not in for_post["actions"][0]["metadata"]
