"""Read projection for V2 Network NAT rules."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.network.models.nat import from_controller
from unifi_core.redaction import redact_sensitive_fields


@strawberry.type(
    description=(
        "A V2 controller NAT rule. Its ID is scoped to the NAT tool family; "
        "do not pass it to port-forward or Integration API tools."
    )
)
class NatRule:
    id: strawberry.ID | None
    is_predefined: bool | None
    setting_preference: str | None
    type: str | None
    description: str | None
    enabled: bool | None
    rule_index: int | None
    protocol: str | None
    ip_version: str | None
    in_interface: str | None
    out_interface: str | None
    ip_address: str | None
    port: str | None
    logging: bool | None
    exclude: bool | None
    pppoe_use_base_interface: bool | None
    source_filter: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    destination_filter: strawberry.scalars.JSON | None  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["description", "type", "enabled", "rule_index"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "NatRule":
        fields = from_controller(obj).model_dump()
        return cls(**redact_sensitive_fields(fields, redact_sensitive=redact_sensitive))

    def to_dict(self) -> dict:
        return asdict(self)
