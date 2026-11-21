"""Closed arguments for InnerSpace reads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from unifi_core.innerspace.units import Unit
from unifi_core.request_paths import InvalidRequestPathError, object_id


def _identifier(value: str, kind: str) -> str:
    """Accept one path segment; the failure text is fixed and never holds the value."""
    try:
        return object_id(value, kind)
    except InvalidRequestPathError:
        raise ValueError(f"Provide a valid InnerSpace {kind} identifier") from None


class InnerSpaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class InnerSpacePlanInput(InnerSpaceInput):
    plan_id: str

    @field_validator("plan_id")
    @classmethod
    def plan(cls, value: str) -> str:
        return _identifier(value, "plan")


class InnerSpaceSiteInput(InnerSpaceInput):
    site_id: str | None = None

    @field_validator("site_id")
    @classmethod
    def site(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value, "site")


class InnerSpaceListInput(InnerSpaceInput):
    limit: int = Field(500, ge=1, le=2000)


class InnerSpaceUnitInput(InnerSpaceInput):
    unit: Unit | None = None


class InnerSpaceAssetInput(InnerSpacePlanInput):
    include_image: bool = False
    image_type: Literal["image/png", "image/jpeg"] | None = None


class InnerSpaceProjectInput(InnerSpaceUnitInput):
    include_shapes: bool = False
