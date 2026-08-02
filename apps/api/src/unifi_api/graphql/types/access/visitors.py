"""Strawberry projection for the Access Developer API visitor family.

Read tools use this type; create/delete acknowledgement dicts remain in
``serializers/access/visitors.py``.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.access.models.visitors import from_controller as visitor_from_controller


@strawberry.type(
    description=(
        "A time-bounded UniFi Access Developer API visitor pass. Its UUID is scoped to the "
        "Access Developer API visitor family and must not be passed to other Access user or credential operations."
    )
)
class Visitor:
    """Typed projection of the shared visitor field model."""

    id: strawberry.ID | None
    name: str | None
    first_name: str | None
    last_name: str | None
    host_user_id: str | None
    valid_from: str | None
    valid_until: str | None
    status: str | None
    credential_count: int | None
    email: str | None
    phone: str | None
    company: str | None
    visit_reason: str | None
    remarks: str | None
    access_policy_ids: list[str] | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": [
                "name",
                "company",
                "valid_from",
                "valid_until",
                "status",
            ],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Visitor":
        normalized = visitor_from_controller(obj)
        return cls(**normalized.model_dump())

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
