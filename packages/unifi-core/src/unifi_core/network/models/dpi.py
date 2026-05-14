"""Shared field models for Network DPI (Deep Packet Inspection) resources.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.dpi``:

- ``DpiApplication`` — list_dpi_applications (V2 official integration API)
- ``DpiCategory``    — list_dpi_categories

Both classes are read-only (no create/update/delete tools exist for DPI
catalog entries). DPI ids can be 0; the factory helpers use explicit
``is None`` checks to preserve zero values rather than the ``a or b``
pattern that would collapse 0 to None.

Factory helpers:
- ``dpi_application_from_controller`` — normalise raw → DpiApplication
- ``dpi_category_from_controller``    — normalise raw → DpiCategory

MUTABLE_FIELDS = frozenset() for both classes.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# DpiApplication
# ---------------------------------------------------------------------------


class DpiApplication(BaseModel):
    """A DPI application classification entry."""

    id: Optional[int] = Field(
        default=None,
        description="Application numeric ID (can be 0)",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="Application display name",
        json_schema_extra={"mutable": False},
    )
    category_id: Optional[int] = Field(
        default=None,
        description="Parent category numeric ID",
        json_schema_extra={"mutable": False},
    )


DPIAPPLICATION_MUTABLE_FIELDS: frozenset[str] = frozenset()
DPIAPPLICATION_READ_ONLY_FIELDS: frozenset[str] = frozenset(DpiApplication.model_fields.keys())


def dpi_application_from_controller(obj: Any) -> DpiApplication:
    """Build a DpiApplication from a controller API response.

    Uses explicit is-None checks to preserve id/category_id == 0.
    """
    ident = _get(obj, "id")
    if ident is None:
        ident = _get(obj, "_id")
    cat = _get(obj, "categoryId")
    if cat is None:
        cat = _get(obj, "category_id")
    return DpiApplication(
        id=ident,
        name=_get(obj, "name"),
        category_id=cat,
    )


# ---------------------------------------------------------------------------
# DpiCategory
# ---------------------------------------------------------------------------


class DpiCategory(BaseModel):
    """A DPI application category."""

    id: Optional[int] = Field(
        default=None,
        description="Category numeric ID (can be 0)",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="Category display name",
        json_schema_extra={"mutable": False},
    )


DPICATEGORY_MUTABLE_FIELDS: frozenset[str] = frozenset()
DPICATEGORY_READ_ONLY_FIELDS: frozenset[str] = frozenset(DpiCategory.model_fields.keys())

# Module-level alias (symmetry test fallback)
MUTABLE_FIELDS = DPIAPPLICATION_MUTABLE_FIELDS


def dpi_category_from_controller(obj: Any) -> DpiCategory:
    """Build a DpiCategory from a controller API response.

    Uses explicit is-None checks to preserve id == 0.
    """
    ident = _get(obj, "id")
    if ident is None:
        ident = _get(obj, "_id")
    return DpiCategory(
        id=ident,
        name=_get(obj, "name"),
    )
