"""Read models for UniFi OS Alarm Manager (``/api/v2/alarms/``).

Normalized, read-only view of the alarm-rule surface. This is the modern
UniFi-OS Alarm Manager (cross-app), distinct from the legacy Protect automations
model in :mod:`unifi_core.protect.models.alarms`. The Alarm Manager service exposes
AI-powered alarms (e.g. AI Natural Language triggers) not present on the legacy
surface, and requires a SuperAdmin credential to reach (see ``AlarmManagerService``).

Read-only: no create/update/delete here, so ``MUTABLE_FIELDS = frozenset()``.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class AlarmTrigger(BaseModel):
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


class AlarmAction(BaseModel):
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


class AlarmRule(BaseModel):
    """A normalized UniFi OS Alarm Manager rule."""

    id: Optional[str] = Field(default=None, description="Rule id", json_schema_extra={"mutable": False})
    title: Optional[str] = Field(default=None, description="Rule title", json_schema_extra={"mutable": False})
    enabled: Optional[bool] = Field(
        default=None, description="Whether the rule is enabled", json_schema_extra={"mutable": False}
    )
    triggers: list[AlarmTrigger] = Field(
        default_factory=list, description="Configured triggers", json_schema_extra={"mutable": False}
    )
    actions: list[AlarmAction] = Field(
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


def _normalize_triggers(raw: Any) -> list[AlarmTrigger]:
    out: list[AlarmTrigger] = []
    for category in _get(raw, "trigger_categories", []) or []:
        cat_id = _get(category, "id")
        cat_title = _get(category, "title")
        for trigger in _get(category, "triggers", []) or []:
            out.append(
                AlarmTrigger(
                    category_id=cat_id,
                    category_title=cat_title,
                    trigger_id=_get(trigger, "id"),
                    title=_get(trigger, "title"),
                    data=_get(trigger, "data", {}) or {},
                )
            )
    return out


def _normalize_actions(raw: Any) -> list[AlarmAction]:
    out: list[AlarmAction] = []
    for category in _get(raw, "action_categories", []) or []:
        cat_id = _get(category, "id")
        cat_title = _get(category, "title")
        for action in _get(category, "actions", []) or []:
            out.append(
                AlarmAction(
                    category_id=cat_id,
                    category_title=cat_title,
                    action_id=_get(action, "id"),
                    title=_get(action, "title"),
                    data=_get(action, "data", {}) or {},
                )
            )
    return out


def alarm_rule_from_controller(raw: Any) -> AlarmRule:
    """Normalize a raw ``/api/v2/alarms/protect`` rule into an AlarmRule."""
    return AlarmRule(
        id=_get(raw, "id"),
        title=_get(raw, "title"),
        triggers=_normalize_triggers(raw),
        actions=_normalize_actions(raw),
        scope=_get(raw, "scope", {}) or {},
        stats=_get(raw, "stats", {}) or {},
        created_at=_get(raw, "created_at"),
        updated_at=_get(raw, "updated_at"),
    )


def alarm_rule_from_legacy(raw: Any) -> AlarmRule:
    """Normalize a legacy ``/automations`` rule into the canonical AlarmRule shape.

    The legacy automations API models rules differently (``conditions`` /
    ``sources`` / ``actions``) and cannot represent AI-powered alarms. This maps
    its fields onto the canonical shape best-effort so the alarm tools return one
    consistent structure regardless of which backend served the request.
    """
    triggers = [
        AlarmTrigger(trigger_id=_get(condition, "type"), data=condition if isinstance(condition, dict) else {})
        for condition in (_get(raw, "conditions", []) or [])
    ]
    actions = [
        AlarmAction(action_id=_get(action, "type"), data=action if isinstance(action, dict) else {})
        for action in (_get(raw, "actions", []) or [])
    ]
    sources = _get(raw, "sources", []) or []
    return AlarmRule(
        id=_get(raw, "id"),
        title=_get(raw, "name"),
        enabled=_get(raw, "enable"),
        triggers=triggers,
        actions=actions,
        scope={"sources": sources} if sources else {},
        stats={},
    )


_WRITE_FIELDS = {"title", "enabled", "triggers", "actions", "scope"}


def _reject_unknown_write_fields(raw: dict[str, Any]) -> None:
    unknown = set(raw) - _WRITE_FIELDS
    if unknown:
        raise ValueError(f"Unknown alarm rule write fields: {', '.join(sorted(unknown))}")


def _to_grouped_entries(items: Any, *, id_key: str, fallback_id_key: str) -> list[list[dict[str, Any]]]:
    """Convert canonical trigger/action rows into the v2 editable envelope."""
    entries: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            raise ValueError("Alarm rule triggers/actions must be objects")
        item_id = item.get(id_key) or item.get(fallback_id_key)
        if not item_id:
            raise ValueError(f"Alarm rule trigger/action is missing {id_key}")
        data = item.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError("Alarm rule trigger/action data must be an object")
        entries.append({"id": item_id, "data": data})
    return [entries] if entries else []


def alarm_rule_to_v2_body(fields: dict[str, Any]) -> dict[str, Any]:
    """Serialize canonical alarm-rule write fields to ``/api/v2/alarms/protect``.

    Live UI capture (2026-06-07) showed create uses ``POST /protect`` and
    update uses ``PATCH /protect/{uuid}``, both with this editable envelope:
    ``triggers_data``, ``actions_data``, ``scope``, and ``title``.
    """
    _reject_unknown_write_fields(fields)
    body: dict[str, Any] = {}
    if "triggers" in fields:
        body["triggers_data"] = _to_grouped_entries(fields["triggers"], id_key="trigger_id", fallback_id_key="id")
    if "actions" in fields:
        body["actions_data"] = _to_grouped_entries(fields["actions"], id_key="action_id", fallback_id_key="id")
    if "scope" in fields:
        body["scope"] = fields["scope"] or {}
    if "title" in fields:
        body["title"] = fields["title"]
    if "enabled" in fields:
        body["enabled"] = fields["enabled"]
    return body


def alarm_rule_to_legacy_body(fields: dict[str, Any]) -> dict[str, Any]:
    """Serialize canonical alarm-rule write fields to legacy Protect automations.

    ``alarm_rule_from_legacy`` stores each raw legacy condition/action dict in
    ``data``. The inverse therefore echoes those nested ``data`` dicts verbatim
    instead of rebuilding ``{"type": ..., **data}``.

    Legacy-only fields such as cooldown, schedules, and historyConditions are
    not expressible in the canonical write shape; update preserves them by
    merging this translated body into the raw legacy rule before PATCH.
    """
    _reject_unknown_write_fields(fields)
    body: dict[str, Any] = {}
    if "title" in fields:
        body["name"] = fields["title"]
    if "enabled" in fields:
        body["enable"] = fields["enabled"]
    if "scope" in fields:
        scope = fields["scope"] or {}
        if isinstance(scope, dict) and "sources" in scope:
            body["sources"] = scope["sources"]
    if "triggers" in fields:
        body["conditions"] = [item.get("data") or {} for item in (fields["triggers"] or []) if isinstance(item, dict)]
    if "actions" in fields:
        body["actions"] = [item.get("data") or {} for item in (fields["actions"] or []) if isinstance(item, dict)]
    return body


ALARM_RULE_MUTABLE_FIELDS: frozenset[str] = frozenset()
ALARM_RULE_READ_ONLY_FIELDS: frozenset[str] = frozenset(AlarmRule.model_fields.keys())
# Alias required by the model-symmetry test harness — read-only model pattern.
MUTABLE_FIELDS = ALARM_RULE_MUTABLE_FIELDS
