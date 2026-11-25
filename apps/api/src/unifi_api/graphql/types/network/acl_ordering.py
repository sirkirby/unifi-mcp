"""Strawberry types for the Integration API ACL rule ordering family.

- ``AclRuleOrdering`` — the ordering read: the site's ACL rule IDs in
  controller order, a bare ``list[str]``.
- ``IntegrationAclRule`` — one rule as the Integration API lists it; its
  ``id`` is the ordering array's ID source (an Integration API UUID family,
  not the V2 MAC ACL rule Mongo ``_id``).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.network.models.acl_ordering import integration_acl_rule_from_controller
from unifi_core.redaction import redact_sensitive_fields


@strawberry.type(
    description=(
        "User-defined ACL rule ordering. These IDs are scoped to the ACL-ordering "
        "tool family — do not pass V2 MAC ACL rule Mongo _id values here."
    )
)
class AclRuleOrdering:
    ordered_acl_rule_ids: list[str]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind, "primary_key": "ordered_acl_rule_ids", "display_columns": ["ordered_acl_rule_ids"]}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AclRuleOrdering":
        if isinstance(obj, dict):
            ids = obj.get("orderedAclRuleIds")
        else:
            ids = obj
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise ValueError("Controller returned an invalid ACL rule ordering response")
        return cls(ordered_acl_rule_ids=ids)

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(
    description=(
        "One MAC ACL rule as the Integration API lists it (read-only). Its id is an "
        "Integration API UUID scoped to the ACL-ordering tool family — do not pass it to "
        "V2 MAC ACL rule tools or translate between the two families."
    )
)
class IntegrationAclRule:
    id: strawberry.ID
    name: str | None
    index: int | None
    action: str | None
    enabled: bool | None
    type: str | None
    network_id_filter: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    raw: strawberry.scalars.JSON | None  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "index", "action", "enabled"],
            "sort_default": "index:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "IntegrationAclRule":
        # Delegate to the shared model so the field mapping lives in one place;
        # the passthrough fields redact at the boundary.
        fields = integration_acl_rule_from_controller(obj).model_dump()
        return cls(**redact_sensitive_fields(fields, redact_sensitive=redact_sensitive))

    def to_dict(self) -> dict:
        return asdict(self)
