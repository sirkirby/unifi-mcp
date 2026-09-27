"""Public site-wide mDNS service settings projection."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.network.models.mdns import MdnsSettings as CoreMdnsSettings
from unifi_core.network.models.mdns import mdns_from_controller
from unifi_core.redaction import redact_sensitive_fields


@strawberry.type
class PredefinedService:
    code: str | None


@strawberry.type
class CustomService:
    name: str | None
    address: str | None


@strawberry.type(description="Site-wide mDNS services; network scope is read-only.")
class MdnsSettings:
    id: strawberry.ID | None
    site_id: str | None
    mode: str | None
    predefined_services: list[PredefinedService]
    custom_services: list[CustomService]
    enabled_for: str | None
    enabled_for_network_ids: list[str]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "MdnsSettings":
        core = obj if isinstance(obj, CoreMdnsSettings) else mdns_from_controller(obj)
        data = redact_sensitive_fields(core.model_dump(), redact_sensitive=redact_sensitive)
        return cls(
            id=data["id"],
            site_id=data["site_id"],
            mode=data["mode"],
            predefined_services=[PredefinedService(**item) for item in data["predefined_services"]],
            custom_services=[CustomService(**item) for item in data["custom_services"]],
            enabled_for=data["enabled_for"],
            enabled_for_network_ids=data["enabled_for_network_ids"],
        )

    def to_dict(self) -> dict:
        return asdict(self)
