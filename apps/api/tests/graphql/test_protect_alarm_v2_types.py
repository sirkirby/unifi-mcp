"""Tests for the Alarm Manager v2 GraphQL types + tool-type registration."""

from __future__ import annotations

from unifi_api.graphql.type_registry_init import build_type_registry
from unifi_api.graphql.types.protect.alarms import (
    AlarmV2ProfileList,
    AlarmV2Rule,
    AlarmV2RuleList,
)


def test_v2_tools_registered_with_expected_types():
    reg = build_type_registry()
    assert reg.lookup_tool("protect_alarm_v2_list_rules") == (AlarmV2RuleList, "detail")
    assert reg.lookup_tool("protect_alarm_v2_get_rule") == (AlarmV2Rule, "detail")
    assert reg.lookup_tool("protect_alarm_v2_list_profiles") == (AlarmV2ProfileList, "detail")


def test_alarm_v2_rule_passthrough_roundtrip():
    raw = {
        "id": "r1",
        "title": "Dog Alarm",
        "triggers": [{"trigger_id": "protect:ai.nls", "data": {"nlsSentence": "x", "nlsThreshold": 50}}],
        "actions": [{"action_id": "protect:notify"}],
        "scope": {"mode": "all", "data": {}},
        "stats": {"executions_24h": 0},
        "created_at": "2026-06-02T20:05:04Z",
        "updated_at": "2026-06-02T20:05:29Z",
    }
    typed = AlarmV2Rule.from_manager_output(raw)
    assert typed.id == "r1"
    assert typed.title == "Dog Alarm"
    assert typed.to_dict() == raw  # byte-identical passthrough


def test_alarm_v2_rule_list_wrapper_and_list_coercion():
    wrapped = AlarmV2RuleList.from_manager_output({"rules": [{"id": "r1"}], "count": 1})
    assert wrapped.count == 1
    assert wrapped.to_dict()["rules"][0]["id"] == "r1"

    coerced = AlarmV2RuleList.from_manager_output([{"id": "r1"}, {"id": "r2"}])
    assert coerced.count == 2
    assert coerced.to_dict()["rules"][1]["id"] == "r2"


def test_alarm_v2_profile_list_wrapper():
    wrapped = AlarmV2ProfileList.from_manager_output({"profiles": [], "count": 0})
    assert wrapped.count == 0
    assert wrapped.to_dict()["profiles"] == []
