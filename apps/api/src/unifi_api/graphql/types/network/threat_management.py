"""Public site-wide threat management (IDS/IPS) settings projection."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.network.models.threat_management import (
    ThreatManagementSettings as CoreThreatManagementSettings,
)
from unifi_core.network.models.threat_management import (
    threat_management_from_controller,
)
from unifi_core.redaction import redact_sensitive_fields


@strawberry.type(description="Site-wide threat management (IDS/IPS) and traffic identification settings.")
class ThreatManagementSettings:
    ips_mode: str | None = strawberry.field(
        default=None,
        description="Raw IPS operation mode string from controller (e.g. 'disabled', 'ids', 'ips', 'ipsInline').",
    )
    enabled: bool | None = strawberry.field(
        default=None,
        description=(
            "Normalized enabled state: true for known active modes, false for disabled, null for unknown/missing."
        ),
    )
    enabled_categories: list[str] | None = strawberry.field(
        default=None,
        description="Enabled threat category codes (null when absent from controller).",
    )
    enabled_networks: list[str] | None = strawberry.field(
        default=None,
        description="Protected network IDs (null when absent from controller).",
    )
    traffic_identification_enabled: bool | None = strawberry.field(
        default=None,
        description="Traffic identification (DPI) enabled state (strict boolean, null if missing/malformed).",
    )
    device_fingerprinting_enabled: bool | None = strawberry.field(
        default=None,
        description="Device fingerprinting enabled state (strict boolean, null if missing/malformed).",
    )
    advanced_filtering_preference: str | None = strawberry.field(
        default=None,
        description="Advanced filtering preference; null when missing or malformed.",
    )

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "ThreatManagementSettings":
        preference = None
        if isinstance(obj, CoreThreatManagementSettings):
            core = obj
        elif isinstance(obj, dict):
            raw_preference = obj.get("advanced_filtering_preference")
            if isinstance(raw_preference, str):
                preference = raw_preference
            if "ips" in obj or "dpi" in obj:
                core = threat_management_from_controller(ips=obj.get("ips"), dpi=obj.get("dpi"))
            elif "traffic_identification_enabled" in obj or "device_fingerprinting_enabled" in obj:
                core = threat_management_from_controller(
                    ips=obj,
                    dpi={
                        "enabled": obj.get("traffic_identification_enabled"),
                        "fingerprintingEnabled": obj.get("device_fingerprinting_enabled"),
                    },
                )
            else:
                core = threat_management_from_controller(ips=obj, dpi=None)
        else:
            core = CoreThreatManagementSettings()
        data = redact_sensitive_fields(core.model_dump(), redact_sensitive=redact_sensitive)
        if preference is None:
            preference = data.get("advanced_filtering_preference")
        return cls(
            ips_mode=data.get("ips_mode"),
            enabled=data.get("enabled"),
            enabled_categories=data.get("enabled_categories"),
            enabled_networks=data.get("enabled_networks"),
            traffic_identification_enabled=data.get("traffic_identification_enabled"),
            device_fingerprinting_enabled=data.get("device_fingerprinting_enabled"),
            advanced_filtering_preference=preference,
        )

    def to_dict(self) -> dict:
        return asdict(self)
