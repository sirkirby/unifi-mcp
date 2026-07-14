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


# --- alarm_rule_to_legacy_create_body: full POST envelope (issue #2) ----------
#
# The canonical write shape carries only title/enabled/triggers/actions/scope,
# but POST /proxy/protect/api/automations rejects an incomplete body with
# 400 "Failed to parse 'request-body'". Create must scaffold the structural
# fields the controller requires that the canonical shape can't express
# (isCreatedBySystem, historyConditions, schedules, cooldown). Verified against
# Hovborg/unifi-protect-bridge automation_payloads.py and the AlarmManager
# raw-rule fixture. Update does NOT use this — it deep-merges onto the full
# existing rule, so alarm_rule_to_legacy_body stays sparse.


def test_legacy_create_body_scaffolds_full_envelope():
    from unifi_core.protect.models.alarm_rules import alarm_rule_to_legacy_create_body

    body = alarm_rule_to_legacy_create_body(
        {
            "title": "Vehicle Arrival Rule",
            "enabled": True,
            "triggers": [{"data": {"condition": {"type": "is", "source": "smartDetectLine", "value": "Arrival"}}}],
            "actions": [
                {
                    "action_id": "HTTP_REQUEST",
                    "data": {
                        "type": "HTTP_REQUEST",
                        "metadata": {
                            "url": "https://homeassistant.local/api/webhook/x",
                            "method": "POST",
                            "headers": [],
                            "timeout": 30000,
                            "useThumbnail": True,
                        },
                        "order": -1,
                    },
                }
            ],
            "scope": {"sources": [{"device": "AABBCCDDEEFF", "type": "include"}]},
        }
    )

    # Translated write fields come through from the canonical body.
    assert body["name"] == "Vehicle Arrival Rule"
    assert body["enable"] is True
    assert body["sources"] == [{"device": "AABBCCDDEEFF", "type": "include"}]
    assert body["conditions"] == [{"condition": {"type": "is", "source": "smartDetectLine", "value": "Arrival"}}]
    assert body["actions"][0]["type"] == "HTTP_REQUEST"
    # Structural envelope the canonical shape can't express — required by POST.
    assert body["isCreatedBySystem"] is False
    assert body["historyConditions"] == []
    assert body["schedules"] == []
    assert body["cooldown"] == {"enable": False, "timeout": 600000}


def test_legacy_create_body_defaults_when_fields_omitted():
    from unifi_core.protect.models.alarm_rules import alarm_rule_to_legacy_create_body

    body = alarm_rule_to_legacy_create_body({"title": "X", "actions": [{"data": {"type": "webhook"}}]})

    assert body["enable"] is True  # a newly-created rule defaults to enabled
    assert body["sources"] == []
    assert body["conditions"] == []
    assert body["historyConditions"] == []
    assert body["schedules"] == []
    assert body["cooldown"] == {"enable": False, "timeout": 600000}


def test_legacy_create_body_preserves_explicit_disabled():
    from unifi_core.protect.models.alarm_rules import alarm_rule_to_legacy_create_body

    body = alarm_rule_to_legacy_create_body(
        {"title": "X", "enabled": False, "actions": [{"data": {"type": "webhook"}}]}
    )
    assert body["enable"] is False


def test_legacy_create_body_preserves_license_plate_known_value():
    """The license_plate_known condition carries the plate-group id in ``value``;
    the raw API keys off it, so create must pass the whole condition verbatim."""
    from unifi_core.protect.models.alarm_rules import alarm_rule_to_legacy_create_body

    lpr = {"condition": {"type": "is", "source": "license_plate_known", "value": "plate-group-123"}}
    body = alarm_rule_to_legacy_create_body(
        {"title": "LPR Rule", "triggers": [{"data": lpr}], "actions": [{"data": {"type": "webhook"}}]}
    )

    assert body["conditions"] == [lpr]
    assert body["conditions"][0]["condition"]["source"] == "license_plate_known"
    assert body["conditions"][0]["condition"]["value"] == "plate-group-123"


def test_legacy_create_body_does_not_alias_defaults_across_calls():
    """Each call must produce independent mutable defaults — mutating one body's
    schedules/cooldown must not bleed into the next."""
    from unifi_core.protect.models.alarm_rules import alarm_rule_to_legacy_create_body

    first = alarm_rule_to_legacy_create_body({"title": "A", "actions": [{"data": {"type": "webhook"}}]})
    first["schedules"].append("mutated")
    first["cooldown"]["timeout"] = 1

    second = alarm_rule_to_legacy_create_body({"title": "B", "actions": [{"data": {"type": "webhook"}}]})
    assert second["schedules"] == []
    assert second["cooldown"] == {"enable": False, "timeout": 600000}
