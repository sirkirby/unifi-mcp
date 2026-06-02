"""Strawberry types for protect/alarms (Phase 6 PR3 Task B).

Two read serializers move here from
``unifi_api.serializers.protect.alarms``:

- ``AlarmStatus``  — protect_alarm_get_status (DETAIL pass-through). The
  manager / tool layer hands a flat dict (``armed``, ``status``,
  ``active_profile_id``/``_name``, ``armed_at``, ``will_be_armed_at``,
  ``breach_detected_at``, ``breach_event_count``, ``profile_count``).
  Pass-through preserves any additional manager keys byte-identically.
- ``AlarmProfileList`` — protect_alarm_list_profiles (DETAIL wrapper-dict
  pass-through). The tool/action layer hands either a bare
  ``list[dict]`` from the manager (which we wrap into
  ``{profiles, count}``) or an already-wrapped dict. The wrapper is the
  payload the action endpoint surfaces.
- ``AlarmProfile`` — sub-row type the REST route uses to project each
  per-profile dict. The manager's flattened shape (``id, name,
  record_everything, activation_delay_ms, schedule_count,
  automation_count``) flows through as-is.

Mutation acks (``protect_alarm_arm`` / ``protect_alarm_disarm``) stay in
the serializer module — those tools dispatch via the manager's
preview-and-confirm path.
"""

from __future__ import annotations

from typing import Any

import strawberry


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="UniFi Protect alarm system arm-state snapshot.")
class AlarmStatus:
    """DETAIL pass-through for the alarm status dict produced by the tool.

    Mirrors ``AlarmStatusSerializer.serialize`` exactly: identity for
    dicts (preserving extra keys byte-for-byte), ``model_dump`` for
    pydantic-shaped input, ``{"result": str(obj)}`` fallback.
    """

    armed: bool | None
    status: str | None
    active_profile_id: str | None
    active_profile_name: str | None
    armed_at: str | None
    will_be_armed_at: str | None
    breach_detected_at: str | None
    breach_event_count: int | None
    profile_count: int | None

    # Carry the original payload so DETAIL pass-through preserves the
    # exact dict shape (the manager may return a wider set of keys than
    # the typed fields enumerate, e.g. ``profiles: []``).
    _raw: strawberry.Private[dict[str, Any] | None] = None
    _fallback: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AlarmStatus":
        if isinstance(obj, dict):
            inst = cls(
                armed=obj.get("armed"),
                status=obj.get("status"),
                active_profile_id=obj.get("active_profile_id"),
                active_profile_name=obj.get("active_profile_name"),
                armed_at=obj.get("armed_at"),
                will_be_armed_at=obj.get("will_be_armed_at"),
                breach_detected_at=obj.get("breach_detected_at"),
                breach_event_count=obj.get("breach_event_count"),
                profile_count=obj.get("profile_count"),
            )
            inst._raw = dict(obj)
            return inst
        if hasattr(obj, "model_dump"):
            dumped = obj.model_dump()
            inst = cls(
                armed=dumped.get("armed"),
                status=dumped.get("status"),
                active_profile_id=dumped.get("active_profile_id"),
                active_profile_name=dumped.get("active_profile_name"),
                armed_at=dumped.get("armed_at"),
                will_be_armed_at=dumped.get("will_be_armed_at"),
                breach_detected_at=dumped.get("breach_detected_at"),
                breach_event_count=dumped.get("breach_event_count"),
                profile_count=dumped.get("profile_count"),
            )
            inst._raw = dict(dumped)
            return inst
        inst = cls(
            armed=None,
            status=None,
            active_profile_id=None,
            active_profile_name=None,
            armed_at=None,
            will_be_armed_at=None,
            breach_detected_at=None,
            breach_event_count=None,
            profile_count=None,
        )
        inst._fallback = str(obj)
        return inst

    def to_dict(self) -> dict:
        if self._raw is not None:
            return self._raw
        if self._fallback is not None:
            return {"result": self._fallback}
        return {}


