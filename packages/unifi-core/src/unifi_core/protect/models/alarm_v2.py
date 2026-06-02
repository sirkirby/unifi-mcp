"""Read models for UniFi OS Alarm Manager v2 (``/api/v2/alarms/``).

Normalized, read-only view of the v2 alarm-rule surface. This is the modern
UniFi-OS Alarm Manager (cross-app), distinct from the legacy Protect automations
model in :mod:`unifi_core.protect.models.alarms`. The v2 service exposes
AI-powered alarms (e.g. AI Natural Language triggers) not present on the legacy
surface, and requires a SuperAdmin credential to reach (see ``AlarmV2Manager``).

Read-only: no create/update/delete here, so ``MUTABLE_FIELDS = frozenset()``.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class AlarmTriggerV2(BaseModel):
    """A configured trigger within an alarm rule (category + trigger + params)."""

    category_id: Optional[str] = Field(
        default=None, description="Trigger category id (e.g. protect:ai)", json_schema_extra={"mutable": False}
    )
    category_title: Optional[str] = Field(
        default=None, description="Trigger category title", json_schema_extra={"mutable": False}
    )
    trigger_id: Optional[str] = Field(
        default=None, description="Trigger id (e.g. protect:ai.nls)", json_schema_extra={"mutable": False}
    )
    title: Optional[str] = Field(default=None, description="Trigger title", json_schema_extra={"mutable": False})
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Configured trigger parameters (e.g. nlsSentence, nlsThreshold)",
        json_schema_extra={"mutable": False},
    )


class AlarmActionV2(BaseModel):
    """A configured action within an alarm rule (category + action + params)."""

    category_id: Optional[str] = Field(
        default=None, description="Action category id (e.g. protect:notify)", json_schema_extra={"mutable": False}
    )
    category_title: Optional[str] = Field(
        default=None, description="Action category title", json_schema_extra={"mutable": False}
    )
    action_id: Optional[str] = Field(
        default=None, description="Action id (e.g. protect:notify)", json_schema_extra={"mutable": False}
    )
    title: Optional[str] = Field(default=None, description="Action title", json_schema_extra={"mutable": False})
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Configured action parameters (e.g. default_channels, receivers)",
        json_schema_extra={"mutable": False},
    )


class AlarmRuleV2(BaseModel):
    """A normalized UniFi OS Alarm Manager v2 rule."""

    id: Optional[str] = Field(default=None, description="Rule id (UUID)", json_schema_extra={"mutable": False})
    title: Optional[str] = Field(default=None, description="Rule title", json_schema_extra={"mutable": False})
    triggers: list[AlarmTriggerV2] = Field(
        default_factory=list, description="Configured triggers", json_schema_extra={"mutable": False}
    )
    actions: list[AlarmActionV2] = Field(
        default_factory=list, description="Configured actions", json_schema_extra={"mutable": False}
    )
    scope: dict[str, Any] = Field(
        default_factory=dict,
        description="Device/camera scope ({mode, data}) the rule applies to",
        json_schema_extra={"mutable": False},
    )
    stats: dict[str, Any] = Field(
        default_factory=dict, description="Rule stats (e.g. executions_24h)", json_schema_extra={"mutable": False}
    )
    created_at: Optional[str] = Field(
        default=None, description="Creation timestamp (ISO 8601)", json_schema_extra={"mutable": False}
    )
    updated_at: Optional[str] = Field(
        default=None, description="Last update timestamp (ISO 8601)", json_schema_extra={"mutable": False}
    )


def _normalize_triggers(raw: Any) -> list[AlarmTriggerV2]:
    out: list[AlarmTriggerV2] = []
    for category in _get(raw, "trigger_categories", []) or []:
        cat_id = _get(category, "id")
        cat_title = _get(category, "title")
        for trigger in _get(category, "triggers", []) or []:
            out.append(
                AlarmTriggerV2(
                    category_id=cat_id,
                    category_title=cat_title,
                    trigger_id=_get(trigger, "id"),
                    title=_get(trigger, "title"),
                    data=_get(trigger, "data", {}) or {},
                )
            )
    return out


def _normalize_actions(raw: Any) -> list[AlarmActionV2]:
    out: list[AlarmActionV2] = []
    for category in _get(raw, "action_categories", []) or []:
        cat_id = _get(category, "id")
        cat_title = _get(category, "title")
        for action in _get(category, "actions", []) or []:
            out.append(
                AlarmActionV2(
                    category_id=cat_id,
                    category_title=cat_title,
                    action_id=_get(action, "id"),
                    title=_get(action, "title"),
                    data=_get(action, "data", {}) or {},
                )
            )
    return out


def alarm_rule_v2_from_controller(raw: Any) -> AlarmRuleV2:
    """Normalize a raw ``/api/v2/alarms/protect`` rule into an AlarmRuleV2."""
    return AlarmRuleV2(
        id=_get(raw, "id"),
        title=_get(raw, "title"),
        triggers=_normalize_triggers(raw),
        actions=_normalize_actions(raw),
        scope=_get(raw, "scope", {}) or {},
        stats=_get(raw, "stats", {}) or {},
        created_at=_get(raw, "created_at"),
        updated_at=_get(raw, "updated_at"),
    )


ALARM_V2_MUTABLE_FIELDS: frozenset[str] = frozenset()
ALARM_V2_READ_ONLY_FIELDS: frozenset[str] = frozenset(AlarmRuleV2.model_fields.keys())
# Alias required by the model-symmetry test harness — read-only model pattern.
MUTABLE_FIELDS = ALARM_V2_MUTABLE_FIELDS
