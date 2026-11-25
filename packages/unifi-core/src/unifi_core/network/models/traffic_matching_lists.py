"""Shared field model for Integration API traffic matching lists.

Mirrors the schemas documented at
``/v1/sites/{siteId}/traffic-matching-lists`` (UniFi Network API, present
since the 10.4.57 specification).

- ``TrafficMatchingList`` — list/get/create payloads

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → TrafficMatchingList
- ``to_controller_create`` — translate create arguments → request payload

``MUTABLE_FIELDS``/``READ_ONLY_FIELDS`` keep create parameters aligned with
list output: every mutable field is a create parameter.

The ``type`` value has no documented enum (example names are "Allowed port
list" and "Protected IP list"; the item DTOs are Port matching and IPv4
matching), so it is carried as an opaque string and never validated against
invented values. Observed controller values — PORTS, IPV4_ADDRESSES and
IPV6_ADDRESSES — are examples, not a published enum. Item entries are passed
through verbatim — the controller is the authority on accepted item shapes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

MUTABLE_FIELDS = frozenset({"name", "type", "items"})
READ_ONLY_FIELDS = frozenset({"id"})


class TrafficMatchingList(BaseModel):
    """Canonical traffic matching list model (read + create)."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    id: Optional[str] = Field(
        default=None,
        description="Integration API UUID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description='List name (example values: "Allowed port list", "Protected IP list")',
    )
    type: Optional[str] = Field(
        default=None,
        description=(
            "List type as an opaque string; the controller defines the accepted values "
            "(port and IPv4 list DTOs exist; no enum is published)"
        ),
    )
    items: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Entry objects exactly as the controller returned them; entries are passed "
            "through without validation of their inner keys"
        ),
    )


def from_controller(raw: Dict[str, Any]) -> TrafficMatchingList:
    """Normalise the raw controller dict into a TrafficMatchingList."""
    if not isinstance(raw, dict):
        raise ValueError("Controller returned an invalid traffic matching list response")
    items = raw.get("items")
    return TrafficMatchingList(
        id=str(raw["id"]) if raw.get("id") is not None else None,
        name=raw.get("name"),
        type=raw.get("type"),
        items=[dict(item) for item in items] if isinstance(items, list) else None,
    )


def to_controller_create(
    name: str,
    list_type: str,
    items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the create payload from validated arguments."""
    if items is not None and (not isinstance(items, list) or not all(isinstance(item, dict) for item in items)):
        raise ValueError("items must be a list of objects")
    payload: Dict[str, Any] = {"name": name, "type": list_type}
    if items is not None:
        payload["items"] = items
    return payload
