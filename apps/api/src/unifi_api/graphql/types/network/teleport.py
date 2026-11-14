"""Public Teleport VPN settings projection."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.network.models.teleport import TeleportSettings as CoreTeleportSettings
from unifi_core.network.models.teleport import teleport_from_controller
from unifi_core.redaction import redact_sensitive_fields


@strawberry.type(description="Teleport VPN settings; only subnet_cidr is writable.")
class TeleportSettings:
    enabled: bool | None
    subnet_cidr: str | None
    id: strawberry.ID | None
    site_id: str | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "TeleportSettings":
        core = obj if isinstance(obj, CoreTeleportSettings) else teleport_from_controller(obj)
        data = redact_sensitive_fields(core.model_dump(), redact_sensitive=redact_sensitive)
        return cls(
            enabled=data["enabled"],
            subnet_cidr=data["subnet_cidr"],
            id=data["id"],
            site_id=data["site_id"],
        )

    def to_dict(self) -> dict:
        return asdict(self)
