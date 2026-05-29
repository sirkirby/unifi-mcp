"""Shared field models for Protect alarms (read-only).

``protect_alarm_arm`` and ``protect_alarm_disarm`` are action tools; their
input models live in ``_actions.py`` (Task 11). The classes below cover
the read shapes returned by:

* ``protect_alarm_get_status`` / ``protect_alarm_list_profiles`` — arm-state
  surface (AlarmStatus / AlarmProfile / AlarmProfileList)
* ``protect_alarm_list_rules`` / ``protect_alarm_get_rule`` — rule CRUD
  surface (AlarmRule + nested AlarmRuleSource / AlarmRuleCondition /
  AlarmRuleAction / AlarmRuleCooldown / AlarmRuleList)

The rule shapes mirror the Protect private ``/proxy/protect/api/automations``
payload schema. They are intentionally lossy on the deep ``condition``
sub-fields (kept as a free-form ``dict`` rather than enumerating every
possible source/type) because Protect adds new detection sources over
time and we don't want a strict schema to break passthrough on a new
condition type.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AlarmStatus(BaseModel):
    """Canonical Protect alarm arm-state snapshot (read-only)."""

    armed: Optional[bool] = Field(
        default=None, description="Whether the alarm system is currently armed", json_schema_extra={"mutable": False}
    )
    status: Optional[str] = Field(
        default=None, description="Raw status string from the controller", json_schema_extra={"mutable": False}
    )
    active_profile_id: Optional[str] = Field(
        default=None, description="UUID of the active arm profile", json_schema_extra={"mutable": False}
    )
    active_profile_name: Optional[str] = Field(
        default=None, description="Display name of the active arm profile", json_schema_extra={"mutable": False}
    )
    armed_at: Optional[str] = Field(
        default=None, description="ISO timestamp when the system was armed", json_schema_extra={"mutable": False}
    )
    will_be_armed_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp when the system will become armed (activation delay)",
        json_schema_extra={"mutable": False},
    )
    breach_detected_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp of the most recent breach detection",
        json_schema_extra={"mutable": False},
    )
    breach_event_count: Optional[int] = Field(
        default=None, description="Number of breach events since last arm", json_schema_extra={"mutable": False}
    )
    profile_count: Optional[int] = Field(
        default=None, description="Total number of configured arm profiles", json_schema_extra={"mutable": False}
    )


class AlarmProfile(BaseModel):
    """Canonical Protect alarm profile row (read-only)."""

    id: Optional[str] = Field(default=None, description="Alarm profile UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(
        default=None, description="Alarm profile display name", json_schema_extra={"mutable": False}
    )
    record_everything: Optional[bool] = Field(
        default=None,
        description="Whether this profile records all cameras continuously",
        json_schema_extra={"mutable": False},
    )
    activation_delay_ms: Optional[int] = Field(
        default=None,
        description="Delay in milliseconds before the alarm activates after arming",
        json_schema_extra={"mutable": False},
    )
    schedule_count: Optional[int] = Field(
        default=None,
        description="Number of schedules associated with this profile",
        json_schema_extra={"mutable": False},
    )
    automation_count: Optional[int] = Field(
        default=None,
        description="Number of automations associated with this profile",
        json_schema_extra={"mutable": False},
    )


class AlarmProfileList(BaseModel):
    """Wrapper shape returned by ``protect_alarm_list_profiles`` (read-only)."""

    profiles: Optional[List[Any]] = Field(
        default=None, description="List of alarm profile dicts", json_schema_extra={"mutable": False}
    )
    count: Optional[int] = Field(
        default=None, description="Number of profiles in the list", json_schema_extra={"mutable": False}
    )


class AlarmRuleSource(BaseModel):
    """Scope entry in an alarm rule (which camera/device the rule applies to)."""

    device: Optional[str] = Field(
        default=None,
        description="Device MAC address or UUID this source targets",
        json_schema_extra={"mutable": False},
    )
    type: Optional[str] = Field(
        default=None,
        description="Scope mode, typically 'include' or 'exclude'",
        json_schema_extra={"mutable": False},
    )


class AlarmRuleCondition(BaseModel):
    """One AND-condition in an alarm rule.

    The inner ``condition`` dict is kept opaque because Protect supports a
    growing set of source/type combinations (license_plate_known, smartDetectLine,
    Vehicle Description, etc.) and we don't want to enumerate them strictly.
    """

    condition: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw inner condition body (source/type/value triple)",
        json_schema_extra={"mutable": False},
    )


class AlarmRuleActionMetadata(BaseModel):
    """Metadata block on an HTTP_REQUEST action (webhook config)."""

    url: Optional[str] = Field(
        default=None,
        description="Absolute webhook URL with path",
        json_schema_extra={"mutable": False},
    )
    method: Optional[str] = Field(
        default=None,
        description="HTTP method (typically 'POST' or 'GET')",
        json_schema_extra={"mutable": False},
    )
    headers: Optional[List[Any]] = Field(
        default=None,
        description="Custom request headers list",
        json_schema_extra={"mutable": False},
    )
    timeout: Optional[int] = Field(
        default=None,
        description="Request timeout in milliseconds",
        json_schema_extra={"mutable": False},
    )
    use_thumbnail: Optional[bool] = Field(
        default=None,
        description="Whether to attach the event thumbnail to the webhook payload",
        json_schema_extra={"mutable": False},
    )


class AlarmRuleAction(BaseModel):
    """One action attached to an alarm rule (webhook, notify, light, etc.)."""

    type: Optional[str] = Field(
        default=None,
        description="Action kind, e.g. 'HTTP_REQUEST', 'NOTIFY', 'LIGHT', 'SOUND'",
        json_schema_extra={"mutable": False},
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Action-specific metadata (kept opaque to support unknown action types)",
        json_schema_extra={"mutable": False},
    )
    order: Optional[int] = Field(
        default=None,
        description="Action execution order (-1 = default)",
        json_schema_extra={"mutable": False},
    )


class AlarmRuleCooldown(BaseModel):
    """Cooldown block — suppresses repeat fires within ``timeout`` ms."""

    enable: Optional[bool] = Field(
        default=None,
        description="Whether cooldown is active",
        json_schema_extra={"mutable": False},
    )
    timeout: Optional[int] = Field(
        default=None,
        description="Cooldown duration in milliseconds",
        json_schema_extra={"mutable": False},
    )


class AlarmRule(BaseModel):
    """Canonical Protect alarm-manager rule (read-only).

    Mirrors the ``/proxy/protect/api/automations`` payload schema.
    Deeply-nested condition bodies are kept opaque (see module docstring).
    """

    id: Optional[str] = Field(default=None, description="Rule UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Rule display name", json_schema_extra={"mutable": False})
    enable: Optional[bool] = Field(
        default=None,
        description="Whether the rule is currently enabled",
        json_schema_extra={"mutable": False},
    )
    is_created_by_system: Optional[bool] = Field(
        default=None,
        description="True for built-in rules created by Protect itself",
        json_schema_extra={"mutable": False},
    )
    sources: Optional[List[AlarmRuleSource]] = Field(
        default=None,
        description="Scope list: which cameras/devices this rule applies to",
        json_schema_extra={"mutable": False},
    )
    conditions: Optional[List[AlarmRuleCondition]] = Field(
        default=None,
        description="AND-conditions that must all match for the rule to fire",
        json_schema_extra={"mutable": False},
    )
    history_conditions: Optional[List[Any]] = Field(
        default=None,
        description="Historical/cross-event conditions (raw passthrough)",
        json_schema_extra={"mutable": False},
    )
    schedules: Optional[List[Any]] = Field(
        default=None,
        description="Schedule windows when the rule is active (raw passthrough)",
        json_schema_extra={"mutable": False},
    )
    actions: Optional[List[AlarmRuleAction]] = Field(
        default=None,
        description="Actions to execute when the rule fires",
        json_schema_extra={"mutable": False},
    )
    cooldown: Optional[AlarmRuleCooldown] = Field(
        default=None,
        description="Cooldown configuration to suppress repeat fires",
        json_schema_extra={"mutable": False},
    )


class AlarmRuleList(BaseModel):
    """Wrapper shape returned by ``protect_alarm_list_rules`` (read-only)."""

    rules: Optional[List[Any]] = Field(
        default=None,
        description="List of alarm rule dicts",
        json_schema_extra={"mutable": False},
    )
    count: Optional[int] = Field(
        default=None,
        description="Number of rules in the list",
        json_schema_extra={"mutable": False},
    )


MUTABLE_FIELDS = frozenset()
READ_ONLY_FIELDS = (
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


def _coerce_list(value: Any) -> Optional[List[Any]]:
    """Return ``value`` if it's a list, otherwise None."""
    return value if isinstance(value, list) else None


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stringify_dt(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return None
    return str(value)


def status_from_controller(raw: Any) -> AlarmStatus:
    """Build an AlarmStatus from a manager dict or object."""
    return AlarmStatus(
        armed=_get(raw, "armed"),
        status=_get(raw, "status"),
        active_profile_id=_get(raw, "active_profile_id"),
        active_profile_name=_get(raw, "active_profile_name"),
        armed_at=_stringify_dt(_get(raw, "armed_at")),
        will_be_armed_at=_stringify_dt(_get(raw, "will_be_armed_at")),
        breach_detected_at=_stringify_dt(_get(raw, "breach_detected_at")),
        breach_event_count=_get(raw, "breach_event_count"),
        profile_count=_get(raw, "profile_count"),
    )


def profile_from_controller(raw: Any) -> AlarmProfile:
    """Build an AlarmProfile from a manager dict or object."""
    return AlarmProfile(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        record_everything=_get(raw, "record_everything"),
        activation_delay_ms=_get(raw, "activation_delay_ms"),
        schedule_count=_get(raw, "schedule_count"),
        automation_count=_get(raw, "automation_count"),
    )


def profile_list_from_controller(raw: Any) -> AlarmProfileList:
    """Build an AlarmProfileList from a manager dict or object.

    Accepts:
    - a dict with ``profiles`` (list) and ``count`` keys (wrapper shape)
    - anything else: ``profiles`` coalesces to None
    """
    profiles = _get(raw, "profiles")
    if not isinstance(profiles, list):
        profiles = None
    return AlarmProfileList(
        profiles=profiles,
        count=_get(raw, "count"),
    )


def _rule_source_from(raw: Any) -> AlarmRuleSource:
    return AlarmRuleSource(
        device=_get(raw, "device"),
        type=_get(raw, "type"),
    )


def _rule_condition_from(raw: Any) -> AlarmRuleCondition:
    inner = _get(raw, "condition")
    if not isinstance(inner, dict):
        inner = None
    return AlarmRuleCondition(condition=inner)


def _rule_action_from(raw: Any) -> AlarmRuleAction:
    metadata = _get(raw, "metadata")
    if not isinstance(metadata, dict):
        metadata = None
    return AlarmRuleAction(
        type=_get(raw, "type"),
        metadata=metadata,
        order=_get(raw, "order"),
    )


def _rule_cooldown_from(raw: Any) -> Optional[AlarmRuleCooldown]:
    if not isinstance(raw, dict):
        return None
    return AlarmRuleCooldown(
        enable=_get(raw, "enable"),
        timeout=_get(raw, "timeout"),
    )


def rule_from_controller(raw: Any) -> AlarmRule:
    """Build an AlarmRule from a raw Protect ``/automations`` payload dict."""
    sources_raw = _coerce_list(_get(raw, "sources"))
    conditions_raw = _coerce_list(_get(raw, "conditions"))
    actions_raw = _coerce_list(_get(raw, "actions"))

    sources = [_rule_source_from(s) for s in sources_raw] if sources_raw is not None else None
    conditions = [_rule_condition_from(c) for c in conditions_raw] if conditions_raw is not None else None
    actions = [_rule_action_from(a) for a in actions_raw] if actions_raw is not None else None

    return AlarmRule(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        enable=_get(raw, "enable"),
        is_created_by_system=_get(raw, "isCreatedBySystem"),
        sources=sources,
        conditions=conditions,
        history_conditions=_coerce_list(_get(raw, "historyConditions")),
        schedules=_coerce_list(_get(raw, "schedules")),
        actions=actions,
        cooldown=_rule_cooldown_from(_get(raw, "cooldown")),
    )


def rule_list_from_controller(raw: Any) -> AlarmRuleList:
    """Build an AlarmRuleList from a manager dict or object.

    Accepts:
    - a dict with ``rules`` (list) and ``count`` keys (wrapper shape)
    - anything else: ``rules`` coalesces to None
    """
    rules = _get(raw, "rules")
    if not isinstance(rules, list):
        rules = None
    return AlarmRuleList(
        rules=rules,
        count=_get(raw, "count"),
    )


# ---------------------------------------------------------------------------
# rule_to_controller: snake_case → camelCase normalization for POST/PATCH body
# ---------------------------------------------------------------------------
#
# The read tools (``protect_alarm_list_rules`` / ``protect_alarm_get_rule``)
# normalize controller payloads to snake_case via ``rule_from_controller``.
# Protect's ``POST /automations`` endpoint is strict camelCase, so a naive
# read → mutate → create round-trip fails with 400 "Failed to parse
# 'request-body'" on the snake_case sibling fields (``is_created_by_system``,
# ``history_conditions``, action metadata ``use_thumbnail``). ``PATCH`` is
# permissive in practice today but the same translation defends against future
# tightening. We rename ONLY the small fixed set of fields that differ in case
# and pass everything else through untouched so unknown / future Protect
# fields keep working.

_RULE_TOP_LEVEL_RENAMES: dict[str, str] = {
    "is_created_by_system": "isCreatedBySystem",
    "history_conditions": "historyConditions",
}

_ACTION_METADATA_RENAMES: dict[str, str] = {
    "use_thumbnail": "useThumbnail",
}


def _metadata_to_controller(metadata: dict[str, Any]) -> dict[str, Any]:
    """Two-pass snake_case -> camelCase rename for action metadata.

    Mirrors the top-level :func:`rule_to_controller` strategy: translate the
    snake_case keys first, then pass through everything else so an explicit
    camelCase sibling overrides the translated value. A single-pass
    comprehension would let the snake_case form clobber the camelCase form (or
    not) depending on dict insertion order — camelCase must always win.
    """
    out: dict[str, Any] = {}
    # First pass: snake_case-translatable keys.
    for key in metadata:
        if key in _ACTION_METADATA_RENAMES:
            out[_ACTION_METADATA_RENAMES[key]] = metadata[key]
    # Second pass: pass through everything else; an explicit camelCase form
    # overrides the snake_case translation above.
    for key, value in metadata.items():
        if key in _ACTION_METADATA_RENAMES:
            continue
        out[key] = value
    return out


def _action_to_controller(action: Any) -> Any:
    if not isinstance(action, dict):
        return action
    out: dict[str, Any] = {}
    for key, value in action.items():
        if key == "metadata" and isinstance(value, dict):
            value = _metadata_to_controller(value)
        out[key] = value
    return out


def rule_to_controller(body: Any) -> Any:
    """Translate a rule body to the camelCase shape Protect's controller expects.

    Inverse of :func:`rule_from_controller`. Translates the few fields where
    the read tools emit snake_case but the controller demands camelCase.
    All other keys (including unknown / future fields) pass through
    unchanged. If the caller provides BOTH the snake_case and camelCase form
    of a field, the camelCase value wins (we never clobber an explicit
    camelCase value with a stale snake_case sibling).

    Non-dict inputs are returned as-is so the downstream call surfaces the
    real type error instead of an opaque ``AttributeError``.
    """
    if not isinstance(body, dict):
        return body

    out: dict[str, Any] = {}
    # First pass: process snake_case-translatable keys (so a later explicit
    # camelCase write can override them).
    for key in body:
        if key in _RULE_TOP_LEVEL_RENAMES:
            out[_RULE_TOP_LEVEL_RENAMES[key]] = body[key]
    # Second pass: pass through everything else (and let any explicit
    # camelCase form override the snake_case translation above).
    for key, value in body.items():
        if key in _RULE_TOP_LEVEL_RENAMES:
            continue
        if key == "actions" and isinstance(value, list):
            value = [_action_to_controller(a) for a in value]
        out[key] = value
    return out