@strawberry.type(description="A UniFi Protect alarm profile (manager flattened shape).")
class AlarmProfile:
    """Sub-row for a single profile — used by the per-page REST projection.

    Pass-through: manager helper already returns a flat dict; we surface
    the same key set without renaming.
    """

    id: strawberry.ID | None
    name: str | None
    record_everything: bool | None
    activation_delay_ms: int | None
    schedule_count: int | None
    automation_count: int | None

    _raw: strawberry.Private[dict[str, Any] | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "record_everything", "schedule_count"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AlarmProfile":
        if isinstance(obj, dict):
            inst = cls(
                id=obj.get("id"),
                name=obj.get("name"),
                record_everything=obj.get("record_everything"),
                activation_delay_ms=obj.get("activation_delay_ms"),
                schedule_count=obj.get("schedule_count"),
                automation_count=obj.get("automation_count"),
            )
            inst._raw = dict(obj)
            return inst
        if hasattr(obj, "model_dump"):
            dumped = obj.model_dump()
            inst = cls(
                id=dumped.get("id"),
                name=dumped.get("name"),
                record_everything=dumped.get("record_everything"),
                activation_delay_ms=dumped.get("activation_delay_ms"),
                schedule_count=dumped.get("schedule_count"),
                automation_count=dumped.get("automation_count"),
            )
            inst._raw = dict(dumped)
            return inst
        inst = cls(
            id=None,
            name=None,
            record_everything=None,
            activation_delay_ms=None,
            schedule_count=None,
            automation_count=None,
        )
        return inst

    def to_dict(self) -> dict:
        if self._raw is not None:
            return self._raw
        return {}


@strawberry.type(description="A UniFi Protect alarm rule (normalized; includes AI-powered alarms).")
class AlarmRule:
    """DETAIL pass-through for a normalized alarm rule.

    Triggers/actions/scope/stats are kept as JSON because per-trigger/action
    ``data`` shape varies by type (e.g. AI Natural Language carries
    nlsSentence/nlsThreshold), so a strict schema would break passthrough.
    """

    id: strawberry.ID | None
    title: str | None
    enabled: bool | None
    triggers: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    actions: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    scope: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    stats: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    created_at: str | None
    updated_at: str | None

    _raw: strawberry.Private[dict[str, Any] | None] = None
    _fallback: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind, "primary_key": "id", "display_columns": ["title"]}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AlarmRule":
        source = obj
        if not isinstance(source, dict) and hasattr(obj, "model_dump"):
            source = obj.model_dump()
        if isinstance(source, dict):
            inst = cls(
                id=source.get("id"),
                title=source.get("title"),
                enabled=source.get("enabled"),
                triggers=source.get("triggers"),
                actions=source.get("actions"),
                scope=source.get("scope"),
                stats=source.get("stats"),
                created_at=source.get("created_at"),
                updated_at=source.get("updated_at"),
            )
            inst._raw = dict(source)
            return inst
        inst = cls(
            id=None,
            title=None,
            enabled=None,
            triggers=None,
            actions=None,
            scope=None,
            stats=None,
            created_at=None,
            updated_at=None,
        )
        inst._fallback = str(obj)
        return inst

    def to_dict(self) -> dict:
        if self._raw is not None:
            return self._raw
        if self._fallback is not None:
            return {"result": self._fallback}
        return {}


@strawberry.type(description="Wrapper for protect_alarm_list_rules — {rules, count}.")
class AlarmRuleList:
    """Wrapper-dict pass-through for ``{rules: [...], count}``.

    Mirrors :class:`AlarmProfileList`: dict identity, list-coercion,
    ``model_dump`` for pydantic, ``{"result": str(obj)}`` fallback. The
    action endpoint surfaces the wrapper directly; per-rule projection
    via :class:`AlarmRule` is used for the REST per-row view.
    """

    rules: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    count: int | None

    _raw: strawberry.Private[dict[str, Any] | None] = None
    _fallback: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AlarmRuleList":
        if isinstance(obj, dict):
            inst = cls(
                rules=obj.get("rules") or [],
                count=obj.get("count"),
            )
            inst._raw = dict(obj)
            return inst
        if isinstance(obj, list):
            wrapper = {"rules": list(obj), "count": len(obj)}
            inst = cls(rules=wrapper["rules"], count=wrapper["count"])
            inst._raw = wrapper
            return inst
        if hasattr(obj, "model_dump"):
            dumped = obj.model_dump()
            inst = cls(
                rules=dumped.get("rules") or [],
                count=dumped.get("count"),
            )
            inst._raw = dict(dumped)
            return inst
        inst = cls(rules=None, count=None)
        inst._fallback = str(obj)
        return inst

    def to_dict(self) -> dict:
        if self._raw is not None:
            return self._raw
        if self._fallback is not None:
            return {"result": self._fallback}
        return {}


@strawberry.type(description="Wrapper for protect_alarm_list_profiles — {profiles, count}.")
class AlarmProfileList:
    """Wrapper-dict pass-through for ``{profiles: [...], count}``.

    Mirrors ``AlarmProfileSerializer.serialize`` exactly: dict identity,
    list-coercion, ``model_dump`` for pydantic, ``{"result": str(obj)}``
    fallback. Used by the action endpoint where the whole response is
    the wrapper. The REST list route projects per-profile via
    ``AlarmProfile`` directly.
    """

    profiles: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    count: int | None

    _raw: strawberry.Private[dict[str, Any] | None] = None
    _fallback: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AlarmProfileList":
        if isinstance(obj, dict):
            inst = cls(
                profiles=obj.get("profiles") or [],
                count=obj.get("count"),
            )
            inst._raw = dict(obj)
            return inst
        if isinstance(obj, list):
            wrapper = {"profiles": list(obj), "count": len(obj)}
            inst = cls(profiles=wrapper["profiles"], count=wrapper["count"])
            inst._raw = wrapper
            return inst
        if hasattr(obj, "model_dump"):
            dumped = obj.model_dump()
            inst = cls(
                profiles=dumped.get("profiles") or [],
                count=dumped.get("count"),
            )
            inst._raw = dict(dumped)
            return inst
        inst = cls(profiles=None, count=None)
        inst._fallback = str(obj)
        return inst

    def to_dict(self) -> dict:
        if self._raw is not None:
            return self._raw
        if self._fallback is not None:
            return {"result": self._fallback}
        return {}
