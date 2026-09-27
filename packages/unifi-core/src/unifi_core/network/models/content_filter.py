"""Shared field model for Network content filtering profiles.

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.content_filter``.

- ``ContentFilter`` — list, create, and update content filters

Factory helpers:
- ``from_controller``      — normalise the raw manager dict → ContentFilter
- ``to_controller_update`` — filter a partial dict to mutable keys only and map
  model field names onto the controller dialect (``blocked_categories`` →
  ``categories``)
- ``to_controller_create`` — validate name and exclusive scope for a new profile

``MUTABLE_FIELDS`` drives the cross-layer symmetry test.

The controller stores schedule fields in a nested object. The manager deep-merges
partial schedule updates onto the fetched profile to preserve sibling fields.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from unifi_core.mac import looks_like_mac, normalize_mac, normalize_mac_list

# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class ContentFilter(BaseModel):
    """Canonical content filter profile model (read + mutable update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Content filter profile UUID",
        json_schema_extra={"mutable": False},
    )
    profile: Optional[str] = Field(
        default=None,
        description="Profile type identifier",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by update) ---
    name: Optional[str] = Field(
        default=None,
        description="Profile display name",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the content filter is active",
    )
    blocked_categories: List[str] = Field(
        default_factory=list,
        description="List of blocked content categories",
    )
    safe_search: List[str] = Field(
        default_factory=list,
        description="Safe search enforcement (GOOGLE, YOUTUBE, BING)",
    )
    client_macs: List[str] = Field(
        default_factory=list,
        description="Client MAC addresses this filter applies to",
    )

    @field_validator("client_macs")
    @classmethod
    def _normalize_client_macs(cls, v):
        """Lowercase the MACs the controller reports."""
        if v is None:
            return v
        return [normalize_mac(m) or m for m in v]

    network_ids: List[str] = Field(
        default_factory=list,
        description="Network IDs this filter applies to",
    )
    schedule_mode: Optional[str] = Field(
        default=None,
        description=(
            "When the filter is in force. One of ALWAYS, EVERY_DAY, EVERY_WEEK, CUSTOM, "
            "ONE_TIME_ONLY. Sent to the controller as schedule.mode."
        ),
    )
    schedule_days: Optional[List[str]] = Field(
        default=None, description="Lowercase days: mon, tue, wed, thu, fri, sat, sun"
    )
    schedule_time_all_day: Optional[bool] = Field(default=None, description="Whether the schedule covers the whole day")
    schedule_time_start: Optional[str] = Field(default=None, description="Start time in HH:MM, 24-hour format")
    schedule_time_end: Optional[str] = Field(default=None, description="End time in HH:MM, 24-hour format")
    schedule_date_start: Optional[str] = Field(default=None, description="Start date in YYYY-MM-DD format")
    schedule_date_end: Optional[str] = Field(default=None, description="End date in YYYY-MM-DD format")


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in ContentFilter.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in ContentFilter.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> ContentFilter:
    """Build a ContentFilter from a controller API response dict."""
    # Coalesce categories: controller may use 'categories' or 'blocked_categories'
    categories = _get(raw, "blocked_categories") or _get(raw, "categories") or []
    if not isinstance(categories, list):
        categories = []

    client_macs = _get(raw, "client_macs") or []
    if not isinstance(client_macs, list):
        client_macs = []

    network_ids = _get(raw, "network_ids") or []
    if not isinstance(network_ids, list):
        network_ids = []

    safe_search = _get(raw, "safe_search") or []
    if not isinstance(safe_search, list):
        safe_search = []

    # Extract schedule_mode from nested schedule object
    schedule = _get(raw, "schedule") or {}
    schedule_mode = schedule.get("mode") if isinstance(schedule, dict) else _get(raw, "schedule_mode")
    schedule = schedule if isinstance(schedule, dict) else {}

    enabled_raw = _get(raw, "enabled", None)
    enabled = enabled_raw if isinstance(enabled_raw, bool) else None

    return ContentFilter(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        enabled=enabled,
        profile=_get(raw, "profile"),
        blocked_categories=list(categories),
        safe_search=list(safe_search),
        client_macs=list(client_macs),
        network_ids=list(network_ids),
        schedule_mode=schedule_mode,
        schedule_days=schedule.get("repeat_on_days"),
        schedule_time_all_day=schedule.get("time_all_day"),
        schedule_time_start=schedule.get("time_range_start"),
        schedule_time_end=schedule.get("time_range_end"),
        schedule_date_start=schedule.get("date_start"),
        schedule_date_end=schedule.get("date_end"),
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    Maps model field names to controller API field names.
    Accepts ``categories`` as an alias for ``blocked_categories`` so callers can
    pass either the controller field name or the model field name.
    """
    if "schedule" in fields:
        raise ValueError("Use flattened schedule fields; nested schedule is not accepted")
    if "categories" in fields and "blocked_categories" not in fields:
        fields = {**fields, "blocked_categories": fields["categories"]}
        fields = {k: v for k, v in fields.items() if k != "categories"}
    result = {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
    # Validate the caller's partial object with the shared model. Unknown keys
    # retain the existing update helper's drop behaviour.
    result = ContentFilter.model_validate(result, strict=True).model_dump(exclude_unset=True)
    if "name" in result and not result["name"].strip():
        raise ValueError("name must be a non-empty string")
    if "blocked_categories" in result and (
        not result["blocked_categories"] or any(not category.strip() for category in result["blocked_categories"])
    ):
        raise ValueError("blocked_categories must be a non-empty list of non-empty strings")
    if "client_macs" in result and any(not looks_like_mac(mac) for mac in result["client_macs"]):
        raise ValueError("client_macs must contain valid MAC addresses")
    # Map blocked_categories → categories
    if "blocked_categories" in result:
        result["categories"] = result.pop("blocked_categories")
    # Nest schedule_mode → schedule.mode. The manager deep-merges onto the fetched
    # profile, so sibling keys (repeat_on_days, time_all_day) are preserved.
    schedule_keys = {
        "schedule_mode": "mode",
        "schedule_days": "repeat_on_days",
        "schedule_time_all_day": "time_all_day",
        "schedule_time_start": "time_range_start",
        "schedule_time_end": "time_range_end",
        "schedule_date_start": "date_start",
        "schedule_date_end": "date_end",
    }
    schedule = {}
    for public_key, controller_key in schedule_keys.items():
        if public_key in result:
            schedule[controller_key] = _validate_schedule_field(public_key, result.pop(public_key))
    if schedule:
        result["schedule"] = schedule
    # This builder takes the caller's raw dict, so the model's field validator
    # never runs for a partial update.
    if "client_macs" in result:
        result["client_macs"] = normalize_mac_list(result["client_macs"])
    return result


def _validate_schedule_field(key: str, value: Any) -> Any:
    if key == "schedule_mode":
        if not isinstance(value, str) or value not in {"ALWAYS", "EVERY_DAY", "EVERY_WEEK", "CUSTOM", "ONE_TIME_ONLY"}:
            raise ValueError("schedule_mode must be ALWAYS, EVERY_DAY, EVERY_WEEK, CUSTOM, or ONE_TIME_ONLY")
    elif key == "schedule_days":
        valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        if not isinstance(value, list) or any(not isinstance(day, str) or day not in valid_days for day in value):
            raise ValueError("schedule_days must contain lowercase mon, tue, wed, thu, fri, sat, or sun")
    elif key == "schedule_time_all_day":
        if not isinstance(value, bool):
            raise ValueError("schedule_time_all_day must be a boolean")
    elif key in {"schedule_time_start", "schedule_time_end"}:
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
            raise ValueError(f"{key} must be HH:MM in 24-hour format")
    elif key in {"schedule_date_start", "schedule_date_end"}:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{key} must be YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{key} must be a valid date") from exc
    return value


def with_create_defaults(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Show the effective public fields for a new, disabled all-day profile."""
    return {
        "enabled": False,
        "schedule_mode": "ALWAYS",
        "schedule_days": [],
        "schedule_time_all_day": True,
        **fields,
    }


def to_controller_create(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a new profile and translate public fields to the V2 dialect."""
    fields = with_create_defaults(fields)
    for required_schedule_field in ("schedule_mode", "schedule_days", "schedule_time_all_day"):
        if fields[required_schedule_field] is None:
            raise ValueError(f"{required_schedule_field} cannot be null on create")
    unknown = set(fields) - MUTABLE_FIELDS - {"categories"}
    if unknown:
        raise ValueError(f"Unknown or read-only content filter fields: {sorted(unknown)}")
    canonical_fields = {**fields}
    if "categories" in canonical_fields:
        canonical_fields.setdefault("blocked_categories", canonical_fields["categories"])
        canonical_fields.pop("categories")
    profile = ContentFilter.model_validate(canonical_fields, strict=True)
    if not profile.name or not profile.name.strip():
        raise ValueError("name must be a non-empty string")
    if not profile.blocked_categories or any(not category.strip() for category in profile.blocked_categories):
        raise ValueError("blocked_categories must be a non-empty list of non-empty strings")
    if "enabled" in fields and profile.enabled is None:
        raise ValueError("enabled must be a boolean when provided")
    client_macs = profile.client_macs
    network_ids = profile.network_ids
    if bool(client_macs) == bool(network_ids):
        raise ValueError("Exactly one non-empty client_macs or network_ids scope is required")
    if any(not value.strip() for value in client_macs + network_ids):
        raise ValueError("Scope identifiers must be non-empty strings")
    payload = to_controller_update(profile.model_dump(exclude_unset=True))
    payload["name"] = profile.name.strip()
    payload.setdefault("enabled", False)
    return payload
