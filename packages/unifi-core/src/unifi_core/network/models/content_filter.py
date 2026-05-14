"""Shared field model for Network content filtering profiles (read + update).

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.content_filter``.

- ``ContentFilter`` — list_content_filters + update_content_filter

Factory helpers:
- ``from_controller``      — normalise the raw manager dict → ContentFilter
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test.

NOTE: ``schedule_mode`` is included in the mutable set regardless of whether
it appears in the JSON Schema dict — it was silently dropped by the old
schema-based path and must be passed through to the controller.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

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
    network_ids: List[str] = Field(
        default_factory=list,
        description="Network IDs this filter applies to",
    )
    schedule_mode: Optional[str] = Field(
        default=None,
        description="Schedule mode for the filter (e.g. ALWAYS)",
    )


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
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
