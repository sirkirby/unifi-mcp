"""Tests for Alarm Manager v2 read models (normalized /api/v2/alarms/ rules)."""

from unifi_core.protect.models.alarm_rules import (
    MUTABLE_FIELDS,
    AlarmRule,
    alarm_rule_from_controller,
)

# Synthetic raw rule mirroring /api/v2/alarms/protect shape (no real data).
_RAW_RULE = {
    "id": "rule-uuid-1",
    "title": "Dog Alarm",
    "trigger_categories": [
        {
            "id": "protect:ai",
            "title": "AI",
            "triggers": [
                {
                    "id": "protect:ai.nls",
                    "title": "AI Natural Language",
                    "data": {"nlsSentence": "a dog appears", "nlsThreshold": 50},
                }
            ],
        }
    ],
    "action_categories": [
        {
            "id": "protect:notify",
            "title": "Notify",
            "actions": [
                {
                    "id": "protect:notify",
                    "title": "Notify",
                    "data": {"default_channels": ["push"], "is_critical": False},
                }
            ],
        }
    ],
    "scope": {"mode": "all", "data": {}},
    "stats": {"executions_24h": 3},
    "created_at": "2026-06-02T20:05:04Z",
    "updated_at": "2026-06-02T20:05:29Z",
}


def test_normalizes_rule_triggers_actions_and_metadata():
    rule = alarm_rule_from_controller(_RAW_RULE)

    assert isinstance(rule, AlarmRule)
    assert rule.id == "rule-uuid-1"
    assert rule.title == "Dog Alarm"

    assert len(rule.triggers) == 1
    trig = rule.triggers[0]
    assert trig.category_id == "protect:ai"
    assert trig.trigger_id == "protect:ai.nls"
    assert trig.title == "AI Natural Language"
    assert trig.data == {"nlsSentence": "a dog appears", "nlsThreshold": 50}

    assert len(rule.actions) == 1
    act = rule.actions[0]
    assert act.category_id == "protect:notify"
    assert act.action_id == "protect:notify"
    assert act.data == {"default_channels": ["push"], "is_critical": False}

    assert rule.scope == {"mode": "all", "data": {}}
    assert rule.stats == {"executions_24h": 3}
    assert rule.created_at == "2026-06-02T20:05:04Z"
    assert rule.updated_at == "2026-06-02T20:05:29Z"


def test_handles_missing_and_empty_fields():
    rule = alarm_rule_from_controller({"id": "x"})
    assert rule.id == "x"
    assert rule.title is None
    assert rule.triggers == []
    assert rule.actions == []
    assert rule.scope == {}
    assert rule.stats == {}


def test_is_read_only_model():
    assert MUTABLE_FIELDS == frozenset()


_RAW_LEGACY_RULE = {
    "id": "66a5c92a0022f903e4000400",
    "name": "Motion",
    "enable": True,
    "conditions": [{"type": "motion", "source": "camera"}],
    "actions": [{"type": "webhook", "url": "https://x"}],
    "sources": [{"device": "AABBCCDDEEFF", "type": "include"}],
}


def test_alarm_rule_from_legacy_maps_to_canonical():
    from unifi_core.protect.models.alarm_rules import alarm_rule_from_legacy

    rule = alarm_rule_from_legacy(_RAW_LEGACY_RULE)

    assert rule.id == "66a5c92a0022f903e4000400"
    assert rule.title == "Motion"
    assert rule.enabled is True
    assert rule.triggers[0].trigger_id == "motion"
    assert rule.triggers[0].data == {"type": "motion", "source": "camera"}
    assert rule.actions[0].action_id == "webhook"
    assert rule.scope == {"sources": [{"device": "AABBCCDDEEFF", "type": "include"}]}


def test_canonical_rule_enabled_defaults_none_for_v2():
    rule = alarm_rule_from_controller(_RAW_RULE)
    assert rule.enabled is None
