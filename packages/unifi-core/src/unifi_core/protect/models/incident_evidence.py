"""Validated arguments for bounded Protect incident evidence collection."""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from unifi_core.incident_collection import MAX_FILTER_IDS, IncidentCollectionRequest

# Protect camera IDs are opaque tokens; anything with whitespace or control
# characters is not one, and nothing is trimmed or case-folded to fit.
_CAMERA_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class ProtectIncidentRequest(IncidentCollectionRequest):
    camera_ids: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_FILTER_IDS,
        description=(
            "Exact Protect camera IDs; each is read as its own source. Omit to read every camera. "
            "Camera names are never resolved to IDs."
        ),
    )

    @field_validator("camera_ids", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return () if value is None else value

    @field_validator("camera_ids")
    @classmethod
    def _ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not all(_CAMERA_ID.match(camera_id) for camera_id in value):
            raise ValueError("camera_ids must be exact Protect camera IDs (letters, digits, '.', '_', ':', '-')")
        return tuple(sorted(set(value)))
